"""A communication acknowledgment is evidence of contact, never capability work."""
import re


_NEGATED_ITEMS = r'(?:diagnostics?|inventory|research|analysis|code|tests?|other actions)'
_NO_WORK = re.compile(r'\bno\s+' + _NEGATED_ITEMS +
    r'(?:\s*(?:,\s*(?:(?:or|and)\s+)?|(?:or|and)\s+)' + _NEGATED_ITEMS + r')*\s+(?:needed|required|requested)\b', re.I)
_WORK = re.compile(r'\b(?:build|create|write|implement|deploy|configure|modify|delete|remove|install|execute|run|'
    r'shell|terminal|commands?|code|tests?|unittest|pytest|research|analysis|analy[sz]e|frameworks?|'
    r'inventory|diagnostics?|scan|audit|benchmark|fetch|download|upload)\b', re.I)


def communication_only(text, *, explicit=False):
    """Conservative native-scope recognition; mixed work requests stay work.

    The exception needs BOTH an acknowledgment-only child and a communication
    goal. A model reply or a tool argument cannot declare an execution exempt.
    """
    if not isinstance(text, str) or not 1 <= len(text) <= 4000:
        return False
    if not re.search(r'\b(?:ping|pong|acknowledg(?:e|ment|ement))\b', text, re.I):
        return False
    if explicit and not re.search(r'\bcommunication check only\b', text, re.I):
        return False
    if not explicit and not re.search(r'\b(?:agents?|workers?|team|staff|acknowledgment|acknowledgement|pong)\b', text, re.I):
        return False
    if re.search(r'https?://|\b(?:\d{1,3}\.){3}\d{1,3}\b|[`$<>]|\b(?:ssh|curl|wget|subprocess)\b', text, re.I):
        return False
    scope = _NO_WORK.sub('', text)
    scope = re.sub(r'\bJARVIS\s+(?:Research|Software|Security|Systems)\b', 'employee', scope, flags=re.I)
    return not _WORK.search(scope)


def assignment(issue, parent):
    return (bool(issue.get('parentId')) and issue.get('parentId') == parent.get('id') and
        not parent.get('parentId') and issue.get('companyId') == parent.get('companyId') and
        issue.get('projectId') == parent.get('projectId') and
        communication_only(issue.get('description'), explicit=True) and
        communication_only(parent.get('description')))


def identity_error(identity, expected, reply):
    if not isinstance(identity, dict):
        return 'A real agent_identity result is required for the acknowledgment.'
    keys = {'agent_id': 'agent', 'company_id': 'company', 'issue_id': 'issue',
        'paperclip_run_id': 'run', 'profile': 'profile'}
    if any(not expected.get(value) or identity.get(key) != expected[value] for key, value in keys.items()):
        return 'Acknowledgment identity does not match this employee, task and execution.'
    if not identity.get('name') or not identity.get('role'):
        return 'Acknowledgment requires the registered employee name and role.'
    if any(expected.get(key) and identity.get(key) != expected[key] for key in ('name', 'role')):
        return 'Acknowledgment differs from the current registered employee.'
    if not isinstance(reply, str) or not re.search(r'\bPONG\b', reply, re.I) or identity['name'] not in reply:
        return 'Reply with PONG and your actual registered name after calling agent_identity.'
    return None


def observed_identity(events):
    return next((event.get('result') for event in reversed(events)
        if event.get('tool') == 'agent_identity' and event.get('success') is True), None)
