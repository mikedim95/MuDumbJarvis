"""Provision exact board-approved tools in employee sandboxes as their ordinary user."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import zipfile
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('jarvis_package_installs', ROOT / 'hermes-plugin/jarvis_readonly/package_installs.py')
packages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packages)


def build_payload(name, path):
    spec = packages.DEVELOPMENT[name]
    data = path / 'data'
    for source, digest in spec['archives']:
        with urllib.request.urlopen('https://deb.debian.org/debian/pool/main/' + source, timeout=15) as res:
            archive = res.read(10 * 1024 * 1024 + 1)
        if hashlib.sha256(archive).hexdigest() != digest:
            raise ValueError('Debian archive digest mismatch')
        (path / 'package.deb').write_bytes(archive)
        subprocess.run(['dpkg-deb', '-x', str(path / 'package.deb'), str(data)], check=True,
                       timeout=15, capture_output=True)
    if name != 'python3-pytest':
        return (data / 'usr/bin' / spec['command']).read_bytes()
    # The sandbox already has Python 3.12. Ship the Debian pure-Python packages
    # as one reproducible executable, including their metadata for plugin discovery.
    modules = data / 'usr/lib/python3/dist-packages'
    buf = io.BytesIO()
    buf.write(b'#!/usr/local/bin/python3\n')
    with zipfile.ZipFile(buf, 'a') as output:
        output.writestr(zipfile.ZipInfo('__main__.py'),
            'import os, sys\nimport pytest\nsys.path.insert(0, os.getcwd())\nsys.exit(pytest.console_main())\n')
        for file in sorted(modules.rglob('*')):
            if file.is_file() and not file.is_symlink() and file.suffix != '.pyc':
                output.writestr(zipfile.ZipInfo(file.relative_to(modules).as_posix()), file.read_bytes())
    return buf.getvalue()


def package_bytes(name):
    digest = packages.DEVELOPMENT[name]['sha256']
    cache = ROOT / '.runtime/package-cache'
    cache.mkdir(mode=0o700, exist_ok=True)
    cached = cache / digest
    if cached.is_file():
        raw = cached.read_bytes()
        if hashlib.sha256(raw).hexdigest() == digest:
            return raw
    with tempfile.TemporaryDirectory(dir=cache) as tmp:
        path = Path(tmp)
        raw = build_payload(name, path)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Executable digest mismatch')
        (path / 'verified').write_bytes(raw)
        os.replace(path / 'verified', cached)
    return raw


def stage_development_packages(names):
    """Cache approved payloads on the controller mount, outside every employee shell."""
    directory = ROOT / '.runtime/codex-shared/project-packages'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(directory, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
    try:
        for name in sorted(names):
            digest = packages.DEVELOPMENT[name]['sha256']
            try:
                source = os.open(digest, os.O_NOFOLLOW | os.O_RDONLY | os.O_NONBLOCK, dir_fd=fd)
            except FileNotFoundError:
                pass
            else:
                with os.fdopen(source, 'rb') as local:
                    if hashlib.sha256(local.read(12*1024*1024 + 1)).hexdigest() == digest:
                        continue
            raw = package_bytes(name)
            temp = '.prepare-' + os.urandom(12).hex()
            tmp = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                with os.fdopen(tmp, 'wb') as store:
                    store.write(raw)
                    store.flush()
                    os.fsync(store.fileno())
                os.replace(temp, digest, src_dir_fd=fd, dst_dir_fd=fd)
            finally:
                try:
                    os.unlink(temp, dir_fd=fd)
                except FileNotFoundError:
                    pass
    finally:
        os.close(fd)


# Runs inside the sandbox as uid 1000. The host never opens an employee-controlled path.
INSTALL = """
import hashlib, os, secrets, sys
issue, name, expected = sys.argv[1:]
if os.getuid() != 1000:
    raise SystemExit('Unexpected sandbox identity')
raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
if hashlib.sha256(raw).hexdigest() != expected:
    raise SystemExit('Package checksum mismatch')
flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
parent = os.open('/workspace', flags)
for part in ('issues', issue, '.jarvis-bin'):
    try:
        os.mkdir(part, 0o700, dir_fd=parent)
    except FileExistsError:
        pass
    child = os.open(part, flags, dir_fd=parent)
    os.close(parent)
    parent = child
