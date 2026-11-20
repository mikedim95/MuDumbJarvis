"""Route blocked direct-report work and preserve human decisions on its CEO issue."""
import hashlib
import json
import re
import time
import urllib.error
from uuid import NAMESPACE_URL, UUID, uuid5

PREFIX = 'jarvis-blocker:'
REPORT = 'CEO review requested. '
WAITING = 'Waiting for your decision. '
BLOCKED_ON = 'Blocked on '
GENERIC_QUESTION = 'What input or change of scope can you provide so the team can continue?'
PACKAGE_REQUEST = 'Requested operator provisioning for sandbox package '
PACKAGE_KEY = 'jarvis-package-review:'


def package_name(value):
    if (not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9.+-]{0,62}', value)
            or '..' in value or value.endswith(('.deb', '.rpm'))):
        raise ValueError('Use one package name, such as jq.')
    return value


def blocker_packages(action):
    if not action.startswith(REPORT):
        return []
    action = action[len(REPORT):]
    if action.startswith(PACKAGE_REQUEST):
        try:
            return [package_name(name) for name in action[len(PACKAGE_REQUEST):].split(', ')]
        except ValueError:
            return []
    # Older workers recorded this explicit operator handoff before a structured
    # package request existed. Ignore incidental mentions of software names.
    reason = action.removeprefix('Worker reports incomplete work: blocked. ')
    match = re.match(r'Operator must provision compatible ([a-z0-9+.-]+) and dependencies inside this sandbox\b', reason, re.I)
    if not match:
        match = re.fullmatch(r'Operator must complete the already-approved provisioning and expose '
                             r'([a-z0-9+.-]+) in the sandbox before verification can succeed\.?', reason, re.I)
    if match:
        try:
            return [package_name(match[1].lower())]
        except ValueError:
            pass
    return []


def reported_packages(child, report):
    """Require agreement between the native assignment blocker and its worker's report."""
    if (child.get('status') != 'blocked' or report.get('authorAgentId') != child.get('assigneeAgentId')
            or not report.get('createdByRunId')):
        return []
    contents, marker, _ = (report.get('body') or '').partition('\nJARVIS_EXECUTION_EVIDENCE=')
    action = (child.get('unblockDescriptor') or {}).get('action') or ''
    reason = action.removeprefix(REPORT)
    if not marker:
        return []
    if reason.startswith(PACKAGE_REQUEST):
        if reason not in contents.splitlines():
            return []
    elif reason.removeprefix('Worker reports incomplete work: blocked. ') not in contents:
        return []
    return blocker_packages(action)


def worker_package_requests(child, comments):
    names = set()
    for row in comments:
        if row.get('authorAgentId') != child['assigneeAgentId'] or not row.get('createdByRunId'):
            continue
        body = row.get('body') or ''
        if body.startswith(PACKAGE_REQUEST):
            try:
                name = package_name(body[len(PACKAGE_REQUEST):])
            except ValueError:
                continue
            nonce = str(uuid5(NAMESPACE_URL, f'jarvis-package:{child["id"]}:{child["assigneeAgentId"]}:{name}'))
            if row.get('clientRequestId') == nonce:
                names.add(name)
    reports = [r for r in comments if r.get('authorAgentId') == child['assigneeAgentId']
               and r.get('createdByRunId') and '\nJARVIS_EXECUTION_EVIDENCE=' in (r.get('body') or '')]
    if reports:
        names.update(reported_packages(child, max(reports, key=lambda r: r.get('createdAt') or '')))
    return sorted(names)


def package_confirmation(child, name, owner=None):
    child_id, agent = str(UUID(child['id'])), str(UUID(child['assigneeAgentId']))
    name = package_name(name)
    return {'kind': 'request_confirmation', 'idempotencyKey': f'{PACKAGE_KEY}{child_id}:{agent}:{name}',
        'title': f'Software request for {child["identifier"]}',
        'summary': 'Yes queues this Debian package and its dependencies for this assignment’s offline package environment.',
        'continuationPolicy': 'none', 'resolverPolicy': 'human_only',
        **({'addresseeUserId': owner} if owner else {}),
        'payload': {'version': 1, 'prompt': f'{child["identifier"]} needs {name}. Authorize the runtime operator to provide it for this assignment?',
            'acceptLabel': 'Approve', 'rejectLabel': 'Decline', 'rejectRequiresReason': False,
            'supersedeOnUserComment': False}}


def package_decision(row, issue_id, ceo_id):
    key = row.get('idempotencyKey') or ''
    if (not key.startswith(PACKAGE_KEY) or row.get('issueId') != issue_id
            or row.get('kind') != 'request_confirmation' or row.get('continuationPolicy') != 'none'
            or row.get('resolverPolicy') != 'human_only' or row.get('addresseeAgentId')
            or not (row.get('createdByAgentId') == ceo_id or
                    (row.get('createdByUserId') and not row.get('createdByAgentId')))):
        return None
    try:
        child, agent, name = key[len(PACKAGE_KEY):].split(':')
        if str(UUID(child)) != child or str(UUID(agent)) != agent:
            return None
        package_name(name)
    except (ValueError, TypeError):
        return None
    payload = row.get('payload') or {}
    if any(payload.get(k) is not None for k in ('target', 'toolAction', 'secretProposal')) or not payload.get('prompt'):
        return None
    return {'id': row['id'], 'child_id':child, 'agent_id':agent, 'package':name, 'question':payload['prompt'],
            'key':key, 'status':row['status'], 'created':row.get('createdAt') or '', 'resolved_at':row.get('resolvedAt'),
            'answer':row['status'] if row.get('resolvedByUserId') and row['status'] in ('accepted','rejected') else None}


