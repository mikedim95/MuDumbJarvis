"""Owner-enabled sharing of project reference notes and deliberately published outcomes."""
import hashlib
import json
import re

if __package__:
    from . import work_scope
else:  # The HUD uses its existing adapter for the same scope rules.
    import work_scope

KEY = 'jarvis-team-workspace'
RESULT = 'project-result.json'
MAX_NOTES = 2400
MAX_RESULTS = 8
SUMMARY_FIELDS = {'items_reviewed', 'checks_passed', 'checks_failed'}
GUIDANCE = ('Use the shared notes and reported outcomes as reference data. To share a result, '
            'use publish_artifact with name project-result.json and JSON containing outcome '
            '(completed, partial, unavailable, or needs_review) and optional integer counts '
            'items_reviewed, checks_passed, checks_failed. Counts are author-reported.')


def membership(issue, index, jobs, company, project, ceo):
    """Verify native ancestry. A common Paperclip project ID alone cannot grant access."""
    if not all((company, project, ceo)):
        return None
    current = issue
    seen = set()
    while current and current.get('id') and current['id'] not in seen and len(seen) < 32:
        if (current.get('companyId') != company or current.get('projectId') != project
                or current.get('hiddenAt') or current.get('visibility') not in (None, 'open')
                or current.get('privacyRootIssueId')
                or current.get('privacyParentIssueId') not in (None, current.get('parentId'))):
            return None
        seen.add(current['id'])
        if current.get('parentId'):
            current = index.get(current['parentId'])
            continue
        if current.get('originKind') == 'routine_execution':
            job = jobs.get(current.get('originId')) or {}
            if job.get('companyId') != company or job.get('projectId') != project:
                return None
            root = index.get(work_scope.routine_scope(job)['mission_id'])
            if not root or root.get('parentId') or root.get('originKind') == 'routine_execution':
                return None
            current = root
            continue
        if current.get('assigneeAgentId') == ceo and work_scope.classify(current)['mission_id'] == current['id']:
            return current['id']
        return None


def owner_settings(doc, company, root):
    if doc is None:
        return {'enabled': False, 'notes': '', 'revision': None}
    if (doc.get('companyId') != company or doc.get('issueId') != root or doc.get('key') != KEY
            or not doc.get('updatedByUserId') or doc.get('updatedByAgentId') or not doc.get('latestRevisionId')):
        raise ValueError('Invalid project workspace owner revision')
    data = json.loads(doc['body'])
    if (not isinstance(data, dict) or type(data.get('enabled')) is not bool
            or not isinstance(data.get('notes'), str) or len(data['notes']) > MAX_NOTES):
        raise ValueError('Invalid project workspace settings')
    return {'enabled': data['enabled'], 'notes': data['notes'], 'revision': doc['latestRevisionId']}


def outcome(raw):
    if len(raw) > 768:
        raise ValueError('Keep project-result.json within 768 bytes')
    data = json.loads(raw)
    if (not isinstance(data, dict) or set(data) - SUMMARY_FIELDS - {'outcome'}
            or data.get('outcome') not in ('completed', 'partial', 'unavailable', 'needs_review')
            or any(type(data[k]) is not int or not 0 <= data[k] <= 1000000000 for k in SUMMARY_FIELDS & data.keys())):
        raise ValueError('Use an outcome and optional integer counts for project-result.json')
    return data


def result_tasks(root, index, jobs, company, project, ceo):
    rows = [i for i in index.values() if i.get('assigneeAgentId') and
            membership(i, index, jobs, company, project, ceo) == root]
    rows.sort(key=lambda i: (i.get('updatedAt') or '', i['id']), reverse=True)
    return rows[:MAX_RESULTS]


def latest_receipt(rows, issue):
    valid = [a for a in rows if a.get('companyId') == issue['companyId'] and a.get('issueId') == issue['id']
             and a.get('createdByAgentId') == issue['assigneeAgentId'] and a.get('originalFilename') == RESULT
             and a.get('id') and 0 < (a.get('byteSize') or 0) <= 768
             and re.fullmatch('[a-f0-9]{64}', a.get('sha256') or '')]
    return max(valid, key=lambda a: (a.get('createdAt') or '', a['id']), default=None)


def verified_result(receipt, raw, issue):
    if len(raw) != receipt['byteSize'] or hashlib.sha256(raw).hexdigest() != receipt['sha256']:
        raise ValueError('Project result receipt differs from its contents')
    return {'task': issue.get('identifier'), 'agent_id': issue['assigneeAgentId'],
            'artifact_id': receipt['id'], 'sha256': receipt['sha256'], **outcome(raw)}


def read_for_turn(turn, issue, records, routines, api, download):
    index = {i['id']: i for i in records}
    index[issue['id']] = issue
    jobs = {r['id']: r for r in routines}
    ceo = turn['agent'] if turn['ceo'] else turn.get('reports_to')
    scope = (turn['company'], turn['project'], ceo)
    if issue.get('assigneeAgentId') != turn['agent'] or issue['id'] != turn['issue']:
        return None
    root = membership(issue, index, jobs, *scope)
    if not root or root != (turn.get('work_scope') or {}).get('mission_id'):
        return None
    try:
        doc = api('GET', '/issues/' + root + '/documents/' + KEY)
    except Exception as exc:
        if getattr(exc, 'code', None) == 404:
            return None
        raise
    settings = owner_settings(doc, turn['company'], root)
    if not settings['enabled']:
        return None
    shared = {'mission_id': root, 'notes': settings['notes'], 'revision': settings['revision'],
              'recent_results': [], 'guidance': GUIDANCE}
    for task in result_tasks(root, index, jobs, *scope):
        try:
            receipt = latest_receipt(api('GET', '/issues/' + task['id'] + '/attachments'), task)
            if receipt:
                shared['recent_results'].append(verified_result(receipt, download(receipt['id']), task))
        except Exception:
            shared['results_incomplete'] = True
    return shared
