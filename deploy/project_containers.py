"""Lifecycle of private Kali development containers for native JARVIS missions."""
import json
import fcntl
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from uuid import UUID

if __package__:
    from . import approved_packages as packages, staffing
else:
    import approved_packages as packages
    import staffing

IMAGE = 'jarvis-command-center:project-cli-v2'
LEGACY_IMAGE = 'jarvis-command-center:project-cli-v1'
LABS = staffing.ROOT / '.runtime/project-labs'
LABEL = 'io.jarvis.project.mission'
COMPANY = 'io.jarvis.project.company'
ISOLATED = 'com.docker.network.bridge.gateway_mode_ipv4'
ICC = 'com.docker.network.bridge.enable_icc'
NETWORK = 'jarvis-projects-local'
LOCK = threading.Lock()
VERIFIED = {}
DEPLOY = Path(__file__).resolve().parent
STATUS = staffing.ROOT / 'server/logs/project-containers.json'


def build_image():
    # Send only public build inputs to Docker. Runtime credentials are outside the context.
    with tempfile.TemporaryDirectory() as stage:
        root = Path(stage)
        shutil.copyfile(DEPLOY / 'Dockerfile.project-cli', root / 'Dockerfile')
        shutil.copyfile(DEPLOY / 'project_install.py', root / 'project-install')
        (root / 'project-install').chmod(0o755)
        tools = root / 'tools'
        tools.mkdir()
        for name, spec in packages.development.CATALOG.items():
            exe = tools / spec['command']
            exe.write_bytes(packages.provision_packages.package_bytes(name))
            exe.chmod(0o755)
        subprocess.run(['docker', 'build', '--build-arg', 'REFRESH=' + str(time.time_ns()),
                        '-t', IMAGE, str(root)], check=True, timeout=900)


def eligible(row, env, *, keep_completed=False):
    return (row.get('companyId') == env['PAPERCLIP_COMPANY_ID'] and row.get('projectId')
            and row.get('assigneeAgentId') == env['PAPERCLIP_CEO_AGENT_ID'] and not row.get('parentId')
            and (row.get('status') in ('todo','in_progress','in_review','blocked')
                 or (keep_completed and row.get('status') == 'done'))
            and not row.get('hiddenAt')
            and row.get('visibility') in (None,'open') and not row.get('privacyRootIssueId')
            and not row.get('privacyParentIssueId') and row.get('originKind') != 'routine_execution'
            and packages.work_scope.classify(row).get('mission_id') == row['id'])


def names(mission):
    name = 'jarvis-project-' + str(UUID(mission))
    return name, NETWORK, name + '-data'


def lab_directory(company, mission):
    return LABS / str(UUID(company)) / str(UUID(mission))


