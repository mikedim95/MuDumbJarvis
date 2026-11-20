"""Install a CEO-reviewed package in an offline environment bound to one assignment."""
import base64
import contextlib
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import time
from uuid import UUID

if __package__:
    from . import staffing, provision_packages
else:
    import staffing
    import provision_packages

ROOT = staffing.ROOT
DEPLOY = ROOT / 'deploy'
STATE = ROOT / '.runtime/approved-apt'
LABEL = 'io.jarvis.apt.review'
PKG_LABEL = 'io.jarvis.apt.package'


def plugin_file(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'hermes-plugin/jarvis_readonly' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reviews = plugin_file('blocker_review')
receipts = plugin_file('apt_receipts')
development = plugin_file('project_packages')
work_scope = plugin_file('work_scope')


def docker(*args, timeout=30, data=None):
    return subprocess.run(['docker', *args], input=data, text=True, capture_output=True, check=True,
                          timeout=timeout, env={**os.environ, 'DOCKER_BUILDKIT': '1'}).stdout.strip()


def utcnow():
    return datetime.now(timezone.utc)


def open_job(row):
    return row and not row.get('hiddenAt') and row.get('status') not in ('done', 'cancelled')


def accepted(board, root, child, agent, interactions):
    ceo, company = board.env['PAPERCLIP_CEO_AGENT_ID'], board.env['PAPERCLIP_COMPANY_ID']
    if (not open_job(root) or not open_job(child) or root.get('parentId') or root.get('assigneeAgentId') != ceo
            or root.get('companyId') != company or child.get('companyId') != company
            or not root.get('projectId') or child.get('projectId') != root['projectId']
            or child.get('parentId') != root['id'] or child.get('assigneeAgentId') != agent['id']):
        return
    for row in interactions:
        review = reviews.package_decision(row, root['id'], ceo)
        if not (review and review['answer'] == 'accepted' and review['child_id'] == child['id']
                and review['agent_id'] == agent['id'] and row.get('companyId') == company
                and (not row.get('addresseeUserId') or row['addresseeUserId'] == row.get('resolvedByUserId'))):
            continue
        expected = reviews.package_confirmation(child, review['package'])
        if review['question'] == expected['payload']['prompt']:
            yield receipts.binding(company, root['projectId'], root['id'], child['id'],
                                   agent['id'], review['package'], str(UUID(review['id'])))


class Unavailable(ValueError):
    """No exact package in the signed distribution."""


def build(scope):
    name = reviews.package_name(scope['package'])
    tag = 'jarvis-approved-apt:' + str(UUID(scope['review']))
    image = staffing.inspect('image', tag)
    if not image:
        try:
            docker('build', '--progress', 'plain', '--build-arg', 'INDEX_DAY=' + utcnow().date().isoformat(),
                   '--build-arg', 'PACKAGE=' + name, '--label', LABEL + '=' + scope['review'],
                   '--label', PKG_LABEL + '=' + name, '-t', tag, '-',
                   timeout=300, data=(DEPLOY / 'Dockerfile.approved-package').read_text())
        except subprocess.CalledProcessError as error:
            # Match command output, never the echoed Dockerfile instruction.
            if any(line.rstrip().endswith(' JARVIS_NO_EXACT_CANDIDATE') for line in error.stderr.splitlines()):
                raise Unavailable('No exact package in the signed Debian repositories.') from None
            if any(line.rstrip().endswith(' JARVIS_PACKAGE_SPACE') for line in error.stderr.splitlines()):
                raise RuntimeError('Insufficient free disk space for package installation.') from None
            raise RuntimeError('Debian could not resolve, download or configure the package.') from None
        image = staffing.inspect('image', tag)
    labels = ((image or {}).get('Config') or {}).get('Labels') or {}
    if labels.get(LABEL) != scope['review'] or labels.get(PKG_LABEL) != name:
        raise ValueError('Package image does not match this approval.')
    return image['Id']


def workspace_for(agent):
    rid = agent['metadata']['jarvis']['runtime_id']
    sandbox = staffing.inspect('container', 'jarvis-sandbox-' + rid)
    path = ROOT / '.runtime/employees' / str(UUID(agent['id'])) / 'workspace'
    if (not sandbox or not sandbox['State']['Running'] or sandbox['Config']['User'] != '1000:1000'
            or (sandbox['Config'].get('Labels') or {}).get(staffing.MANAGED) != rid
            or not sandbox['HostConfig']['ReadonlyRootfs'] or sandbox['HostConfig'].get('Privileged')
            or not any(m['Destination'] == '/workspace' and m['Type'] == 'bind' and m['Source'] == str(path)
                       for m in sandbox['Mounts'])):
        raise RuntimeError('The assigned employee sandbox is unavailable.')
    return sandbox['Id'], path


def start_tool(scope, image, ipc):
    name = 'jarvis-apt-' + scope['review']
    current = staffing.inspect('container', name)
    sock = ipc / 'tool.sock'
    if not current or not current['State']['Running']:
        sock.unlink(missing_ok=True)
    if current:
        if (current['Config']['Labels'].get(LABEL) != scope['review'] or current['Image'] != image
                or current['HostConfig']['NetworkMode'] != 'none' or not current['HostConfig']['ReadonlyRootfs']
                or current['HostConfig'].get('Privileged') or current['Config']['User'] != '1000:1000'):
            raise RuntimeError('Another container owns the package name.')
        if not current['State']['Running']:
            docker('start', name)
    else:
        docker('run', '-d', '--name', name, '--label', LABEL + '=' + scope['review'],
               '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--pids-limit', '24', '--memory', '96m', '--cpus', '0.5', '--user', '1000:1000',
               '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=8m',
               '--mount', 'type=bind,src=' + str(ipc) + ',dst=/ipc',
               '--mount', 'type=bind,src=' + str(DEPLOY / 'apt_tool.py') + ',dst=/tool.py,readonly',
               '--entrypoint', '/usr/local/bin/python3', image, '-IS', '/tool.py', scope['package'])
    for _ in range(50):
        if sock.exists() and stat.S_ISSOCK(sock.lstat().st_mode):
            return name
        time.sleep(.1)
    raise RuntimeError('The offline package endpoint did not start.')


@contextlib.contextmanager
def bin_directory(workspace, issue):
    # Keep each directory pinned. A worker cannot redirect a host write through a symlink.
    flags = os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW
    fd = os.open(workspace, flags)
    try:
        for component in ('issues', str(UUID(issue)), '.jarvis-bin'):
            try:
                os.mkdir(component, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            nxt = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd
    finally:
        os.close(fd)


def publish_client(scope, workspace, sock):
    code = (DEPLOY / 'apt_client.py').read_bytes()
    name = reviews.package_name(scope['package'])
    with bin_directory(workspace, scope['issue']) as fd:
        tmp = '.apt-' + secrets.token_hex(12)
        try:
            with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                   0o700, dir_fd=fd), 'wb') as out:
                out.write(code)
                out.flush()
                os.fsync(out.fileno())
            try:
                os.link(tmp, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            except FileExistsError:
                existing = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=fd)
                with os.fdopen(existing, 'rb') as saved:
                    if not stat.S_ISREG(os.fstat(existing).st_mode) or saved.read(len(code) + 1) != code:
                        raise RuntimeError('A different file already occupies the assignment package command.')
                os.replace(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
            else:
                os.unlink(tmp, dir_fd=fd)
            os.link(sock, tmp, dst_dir_fd=fd, follow_symlinks=False)
            os.replace(tmp, '.apt-' + name + '.sock', src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            try:
                os.unlink(tmp, dir_fd=fd)
            except FileNotFoundError:
                pass
    return hashlib.sha256(code).hexdigest()


def client_ready(scope, agent):
    _, workspace = workspace_for(agent)
    sock = STATE / scope['review'] / 'tool.sock'
    code = (DEPLOY / 'apt_client.py').read_bytes()
    try:
        with bin_directory(workspace, scope['issue']) as fd:
            endpoint = os.stat('.apt-' + scope['package'] + '.sock', dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISSOCK(endpoint.st_mode) or not os.path.samestat(sock.lstat(), endpoint):
                return False
            handle = os.open(scope['package'], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=fd)
            with os.fdopen(handle, 'rb') as saved:
                info = os.fstat(handle)
                return (stat.S_ISREG(info.st_mode) and bool(info.st_mode & 0o100)
                        and saved.read(len(code) + 1) == code)
    except OSError:
        return False


# Run the trusted client source via stdin, never execute a worker-editable file as the operator.
VERIFY = """
import hashlib,os,stat,sys
name, digest, option, inode = sys.argv[1:]
endpoint = os.stat('.apt-' + name + '.sock', follow_symlinks=False)
if not stat.S_ISSOCK(endpoint.st_mode) or endpoint.st_ino != int(inode):
    raise SystemExit('Package endpoint changed')
fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
with os.fdopen(fd, 'rb') as f:
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        raise SystemExit('Invalid package launcher')
    code = f.read(16385)
if hashlib.sha256(code).hexdigest() != digest:
    raise SystemExit('Installed package launcher changed')
sys.argv = [name, option]
exec(compile(code, name, 'exec'), {'__name__':'__main__', '__file__':name})
"""


def deliver(scope, agent, image):
    sandbox, workspace = workspace_for(agent)
    ipc = STATE / scope['review']
    ipc.mkdir(mode=0o700, exist_ok=True)
    runner = start_tool(scope, image, ipc)
    name = scope['package']
    version = docker('exec', '--user', '1000:1000', runner, '/usr/bin/dpkg-query', '-W', '-f=${Version}', name)
    digest = publish_client(scope, workspace, ipc / 'tool.sock')
    arg = '--version' if name in ('nmap', 'jq') else '--package-version'
    direct = (docker('exec', '--user', '1000:1000', runner, '/usr/bin/' + name, '--version')
              if arg == '--version' else version)
    inode = (ipc / 'tool.sock').lstat().st_ino
    raw = subprocess.run(['docker', 'exec', '--user', '1000:1000', '--workdir',
                          '/workspace/issues/' + scope['issue'] + '/.jarvis-bin', sandbox,
                          '/usr/local/bin/python3', '-IS', '-c', VERIFY, name, digest, arg, str(inode)],
                         capture_output=True, timeout=20, check=True).stdout
    output = raw.decode().strip()
    if not output or len(raw) > 4096 or output != direct:
        raise RuntimeError('The assigned workspace did not verify the package.')
    return {'status':'ready', 'version':version, 'image':image, 'verified_at':utcnow().isoformat(),
            'command':'./.jarvis-bin/' + name, 'usage':receipts.usage(name), 'probe':arg,
            'output_line':output.splitlines()[0], 'stdout_base64':base64.b64encode(raw).decode(),
            'output_sha256':hashlib.sha256(raw).hexdigest()}


def held(board, issue):
    rows = board.api('GET', '/issues/' + issue + '/tree-holds?status=active')
    return bool(rows.get('holds') if isinstance(rows, dict) else rows)


def fetch_scope(board, scope, agent):
    root, child = [board.api('GET', '/issues/' + scope[k]) for k in ('parent', 'issue')]
    rows = board.api('GET', '/issues/' + root['id'] + '/interactions')
    current = board.api('GET', '/agents/' + agent['id'])
    approvals = board.api('GET', '/companies/' + scope['company'] + '/approvals')
    profile = staffing.validate_agent(current, approvals, board.env)
    return (profile and profile['sandbox'] and 'terminal' in profile['tools']
            and (current.get('metadata') or {}).get('jarvis', {}).get('runtime_id') == agent['metadata']['jarvis']['runtime_id']
            and scope in accepted(board, root, child, current, rows)
            and not held(board, root['id']) and not held(board, child['id']))


def save(board, path, doc, scope, result):
    key = receipts.key(scope['review'])
    saved = board.api('PUT', path + '/' + key, {'title':'Debian package · ' + scope['package'], 'format':'markdown',
        'baseRevisionId':(doc or {}).get('latestRevisionId'), 'body':json.dumps({'scope':scope, **result}, sort_keys=True),
        'changeSummary':'Offline package provisioning ' + result['status']})
    if not receipts.read(saved, scope):
        raise RuntimeError('Paperclip did not confirm the package receipt.')


def provision(board, scope, child, agent, running):
    path = '/issues/' + child['id'] + '/documents'
    doc = next((r for r in board.api('GET', path) if r['key'] == receipts.key(scope['review'])), None)
    prior = receipts.read(doc, scope)
    if doc and not prior:
        raise ValueError('Existing package receipt conflicts with the approved request.')
    if not prior and not (child.get('status') == 'blocked' and scope['package'] in reviews.worker_package_requests(
            child, board.api('GET', '/issues/' + child['id'] + '/comments'))):
        return False
    if held(board, scope['parent']) or held(board, scope['issue']):
        return False
    if prior and prior.get('retry_after') and utcnow() < datetime.fromisoformat(prior['retry_after']):
        return True
    try:
        if prior and prior['status'] == 'ready' and scope['review'] in running and client_ready(scope, agent):
            return True
        image = build(scope)
        if not fetch_scope(board, scope, agent):
            return False
        result = deliver(scope, agent, image)
        if not fetch_scope(board, scope, agent):
            return False
    except (Unavailable, OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
        missing = isinstance(exc, Unavailable)
        message = str(exc) if isinstance(exc, (Unavailable, RuntimeError)) else 'Package setup or verification failed.'
        result = {'status':'unavailable' if missing else 'retrying', 'detail':message[:180],
                  'retry_after':(utcnow() + (timedelta(days=1) if missing else timedelta(minutes=3))).isoformat()}
    save(board, path, doc, scope, result)
    return True


def tick(board):
    env = board.env
    company = env['PAPERCLIP_COMPANY_ID']
    base = '/companies/' + company
    approvals = board.api('GET', base + '/approvals')
    employees = {}
    for agent in board.api('GET', base + '/agents'):
        item = staffing.validate_agent(agent, approvals, env)
        if item and item['sandbox'] and 'terminal' in item['tools']:
            employees[agent['id']] = agent
    running = set(docker('ps', '--filter', 'label=' + LABEL, '--format', '{{.Label "' + LABEL + '"}}').splitlines())
    issues = {}
    cursor = ''
    while True:
        page = board.api('GET', base + '/issues?includeRoutineExecutions=true&sortField=id&sortDir=asc&limit=500' + cursor)
        issues.update((i['id'], i) for i in page if i.get('companyId') == company)
        if len(page) < 500:
            break
        nxt = '&afterId=' + str(UUID(page[-1]['id']))
        if nxt == cursor:
            raise RuntimeError('Issue pagination did not advance.')
        cursor = nxt
    keep, by_parent = set(), {}
    for child in issues.values():
        agent = employees.get(child.get('assigneeAgentId'))
        root = issues.get(child.get('parentId'))
        if not agent or not open_job(child) or not open_job(root) or root.get('assigneeAgentId') != env['PAPERCLIP_CEO_AGENT_ID']:
            continue
        if root['id'] not in by_parent:
            by_parent[root['id']] = board.api('GET', '/issues/' + root['id'] + '/interactions')
        for scope in accepted(board, root, child, agent, by_parent[root['id']]):
            try:
                if provision(board, scope, child, agent, running):
                    keep.add(scope['review'])
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                # Another request can still succeed if this native receipt is unavailable.
                print(f"Package review {scope['review']}: {type(exc).__name__}", flush=True)
    # Include helpers created during a build if the scope changed before publication.
    owned = set(docker('ps', '-a', '--filter', 'label=' + LABEL, '--format', '{{.Label "' + LABEL + '"}}').splitlines())
    for review_id in owned - keep:
        name = 'jarvis-apt-' + str(UUID(review_id))
        state = staffing.inspect('container', name)
        if state and state['Config']['Labels'].get(LABEL) == review_id:
            docker('rm', '-f', state['Id'])
    approved = set()
    for root in issues.values():
        if (not open_job(root) or root.get('parentId') or root.get('assigneeAgentId') != env['PAPERCLIP_CEO_AGENT_ID']
                or work_scope.classify(root).get('mission_id') != root['id']):
            continue
        docs = board.api('GET', '/issues/' + root['id'] + '/documents')
        if not any(doc.get('key') == development.KEY for doc in docs):
            continue
        try:
            doc = board.api('GET', '/issues/' + root['id'] + '/documents/' + development.KEY)
            approved.update(development.owner_policy(doc, company, root['id'])['approved'])
        except (KeyError, ValueError):
            print('Invalid development package grant on ' + root['id'], flush=True)
    if approved:
        provision_packages.stage_development_packages(approved)


def main():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / 'provision.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        tick(staffing.Board(staffing.settings()))


if __name__ == '__main__':
    main()
