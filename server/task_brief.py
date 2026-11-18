"""Short project-tree captions from current Paperclip state and published assignee updates."""
import re

from csi_events import public_body


# Ignore receipt appendices, tool payloads, file listings and implementation paths.
APPENDIX = re.compile(r'^(?:```|Verified (?:(?:delegated execution|execution|local_ollama_models) data\b|runtime identity:))', re.M | re.I)
FILE_REFERENCE = re.compile(
    r'https?://|(?<!\w)/(?:[\w.-]+/)+|\b[\w.-]+\.(?:md|txt|json|py|js|ts|yaml|yml|csv|pdf|log|html)\b'
    r'|\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', re.I)
BLOCKED_REPLY = re.compile(r'^(?:blocked|incomplete)\s*[:—-]\s*', re.I)


OUTCOME_HEADING = re.compile(
    r'^(?:key findings?|findings?|results?|outcomes?|interpretation|conclusions?|recommendations?|bottom line)'
    r'(?:\s*[:—]\s*|$)', re.I)
IMPLICATION = re.compile(
    r'\b(?:recommend(?:ed)?|retain|demonstrates?|indicates?|this means|justified|partial|'
    r'unmet|passed|point-in-time|remains? (?:unverified|unknown|unavailable)|did not meet)\b', re.I)
RECEIPT = re.compile(r'\b(?:attachment receipt|artifact (?:id|reference)|confirms? persistence|runtime output delivery)\b', re.I)


def caption(text, *, outcome=False, covered='', max_sentences=2):
    """Select complete sentences so a word limit cannot cut off the qualification."""
    lines = APPENDIX.split(public_body(text), maxsplit=1)[0].splitlines()
    candidates = []
    next_is_outcome = False
    covered_words = set(re.findall(r'\w+', covered.casefold()))
    for line in lines:
        line = line.strip(' \t#>*_`-').replace('**', '').replace('`', '')
        if not line:
            continue
        heading = OUTCOME_HEADING.match(line)
        priority = 2 if heading or next_is_outcome else 0
        next_is_outcome = False
        if heading:
            line = line[heading.end():].strip()
            if not line:
                next_is_outcome = True
                continue
        if line.startswith(('{', '[', '|')) or re.match(r'^\S+\s+[—-]\s+\d', line):
            continue
        if line.endswith(':'):
            if not re.search(r'\b(?:completed|replied|passed|failed|found)\b', line, re.I):
                continue
            line = line[:-1].rstrip() + '.'
        for sentence in re.split(r'(?<=[.!?])\s+', line):
            if FILE_REFERENCE.search(sentence):
                lead, colon, _ = sentence.partition(':')
                if not colon or FILE_REFERENCE.search(lead) or not re.search(r'\b(?:passed|failed|completed|found)\b', lead, re.I):
                    continue
                sentence = lead.rstrip() + '.'
            if RECEIPT.search(sentence) or len(sentence) > 380:
                continue
            words = set(re.findall(r'\w+', sentence.casefold()))
            if not words or words <= covered_words:
                continue
            rank = max(priority, int(bool(IMPLICATION.search(sentence)))) if outcome else 0
            candidates.append((rank, len(candidates), sentence))
    if not candidates:
        return ''
    selected = []
    for rank, index, sentence in sorted(candidates, key=lambda row: (-row[0], row[1])):
        if selected and (len(selected[0][1]) + len(sentence) > 250 or rank < selected_rank):
            continue
        selected.append((index, sentence))
        selected_rank = rank
        if len(selected) == max_sentences:
            break
    return ' '.join(sentence for _, sentence in sorted(selected))


def assigned_update(task):
    """Read only the current assignee's prose since the latest operator instruction or run."""
    assignee = task.get('assigneeAgentId')
    if not assignee:
        return ''
    since = max((run.get('startedAt') or '' for run in task['runs']), default='')
    for comment in sorted(task['comments'], key=lambda row: row.get('createdAt') or '', reverse=True):
        body = str(comment.get('body') or '').strip()
        if comment.get('authorUserId') and body.startswith('[JARVIS USER MESSAGE'):
            break
        if since and comment.get('createdAt') and comment['createdAt'] < since:
            break
        if comment.get('authorAgentId') != assignee or not body or body.startswith('[JARVIS TOOL EVENT]'):
            continue
        if body.startswith(('[JARVIS ', 'CEO delegated ')):
            break
        return body
    return ''


def job_brief(task):
    status = task.get('status')
    children = task['children']
    update = assigned_update(task)
    result = ''
    active = bool(task.get('executionRunId') or any(run.get('status') == 'running' for run in task['runs']))
    action = (task.get('unblockDescriptor') or {}).get('action')
    if status == 'blocked':
        progress = caption(action) or 'Waiting for the blocker to be resolved.'
        # An older validator wrapped the worker's explicitly incomplete result in a diagnostic.
        # Never promote an unaccepted success claim from that diagnostic.
        worker_reply = update.partition('\nRuntime response:\n')[2].strip() or update
        if BLOCKED_REPLY.match(worker_reply):
            result = caption(BLOCKED_REPLY.sub('', worker_reply, count=1), covered=progress, max_sentences=1)
    elif status == 'done':
        result = caption(update, outcome=True) if not update.startswith(('Execution verification failed:', 'Verification failed:')) else ''
        progress = '' if result or children else 'No outcome was recorded.'
    elif status == 'in_progress':
        progress = caption(update, max_sentences=1) or caption(action) or ('A run is active.' if active else 'Work is in progress.')
    elif status == 'in_review':
        progress = caption(action) or caption(update, max_sentences=1) or 'Waiting for review.'
    elif status == 'cancelled':
        progress = 'Work stopped.'
    elif status in ('todo', 'backlog'):
        if active:
            progress = 'A run is active.'
        else:
            progress = 'Queued to start.' if status == 'todo' else 'Work has not been scheduled.'
    else:
        progress = 'No current state was reported.'

    if children and (status == 'done' or (status in ('todo', 'in_progress', 'in_review') and not (action or update))):
        done = sum(child.get('status') == 'done' for child in children)
        blocked = sum(child.get('status') == 'blocked' for child in children)
        count = len(children)
        progress = f'{done} of {count} delegated {"job" if count == 1 else "jobs"} complete.'
        if blocked:
            progress += f' {blocked} blocked.'
    return {'progress': progress, 'result': result}
