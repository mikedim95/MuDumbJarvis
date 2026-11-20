"""Project package grants belong to the owner. Installed commands run in the worker's existing sandbox."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from uuid import UUID

KEY = 'jarvis-development-packages'
CATALOG = json.loads(Path(__file__).with_name('development_packages.json').read_text())
CACHE = Path('/opt/jarvis-codex/project-packages')
MAX_BYTES = 12 * 1024 * 1024
DIRECTORY = os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW


def owner_policy(doc, company, mission):
    if doc is None:
        return {'approved': [], 'outdated': [], 'revision': None}
    if (doc.get('companyId') != company or doc.get('issueId') != mission or doc.get('key') != KEY
            or not doc.get('updatedByUserId') or doc.get('updatedByAgentId') or not doc.get('latestRevisionId')):
        raise ValueError('A native owner revision is required for project package approvals')
    body = json.loads(doc['body'])
    if not isinstance(body, dict) or body.get('version') != 1 or not isinstance(body.get('packages'), dict):
        raise ValueError('Invalid project package policy')
    pins = body['packages']
    if len(pins) > 64 or any(not isinstance(v, str) or not re.fullmatch('[a-f0-9]{64}', v) for v in pins.values()):
        raise ValueError('Invalid project package digest')
    approved = sorted(n for n, pin in pins.items() if n in CATALOG and CATALOG[n]['sha256'] == pin)
    return {'approved': approved, 'outdated': sorted(set(pins) - set(approved)), 'revision': doc['latestRevisionId']}


def for_assignment(turn, issue, api, *, refresh=False):
    from . import team_workspace
    expected = (turn.get('work_scope') or {}).get('mission_id')
    if (not expected or turn.get('task_kind') == 'acknowledgement' or issue.get('id') != turn.get('issue')
            or issue.get('assigneeAgentId') != turn.get('agent') or issue.get('status') in ('done','cancelled')):
        return None
    index = {i['id']: i for i in turn.get('_scope_issues', [])}
    jobs = {j['id']: j for j in turn.get('_scope_routines', [])}
    index[issue['id']] = issue
    if refresh:
        # A still-running task can be moved after preflight. Re-read its real ancestry before installing.
        row, seen = issue, {issue['id']}
        while row.get('parentId'):
            key = row['parentId']
            if key in seen or len(seen) >= 32:
                return None
            seen.add(key)
            row = api('GET', '/issues/' + str(UUID(key)))
            index[key] = row
        if row.get('originKind') == 'routine_execution':
            jobs = {j['id']: j for j in api('GET','/companies/' + turn['company'] + '/routines')}
            index[expected] = api('GET', '/issues/' + str(UUID(expected)))
    root = team_workspace.membership(issue, index, jobs, turn['company'], turn['project'], turn.get('reports_to'))
    if root != expected or index[root].get('status') in ('done', 'cancelled'):
        return None
    try:
        doc = api('GET','/issues/' + root + '/documents/' + KEY)
    except Exception as exc:
        if getattr(exc,'code',None) == 404:
            return None
        raise
    return {**owner_policy(doc,turn['company'],root), 'mission_id':root}


def verified_bytes(parent_fd, name, digest):
    fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent_fd)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES:
            raise ValueError('Invalid development tool file')
        raw = stream.read(MAX_BYTES + 1)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Development tool contents differ from the approved digest')
    return raw


def install(turn, name, policy):
    from hermes_constants import get_hermes_home
    spec = CATALOG[name]
    if name not in policy['approved']:
        raise PermissionError('Package needs an owner approval')
    digest, command = spec['sha256'], spec['command']
    cache = os.open(CACHE, DIRECTORY)
    try:
        raw = verified_bytes(cache, digest, digest)
    finally:
        os.close(cache)
    fd = os.open(get_hermes_home(), DIRECTORY)
    try:
        for part in ('workspace','issues',str(UUID(turn['issue'])),'.jarvis-bin'):
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
        tmp = '.project-' + secrets.token_hex(12)
        temp = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700, dir_fd=fd)
        try:
            with os.fdopen(temp, 'wb') as out:
                out.write(raw)
                out.flush()
                os.fsync(out.fileno())
            try:
                os.link(tmp, command, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            except FileExistsError:
                pass
            verified_bytes(fd, command, digest)
            if not os.stat(command, dir_fd=fd, follow_symlinks=False).st_mode & stat.S_IXUSR:
                raise PermissionError('The existing tool file is not executable')
        finally:
            os.unlink(tmp, dir_fd=fd)
    finally:
        os.close(fd)
    return {'status':'installed', 'package':name, 'version':spec['version'], 'command':'./.jarvis-bin/' + command,
            'sha256':digest, 'mission_id':policy['mission_id'], 'policy_revision':policy['revision']}
