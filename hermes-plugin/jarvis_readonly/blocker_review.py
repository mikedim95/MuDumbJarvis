"""Route blocked direct-report work and preserve human decisions on its CEO issue."""
import hashlib
import json
import re
import time
import urllib.error
from uuid import NAMESPACE_URL, uuid5

PREFIX = 'jarvis-blocker:'
REPORT = 'CEO review requested. '
WAITING = 'Waiting for your decision. '


def objective_blocker(response):
    for paragraph in response.split('\n\n'):
        if re.search(r'\b(?:overall\s+)?(?:task|objective|goal)\s+(?:remains?|is)\s+(?:blocked|incomplete|unfinished|unmet)\b', paragraph, re.I):
            return paragraph.strip()[:900]
    return None


def decisions(rows, issue_id, ceo_id):
    result = []
    for row in rows:
        if (row.get('issueId') != issue_id or row.get('createdByAgentId') != ceo_id
                or row.get('kind') != 'ask_user_questions'
                or not (row.get('idempotencyKey') or '').startswith(PREFIX)):
            continue
        form = (row.get('payload') or {}).get('questionSet') or {}
        for question in form.get('questions') or []:
            if question.get('answerMode') != 'text' or not question.get('id', '').startswith('child-'):
                continue
            answers = (row.get('result') or {}).get('answers') or []
            answer = next((a.get('otherText') for a in answers if a.get('questionId') == question['id']), None)
            result.append({'id': row['id'], 'child_id': question['id'][6:], 'question': question['prompt'],
                           'status': row['status'], 'answer': answer if row.get('resolvedByUserId') else None,
                           'key': row['idempotencyKey'], 'created': row.get('createdAt') or ''})
    return sorted(result, key=lambda d: d['created'], reverse=True)


def wake_request(api, turn, comments, human, children):
    """Resolve a native blocker wake to its original conversation request, including older requests."""
    latest = human[-1] if human else None
    if not latest:
        return latest
    children = [c for c in children if c.get('parentId') == turn['issue'] and c.get('companyId') == turn['company']
                and c.get('projectId') == turn['project']]
    if not any(not (c.get('description') or '').startswith('[JARVIS REQUEST ' + latest['id'] + ']\n') for c in children):
        return latest
    if not any((c.get('body') or '').startswith(('[JARVIS WORKER BLOCKER ', WAITING, 'System relay:')) for c in comments):
        return latest
    wake = api('GET', '/heartbeat-runs/' + turn['run']).get('contextSnapshot') or {}
    if wake.get('issueId') != turn['issue']:
        return latest
    child_id = None
    if wake.get('interactionId'):
        rows = decisions(api('GET', '/issues/' + turn['issue'] + '/interactions'), turn['issue'], turn['agent'])
        child_id = next((d['child_id'] for d in rows if d['id'] == wake['interactionId'] and d['answer']), None)
    elif wake.get('source') == 'issue.stop_relay':
        child_id = wake.get('childIssueId')
    else:
        comment = next((c for c in comments if c.get('id') == (wake.get('wakeCommentId') or wake.get('commentId'))), {})
        marker, _, body = (comment.get('body') or '').partition('\n')
        if marker.startswith('[JARVIS WORKER BLOCKER '):
            for c in children:
                nonce = str(uuid5(NAMESPACE_URL, c['id'] + ':' + marker))
                if ((comment.get('authorAgentId') == c.get('assigneeAgentId') and body.startswith(c['identifier'] + ' '))
                        or (comment.get('authorUserId') and comment.get('clientRequestId') == nonce)):
                    child_id = c['id']
                    break
    child = next((c for c in children if c['id'] == child_id), {})
    match = re.match(r'^\[JARVIS REQUEST (initial|[0-9a-f-]{36})\]\n', child.get('description') or '')
    if not match:
        return latest
    if match[1] == 'initial':
        return None
    return next((c for c in human if c['id'] == match[1]), latest)


def ask(api, turn, issue, child, text, reason):
    if not 10 <= len(text) <= 500 or not 10 <= len(reason) <= 900:
        raise ValueError('Supply one short decision question in text and explain in plan what you tried and why you need the owner.')
    path = '/issues/' + issue['id'] + '/interactions'
    previous = decisions(api('GET', path), issue['id'], turn['agent'])
    pending = next((item for item in previous if item['status'] == 'pending'
                    and item['child_id'] in turn.get('review_child_ids', [child['id']])), None)
    if pending:
        turn['owner_question'] = pending
        return pending
    basis = str((child.get('unblockDescriptor') or {}).get('action') or child['status'])
    answered = [d for d in previous if d['child_id'] == child['id'] and d['answer']]
    if any(d['question'].strip().casefold() == text.strip().casefold() for d in answered):
        raise ValueError('The owner already answered this question. Apply that answer to the existing assignment.')
    revision = answered[0]['id'] if answered else ''
    key = PREFIX + child['id'] + ':' + hashlib.sha256((basis + revision).encode()).hexdigest()[:20]
    owner = issue.get('responsibleUserId') or issue.get('createdByUserId')
    question = {'id': 'child-' + child['id'], 'prompt': text, 'required': True, 'answerMode': 'text'}
    row = api('POST', path, {'kind': 'ask_user_questions', 'idempotencyKey': key,
        'title': 'Decision needed for ' + child['identifier'], 'summary': reason,
        'resolverPolicy': 'human_only', 'continuationPolicy': 'wake_assignee',
        **({'addresseeUserId': owner} if owner else {}),
        'payload': {'version': 1, 'questionSet': {'schema': 'paperclip.question_set.v1', 'questions': [question]}}}, turn['run'])
    turn['owner_question'] = decisions([row], issue['id'], turn['agent'])[0]
    return turn['owner_question']