temp = '.install-' + secrets.token_hex(16)
fd = os.open(temp, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700, dir_fd=parent)
try:
    with os.fdopen(fd, 'w+b') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
        f.seek(0)
        if hashlib.file_digest(f, 'sha256').hexdigest() != expected:
            raise SystemExit('Installed bytes differ')
        os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
finally:
    try:
        os.unlink(temp, dir_fd=parent)
    except FileNotFoundError:
        pass
    os.close(parent)
print(expected)
"""


def install(state, issue_id, name):
    raw = package_bytes(name)
    digest = packages.CATALOG[name][3]
    call = subprocess.run(['docker', 'exec', '-i', '--user', '1000:1000', '--workdir', '/',
                           state['Id'], '/usr/local/bin/python3', '-IS', '-c', INSTALL, str(UUID(issue_id)), name, digest],
                          input=raw, capture_output=True, timeout=30, check=True)
    if call.stdout.decode().strip() != digest:
        raise ValueError('Sandbox did not confirm the installation')


def reconcile(board, agent, item, approvals, inspect):
    if not item['sandbox'] or 'terminal' not in item['tools']:
        return
    for approval in approvals:
        data = approval.get('payload') or {}
        if (data.get('kind') != packages.KIND or approval.get('status') != 'approved'
                or not approval.get('decidedByUserId') or approval.get('requestedByAgentId') != agent['id']
                or approval.get('companyId') != agent['companyId'] or not isinstance(data.get('package'), str)
                or data['package'] not in packages.CATALOG):
            continue
        try:
            apply_approval(board, agent, approval, inspect)
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            # One stale approval or a board outage must not interrupt employee provisioning.
            print(f"Package approval {approval.get('id')}: {type(exc).__name__}", flush=True)


def apply_approval(board, agent, approval, inspect):
    data = approval['payload']
    # Scope comes from native linkage and the current assignee, never from a proposed path.
    approval_id = str(UUID(approval['id']))
    linked = board.api('GET', '/approvals/' + approval_id + '/issues')
    if len(linked) != 1 or linked[0].get('id') != data.get('issue_id'):
        return
    issue = board.api('GET', '/issues/' + str(UUID(linked[0]['id'])))
    if (issue.get('companyId') != agent['companyId'] or issue.get('assigneeAgentId') != agent['id']
            or issue.get('hiddenAt') or issue.get('status') in ('done', 'cancelled') or not issue.get('projectId')):
        return
    expected = packages.payload(data['package'], agent['companyId'], issue['projectId'], issue['id'], agent['id'])
    if not packages.matches(approval, expected):
        return
    path = '/issues/' + issue['id'] + '/documents'
    key = packages.receipt_key(approval_id)
    prior = next((d for d in board.api('GET', path) if d.get('key') == key), None)
    if (packages.receipt(prior, approval) or {}).get('status') == 'installed':
        return
    rid = agent['metadata']['jarvis']['runtime_id']
    state = inspect('container', 'jarvis-sandbox-' + rid)
    status = 'retrying'
    try:
        if (state and state['State']['Running'] and state['Config']['Labels'].get('io.jarvis.employee') == rid
                and state['HostConfig'].get('ReadonlyRootfs') and not state['HostConfig'].get('Privileged')
                and state['Config']['User'] == '1000:1000'):
            install(state, issue['id'], data['package'])
            status = 'installed'
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Package provisioning {approval_id}: {type(exc).__name__}", flush=True)
    body = {'approval_id': approval_id, 'request': expected, 'status': status}
    if (packages.receipt(prior, approval) or {}).get('status') == status:
        return
    saved = board.api('PUT', path + '/' + key, {'title': 'Package installation: ' + data['package'],
        'format': 'markdown', 'body': json.dumps(body), 'baseRevisionId': (prior or {}).get('latestRevisionId'),
        'changeSummary': 'Runtime package installation ' + status})
    if (packages.receipt(saved, approval) or {}).get('status') != status:
        raise ValueError('Native installation receipt was not confirmed')