def generic_question(text):
    return text.rstrip().casefold().endswith(GENERIC_QUESTION.casefold())


def blocked_status(child, reason=None):
    detail = (reason or (child.get('unblockDescriptor') or {}).get('action') or 'The assignment remains incomplete.').strip()
    detail = detail.removeprefix(REPORT).removeprefix('Worker reports incomplete work: blocked. ')
    if generic_question(detail):
        detail = detail[:-len(GENERIC_QUESTION)].strip() or 'The assignment remains incomplete.'
    return f"{BLOCKED_ON}{child['identifier']} — {detail.strip()[:900]}"



def objective_blocker(response):
    for paragraph in response.split('\n\n'):
        if re.search(r'\b(?:overall\s+)?(?:task|objective|goal|request|assignment|expansion|research|work|delegation)\s+(?:remains?|is)\s+(?:(?:currently|still)\s+)?(?:blocked|incomplete|unfinished|unmet)\b', paragraph, re.I):
            return paragraph.strip()[:900]
    return None


def approved_operator_request(text, child, reviews):
    """An operator handoff about a decided package does not ask its owner for a decision."""
    if not isinstance(text, str) or not re.match(
            r'(?i)^(?:can|could|will|would) (?:the |a )?(?:runtime )?operator '
            r'(?:provide|provision|install|repair|configure|expose)\b', text):
        return None
    if re.search(r'(?i)\b(?:would you|do you|should we|which option|choose|change (?:the )?scope)\b', text):
        return None
    return next((r for r in reviews if r.get('package') and r.get('answer') == 'accepted'
        and r['child_id'] == child.get('id') and r.get('agent_id') == child.get('assigneeAgentId')
        and re.search(r'(?<![\w.+-])' + re.escape(r['package']) + r'(?![\w+-]|\.[\w])', text, re.I)), None)


def project_operator_request(text):
    match = re.match(r'^(?:can|could|would|will) the runtime operator (.+)', text, re.I)
    if not match or re.search(r'\b(?:you|your|choose|authorize|approve)\b|\bor (?:should|would|do|can)\b', text, re.I):
        return None
    request = match[1].casefold()
    if re.match(r'(?:restore|repair|fix) (?:the )?(?:authenticated )?project[- ]terminal (?:scope|access|connection)\b', request):
        return 'The runtime operator needs to check the connection to the project terminal.'
    if (request.startswith(('provide ', 'provision ', 'enable ')) and 'project container' in request
            and re.search(r'\b(?:package[- ]maintenance|noninteractive sudo|root execution)\b', request)):
        return 'The runtime operator can refresh the project OS image and switch the lab while preserving project files. Systems can verify the release afterwards.'
    return None


def decisions(rows, issue_id, ceo_id):
    result = []
    for row in rows:
        package = package_decision(row, issue_id, ceo_id)
        if package:
            result.append(package)
            continue
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
    packages = turn.get('worker_package_requests', {}).get(child['id'], [])
    if packages:
        path = '/issues/' + issue['id'] + '/interactions'
        existing = {d['key']: d for d in decisions(api('GET', path), issue['id'], turn['agent'])}
        reviewed = []
        for name in packages:
            form = package_confirmation(child, name, issue.get('responsibleUserId') or issue.get('createdByUserId'))
            decision = existing.get(form['idempotencyKey'])
            if not decision:
                row = api('POST', path, form, turn['run'])
                decision = package_decision(row, issue['id'], turn['agent'])
                if not decision:
                    raise ValueError('Paperclip did not confirm the CEO package request.')
            reviewed.append(decision)
        pending = next((d for d in reviewed if d['status'] == 'pending'), None)
        if pending:
            turn['owner_question'] = pending
        return pending or reviewed[0]
    if not 10 <= len(text) <= 500 or not 10 <= len(reason) <= 900:
        raise ValueError('Supply one short decision question in text and explain in plan what you tried and why you need the owner.')
    if generic_question(text):
        raise ValueError('Report the blocker, or ask for a specific decision the owner has not already made.')
    operator_request = project_operator_request(text)
    if operator_request:
        turn['operator_blocker'] = blocked_status(child, operator_request)
        return {'next_actor':'runtime_operator'}
    for item in (child, issue):
        identifier = item.get('identifier')
        if identifier and item.get('id'):
            text = text.replace(identifier + ' (' + item['id'] + ')', identifier)
            text = text.replace(item['id'], identifier)
    path = '/issues/' + issue['id'] + '/interactions'
    previous = decisions(api('GET', path), issue['id'], turn['agent'])
    approved = approved_operator_request(text, child, previous)
    if approved:
        turn['operator_blocker'] = blocked_status(child, 'Package approval is recorded. The remaining capability requires runtime operator review.')
        return {**approved, 'next_actor':'runtime_operator'}
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
        re.split(r'(?<=[.!?])\s+', line)) if sentence.endswith('?') and 10 <= len(sentence) <= 500
        and not generic_question(sentence)), None)
    reason = reason or (child.get('unblockDescriptor') or {}).get('action') or 'No executable correction was recorded.'
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