def disposition(response, child, reason=None):
    """Persist the CEO's final question when it was written as prose instead of a tool call."""
    lines = [line.strip(' *#>-') for line in response.splitlines() if line.strip()]
    question = next((sentence for line in reversed(lines) for sentence in reversed(
        re.split(r'(?<=[.!?])\s+', line)) if sentence.endswith('?') and 10 <= len(sentence) <= 500), None)
    reason = reason or (child.get('unblockDescriptor') or {}).get('action') or 'No executable correction was recorded.'
    if not question:
        question = ('For ' + child['identifier'] + ', ' + reason[:280].rstrip('.!?') +
                    '. What input or change of scope can you provide so the team can continue?')
    return question, ('CEO review of ' + child['identifier'] + '. ' + reason)[:900]


def partial_reports(reporting, turn, child):
    """Inspect the blocked worker's signed report without accepting it as completed work."""
    from .employee_work import attachment_bytes, artifact_run_id
    comments = reporting.api('GET', '/issues/' + child['id'] + '/comments')
    updates = sorted((c for c in comments if c.get('authorAgentId') == child['assigneeAgentId']
                      and '\nJARVIS_EXECUTION_EVIDENCE=' in (c.get('body') or '')),
                     key=lambda c: c.get('createdAt') or '', reverse=True)
    if not updates:
        return []
    comment = updates[0]
    try:
        proof = json.loads(comment['body'].rsplit('\nJARVIS_EXECUTION_EVIDENCE=', 1)[1])
    except ValueError:
        return []
    run_id = comment.get('createdByRunId')
    if not (run_id and reporting.authentic_evidence(proof) and proof.get('task_status') == 'blocked'
            and proof.get('paperclip_run_id') == run_id and proof.get('issue_id') == child['id']
            and proof.get('agent_id') == child['assigneeAgentId'] and proof.get('company_id') == turn['company']):
        return []
    receipts = {r['id']: r for r in proof.get('artifacts', []) if r.get('id') and r.get('sha256')}
    result = []
    for row in reporting.api('GET', '/issues/' + child['id'] + '/attachments'):
        receipt = receipts.get(row['id'])
        if (not receipt or row.get('issueId') != child['id'] or row.get('createdByAgentId') != child['assigneeAgentId']
                or artifact_run_id(row) != run_id or not (row.get('originalFilename') or '').lower().endswith(('.md', '.txt'))
                or not 0 < (row.get('byteSize') or 0) <= 131072):
            continue
        raw = attachment_bytes(row['id'])
        if hashlib.sha256(raw).hexdigest() == receipt['sha256']:
            result.append({'name': row['originalFilename'], 'excerpt': raw.decode('utf-8', 'replace')[:2400]})
            if len(result) == 2:
                break
    return result


def report(api, turn, child, reason):
    parent_id = child.get('parentId')
    manager = turn.get('reports_to')
    if not parent_id or not manager:
        return
    parent = api('GET', '/issues/' + parent_id)
    if (parent.get('assigneeAgentId') != manager or parent.get('companyId') != turn['company']
            or parent.get('projectId') != turn['project'] or parent.get('status') in ('done', 'cancelled')
            or parent.get('hiddenAt') or parent.get('executionBlocker')):
        return
    marker = '[JARVIS WORKER BLOCKER ' + turn['run'] + ']'
    path = '/issues/' + parent_id + '/comments'
    for attempt in range(3):
        try:
            comments = api('GET', path)
            if any(c.get('authorAgentId') == turn['agent'] and (c.get('body') or '').startswith(marker) for c in comments):
                return
            api('POST', path, {'body': marker + '\n' + child['identifier'] + ' needs CEO review. ' + reason[:1200]}, turn['run'])
            return
        except urllib.error.HTTPError as exc:
            if exc.code == 403 and any(c.get('authorType') == 'system' and
                    (c.get('body') or '').startswith('System relay: [' + child['identifier'] + ']')
                    for c in api('GET', path)):
                return  # Paperclip handles parent reports for restricted worker trust.
            if exc.code < 500 or attempt == 2:
                raise
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(attempt + 1)