@contextmanager
def lab_lock(company, mission, *, exclusive=False):
    directory = lab_directory(company, mission)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (directory / 'lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield


def selection(company, mission):
    try:
        return json.loads((lab_directory(company, mission) / 'current.json').read_text())
    except FileNotFoundError:
        return None


def save_selection(company, mission, current, previous=None):
    directory = lab_directory(company, mission)
    with tempfile.NamedTemporaryFile('w', dir=directory, delete=False) as stream:
        json.dump({'current':current, 'previous':previous}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(stream.name, directory / 'current.json')


def active_name(company, mission):
    record = selection(company, mission)
    return record['current']['name'] if record else names(mission)[0]


def ensure_network(company):
    """Reserve one common bridge; individual service connections are configured separately."""
    net = staffing.inspect('network', NETWORK)
    if not net:
        packages.docker('network', 'create', '--driver', 'bridge', '--internal',
                        '--opt', ISOLATED + '=isolated', '--opt', ICC + '=false',
                        '--label', COMPANY + '=' + str(UUID(company)), NETWORK)
        net = staffing.inspect('network', NETWORK)
    if (not net or (net.get('Labels') or {}).get(COMPANY) != company or not net['Internal']
            or net['Driver'] != 'bridge' or net.get('EnableIPv6')
            or net['Options'].get(ISOLATED) != 'isolated' or net['Options'].get(ICC) != 'false'):
        raise ValueError('The JARVIS shared local bridge has conflicting configuration or ownership.')
    return net


def container(company, mission):
    with leased_container(company, mission) as ident:
        return ident


@contextmanager
def leased_container(company, mission):
    with lab_lock(company, mission):
        record = selection(company, mission)
        if record:
            ident = provision(company, mission, record['current'])
        else:
            name = names(mission)[0]
            existing = staffing.inspect('container', name)
            legacy = bool(existing and existing['HostConfig']['ReadonlyRootfs'])
            image = staffing.inspect('image', LEGACY_IMAGE if legacy else IMAGE)
            if not image:
                raise RuntimeError('Build the project CLI image before starting the lab.')
            target = {'name':name, 'image':image['Id'], 'readonly':legacy}
            previous = None
            if legacy and not existing['State']['Running']:
                # On reactivation preserve a retired generation without starting its old system.
                provision(company, mission, target, start=False)
                previous = target
                target = writable_release(mission)
            ident = provision(company, mission, target)
            save_selection(company, mission, target, previous)
        yield ident


def writable_release(mission):
    image = staffing.inspect('image', IMAGE)
    if not image:
        raise RuntimeError('Build the writable project image before switching labs.')
    name = names(mission)[0] + '-lab-' + image['Id'].split(':')[1][:12]
    return {'name':name, 'image':image['Id'], 'readonly':False}


def provision(company, mission, target, *, start=True):
    base, network, volume = names(mission)
    name = target['name']
    if name not in (base, base + '-lab-' + target['image'].removeprefix('sha256:')[:12]):
        raise ValueError('Container name does not belong to this project release.')
    labels = {LABEL: str(UUID(mission)), COMPANY: str(UUID(company))}
    label_options = [x for k, v in labels.items() for x in ('--label', k + '=' + v)]
    def owned(obj, actual):
        if not obj or any((actual or {}).get(k) != v for k, v in labels.items()):
            raise ValueError('A Docker resource with this name belongs to another owner.')
    with LOCK:
        image = staffing.inspect('image', target['image'])
        if not image:
            raise RuntimeError('The project CLI image needs to be built.')
        if not target['readonly'] and (image['Config'].get('Labels') or {}).get('io.jarvis.project.template') != 'writable-v2':
            raise ValueError('Unrecognized writable project template.')
        ensure_network(company)
        vol = staffing.inspect('volume', volume)
        if not vol:
            packages.docker('volume', 'create', *label_options, volume)
            vol = staffing.inspect('volume', volume)
        owned(vol, vol['Labels'])
        if vol['Driver'] != 'local' or vol.get('Options'):
            raise ValueError('The project volume must use private local storage.')
        box = staffing.inspect('container', name)
        if not box:
            packages.docker('create', '--name', name, *label_options, '--network', network, '--dns', '127.0.0.1',
                *(['--read-only'] if target['readonly'] else []), '--user', '1000:1000', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--pids-limit', '96', '--cpus', '1', '--memory', '384m', '--ulimit', 'fsize=67108864:67108864',
                '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777',
                '--mount', 'type=volume,src=' + volume + ',dst=/project', image['Id'])
            box = staffing.inspect('container', name)
        owned(box, box['Config']['Labels'])
        cfg = box['HostConfig']
        mounts = [m for m in box['Mounts'] if m['Type'] != 'tmpfs']
        if (box['Image'] != image['Id'] or cfg.get('Privileged') or cfg['ReadonlyRootfs'] != target['readonly']
                or cfg.get('CapAdd') or 'ALL' not in (cfg.get('CapDrop') or [])
                or not any(s.split(':')[0] == 'no-new-privileges' for s in cfg.get('SecurityOpt') or [])
                or cfg.get('NetworkMode') != network or cfg.get('PortBindings')
                or set(box['NetworkSettings']['Networks']) != {network}
                or box['Config']['User'] != '1000:1000' or len(mounts) != 1
                or (mounts[0]['Type'], mounts[0].get('Name'), mounts[0]['Destination'], mounts[0]['RW'])
                    != ('volume', volume, '/project', True)):
            raise ValueError('Project container configuration differs from its approved configuration.')
        if start and not box['State']['Running']:
            packages.docker('start', box['Id'])
        return box['Id']


def projects(board, running_names=()):
    company = board.env['PAPERCLIP_COMPANY_ID']
    path = '/companies/' + company + '/issues?includeRoutineExecutions=true&sortField=id&sortDir=asc&limit=500'
    active = set()
    after = ''
    while True:
        rows = board.api('GET', path + after)
        for row in rows:
            keep = (row.get('status') == 'done' and eligible(row, board.env, keep_completed=True)
                    and active_name(company, row['id']) in running_names)
            if eligible(row, board.env, keep_completed=keep):
                active.add(str(UUID(row['id'])))
        if len(rows) < 500:
            return active
        cursor = '&afterId=' + str(UUID(rows[-1]['id']))
        if cursor == after:
            raise RuntimeError('Project list pagination did not advance.')
        after = cursor


def reconcile(board):
    company = board.env['PAPERCLIP_COMPANY_ID']
    with LOCK:
        network = ensure_network(company)
    rows = packages.docker('ps', '--no-trunc', '--filter', 'label=' + COMPANY + '=' + company,
                           '--filter', 'label=' + LABEL, '--format', '{{json .}}')
    running = {row['Names']:row['ID'] for row in (json.loads(line) for line in rows.splitlines())}
    active = projects(board, running)
    active_names = {active_name(company, m) for m in active}
    states = {}
    for mission in sorted(active):
        try:
            ident = running.get(active_name(company, mission))
            if ident and VERIFIED.get((company, mission)) == ident and ident in (network.get('Containers') or {}):
                states[mission] = 'running'
                continue
            # A deletion can race list pagination; don't recreate an archived mission.
            if eligible(board.api('GET', '/issues/' + mission), board.env, keep_completed=bool(ident)):
                VERIFIED[company, mission] = container(company, mission)
                states[mission] = 'running'
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            states[mission] = 'unavailable'
            print('Project CLI provisioning failed for ' + mission + ': ' + str(exc)[:180], flush=True)
    for name, ident in running.items():
        if name in active_names:
            continue
        box = staffing.inspect('container', ident)
        if not box:
            continue
        labels = box['Config']['Labels']
        mission = labels[LABEL]
        if labels.get(COMPANY) != company:
            continue
        with lab_lock(company, mission):
            selected_name = active_name(company, mission)
            if name != selected_name:
                # Only the selected generation accepts commands. Retain stopped generations for rollback.
                if name == names(mission)[0] or name.startswith(names(mission)[0] + '-lab-'):
                    packages.docker('stop', '--time', '2', ident)
                continue
            if mission in active:
                continue
            # Recheck archive/cancellation and completion against the current native issue.
            try:
                if eligible(board.api('GET', '/issues/' + str(UUID(mission))), board.env, keep_completed=True):
                    continue
            except RuntimeError as exc:
                if str(exc) != 'Paperclip GET failed: HTTP 404':
                    raise
            with LOCK:
                packages.docker('stop', '--time', '2', box['Id'])
                VERIFIED.pop((company,mission), None)
    # Endpoint IDs bind the bridge address to the verified container (even when names are reused).
    if any(state == 'running' and VERIFIED[company, mission] not in (network.get('Containers') or {})
           for mission, state in states.items()):
        network = ensure_network(company)
    endpoints = network.get('Containers') or {}
    addresses = {}
    for mission, state in states.items():
        endpoint = endpoints.get(VERIFIED.get((company, mission))) or {}
        if state == 'running' and endpoint.get('Name') == active_name(company, mission) and endpoint.get('IPv4Address'):
            addresses[mission] = endpoint['IPv4Address'].partition('/')[0]
    # HUD reads this small snapshot through its existing logs mount; Docker stays operator-only.
    with tempfile.NamedTemporaryFile('w', dir=STATUS.parent, delete=False) as stream:
        json.dump({'company':company, 'at':time.time(), 'network':NETWORK, 'projects':states,
                   'bridge_ipv4':addresses}, stream)
    os.replace(stream.name, STATUS)
