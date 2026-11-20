"""Native operator receipts for an approved, assignment-scoped Debian environment."""
import base64
import hashlib
import json
import re
from datetime import datetime
from uuid import UUID


def key(review_id):
    return 'jarvis-apt-' + str(UUID(review_id))


def binding(company, project, parent, child, agent, package, review_id):
    return {'company': company, 'project': project, 'parent': parent, 'issue': child,
            'agent': agent, 'package': package, 'review': review_id}


def read(doc, expected):
    if not doc or (doc.get('companyId'), doc.get('issueId')) != (expected['company'], expected['issue']):
        return None
    if not doc.get('updatedByUserId') or doc.get('updatedByAgentId') or doc.get('key') != key(expected['review']):
        return None
    try:
        # Paperclip normalizes escaped newlines in Markdown. Early receipts
        # saved plain stdout; new receipts encode its exact bytes.
        record = json.loads(doc['body'], strict=False)
    except (TypeError, ValueError, KeyError):
        return None
    if not isinstance(record, dict) or record.get('scope') != expected:
        return None
    status = record.get('status')
    if status == 'ready':
        if (not re.fullmatch(r'[0-9][a-zA-Z0-9:.+~-]{0,135}', str(record.get('version') or ''))
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', str(record.get('image') or ''))
                or not re.fullmatch(r'[0-9a-f]{64}', str(record.get('output_sha256') or ''))
                or record.get('command') != './.jarvis-bin/' + expected['package']
                or record.get('usage') != usage(expected['package'])):
            return None
        if 'stdout_base64' in record:
            try:
                raw = base64.b64decode(record['stdout_base64'], validate=True)
            except (ValueError, TypeError):
                return None
            if hashlib.sha256(raw).hexdigest() != record['output_sha256']:
                return None
        elif isinstance(record.get('output'), str):
            if not any(hashlib.sha256((record['output'] + nl).encode()).hexdigest() == record['output_sha256']
                       for nl in ('', '\n')):
                return None
        else:
            return None
        stamp = record.get('verified_at')
    elif status in ('unavailable', 'retrying') and isinstance(record.get('detail'), str):
        stamp = record.get('retry_after')
    else:
        return None
    try:
        if datetime.fromisoformat(stamp).tzinfo is None:
            return None
    except (TypeError, ValueError):
        return None
    return record


def usage(package):
    if package == 'nmap':
        return '--version (offline version check only)'
    if package == 'jq':
        return 'a jq filter on standard input, or --version'
    return '--package-version (installed Debian version)'


def ready_commands(documents, decisions, company, project, parent, issue, agent):
    """Return a runnable probe only for an accepted review and its matching operator receipt."""
    docs = {d.get('key'): d for d in documents}
    result = {}
    for choice in decisions:
        name = choice.get('package')
        if not (name and choice.get('answer') == 'accepted' and choice.get('child_id') == issue
                and choice.get('agent_id') == agent):
            continue
        scope = binding(company, project, parent, issue, agent, name, choice['id'])
        receipt = read(docs.get(key(choice['id'])), scope)
        if receipt and receipt['status'] == 'ready':
            flag = '--version' if name in ('nmap', 'jq') else '--package-version'
            result[name] = {k: receipt[k] for k in ('command', 'version', 'usage', 'verified_at')}
            result[name]['probe_command'] = receipt['command'] + ' ' + flag
    return result
