"""Operator-side project lifecycle and authenticated, unprivileged local execution."""
import argparse
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import selectors
import socket
import socketserver
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
import urllib.request
from uuid import UUID

if __package__:
    from . import project_containers as projects, project_offline
else:
    import project_containers as projects
    import project_offline

staffing = projects.staffing
wire = projects.packages.plugin_file('project_cli')
findings = projects.packages.plugin_file('finding_store')
SOCKET = staffing.ROOT / '.runtime/codex-shared/project-cli.sock'
LIMIT = 64 * 1024



def authorize(board, request):
    company, project, agent, issue, run = (str(UUID(request[k])) for k in ('company','project','agent','issue','run'))
    mission = request.get('mission')
    action = request.get('action', 'terminal')
    env = board.env
    if company != env['PAPERCLIP_COMPANY_ID']:
        raise PermissionError('Wrong company.')
    row = board.api('GET', '/issues/' + issue)
    if (row.get('executionRunId') != run or row.get('assigneeAgentId') != agent or row.get('companyId') != company
            or row.get('projectId') != project or row.get('hiddenAt')
            or row.get('status') not in ('todo','in_progress','in_review')):
        raise PermissionError('This worker no longer owns an active execution.')
    if agent == env['PAPERCLIP_CEO_AGENT_ID']:
        if action == 'terminal':
            raise PermissionError('The CEO has no shell.')
    else:
        worker = board.api('GET', '/agents/' + agent)
        profile = staffing.validate_agent(worker, board.api('GET', '/companies/' + company + '/approvals'), env)
        needed = 'terminal' if action == 'terminal' else 'publish_artifact'
        if (worker.get('reportsTo') != env['PAPERCLIP_CEO_AGENT_ID'] or not profile
                or needed not in profile['tools'] or (action == 'terminal' and not profile['sandbox'])):
            raise PermissionError('The worker does not hold this capability.')
    task = row
    if action == 'read_findings':
        return task, None
    seen = set()
    while True:
        if (row['id'] in seen or len(seen) >= 32 or row.get('companyId') != company or row.get('projectId') != project
                or row.get('hiddenAt') or row.get('visibility') not in (None,'open') or row.get('privacyRootIssueId')
                or row.get('privacyParentIssueId') not in (None, row.get('parentId'))):
            raise PermissionError('The assignment has no shared project scope.')
        seen.add(row['id'])
        if row.get('parentId'):
            row = board.api('GET', '/issues/' + str(UUID(row['parentId'])))
        elif row.get('originKind') == 'routine_execution':
            jobs = board.api('GET', '/companies/' + company + '/routines')
            job = next((r for r in jobs if r['id'] == row.get('originId') and r.get('companyId') == company
                        and r.get('projectId') == project), None)
            if not job or projects.packages.work_scope.routine_scope(job).get('mission_id') != mission:
                raise PermissionError('General jobs stay in the existing app.')
            row = board.api('GET', '/issues/' + mission)
        else:
            break
    if row['id'] != mission or not projects.eligible(row, env):
        raise PermissionError('The assignment belongs to another project or the project is closed.')
    return task, row


def verify(env, packet):
    req = packet['request']
    for key in ('company','project','agent','issue','run'):
        if str(UUID(req[key])) != req[key]:
            raise ValueError('Invalid native identifier.')
    key = hmac.new(env['JARVIS_EXECUTION_PROOF_KEY'].encode(),
                   ('jarvis-employee-proof-v3:' + req['agent']).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(wire.signature(key, req), packet['proof']):
        raise PermissionError('Unrecognized project terminal signature.')
    if (type(req['time']) is not int or abs(time.time() - req['time']) > 30
            or not re.fullmatch('[a-f0-9]{32}', req['nonce'])):
        raise ValueError('Expired or invalid project request.')
    if req.get('action') != 'read_findings' or req.get('mission'):
        if str(UUID(req['mission'])) != req['mission']:
            raise ValueError('Invalid mission.')
    if req.get('action') == 'publish_finding' and str(UUID(req['artifact'])) == req['artifact']:
        return req
    if req.get('action') == 'read_findings':
        return req
    if (req.get('action', 'terminal') != 'terminal' or not wire.project_path(req['cwd'])
            or type(req['timeout']) is not int or not 1 <= req['timeout'] <= 120
            or not isinstance(req['command'], str) or not 0 < len(req['command']) <= 32768 or '\0' in req['command']):
        raise ValueError('Invalid or expired project terminal call.')
    if 'stdin' in req and (not isinstance(req['stdin'], str) or len(req['stdin'].encode()) > LIMIT):
        raise ValueError('Project file input exceeds 64 KiB.')
    return req


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise PermissionError('The native attachment location changed.')


def reference(board, req, task, root):
    db = projects.STATUS.parent / 'general_conversations.sqlite3'
    if req['action'] == 'read_findings':
        query = str(task.get('title') or '') + ' ' + str(task.get('description') or '')[:800]
        return {'findings': findings.search(db, req['company'], query, limit=2)}
    rows = board.api('GET','/issues/' + task['id'] + '/attachments')
    artifact = next((a for a in rows if a.get('id') == req['artifact'] and a.get('issueId') == task['id']
        and a.get('companyId') == req['company'] and a.get('createdByAgentId') == req['agent']
        and (a.get('originatingRunId') or a.get('createdByRunId')) == req['run']
        and a.get('createdByRunId') in (None,req['run'])
        and a.get('originalFilename') == 'project-findings.md' and 0 < (a.get('byteSize') or 0) <= 4000), None)
    if not artifact:
        raise PermissionError('No matching native project findings receipt.')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    download = urllib.request.Request('http://127.0.0.1:3100/api/attachments/' + req['artifact'] + '/content',
        headers={'Authorization':'Bearer ' + board.env['PAPERCLIP_API_KEY']})
    with opener.open(download,timeout=6) as response:
        raw = response.read(4001)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != artifact['sha256'] or len(raw) != artifact['byteSize']:
        raise ValueError('Native project finding digest mismatch.')
    authorize(board, req)
    findings.record(db, (req['company'], root['id'], root['identifier'], task['id'], req['agent'], req['run'],
                         req['artifact'], digest, raw.decode('utf-8')))
    SOCKET.with_name('project-findings-available').touch(mode=0o600, exist_ok=True)
    return {'artifact_id':req['artifact'], 'sha256':digest}


def run_command(box, req):
    # Only the command after bash -c belongs to the worker. Docker arguments and environment are operator-owned.
    argv = ['docker', 'exec', '-i', '--user', '1000:1000', '--workdir', req['cwd'], box,
            '/usr/local/bin/python3', '-IS', '-c', project_offline.LAUNCHER, project_offline.filter_base64(),
            str(req['timeout']), req['command']]
    deadline = time.monotonic() + req['timeout'] + 5
    data = bytearray()
    with tempfile.TemporaryFile() as stdin:
        stdin.write(req.get('stdin', '').encode())
        stdin.seek(0)
        proc = subprocess.Popen(argv, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    with proc:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                while time.monotonic() < deadline:
                    if not selector.select(max(0, deadline - time.monotonic())):
                        break
                    chunk = os.read(proc.stdout.fileno(), 16384)
                    if not chunk:
                        break
                    if len(data) < LIMIT:
                        data.extend(chunk[:LIMIT - len(data)])
            code = proc.wait(timeout=max(.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()
            code = 124
    return {'output':data.decode(errors='replace'), 'exit_code':code, 'truncated':len(data) == LIMIT,
            'mission_id':req['mission'], 'workdir':req['cwd']}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(8)
        try:
            line = self.rfile.readline(wire.MAX_WIRE + 1)
            if not line.endswith(b'\n') or len(line) > wire.MAX_WIRE:
                raise ValueError('Invalid project terminal request.')
            req = verify(self.server.env, json.loads(line))
            with self.server.lock:
                now = time.monotonic()
                self.server.nonces = {k:t for k,t in self.server.nonces.items() if t > now}
                if req['nonce'] in self.server.nonces:
                    raise PermissionError('This terminal call was already admitted.')
                self.server.nonces[req['nonce']] = now + 65
            board = staffing.Board(self.server.env)
            task, root = authorize(board, req)
            if req.get('action') in ('publish_finding','read_findings'):
                result = reference(board, req, task, root)
            else:
                with projects.leased_container(req['company'], req['mission']) as box:
                    authorize(board, req)  # A project can be removed during provisioning.
                    result = run_command(box, req)
        except (OSError, KeyError, ValueError, TypeError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as exc:
            result = {'exit_code':125, 'error':'Project terminal: ' + str(exc)[:240]}
        self.wfile.write(json.dumps(result).encode() + b'\n')


def serve():
    env = staffing.settings()
    SOCKET.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with SOCKET.with_suffix('.lock').open('a') as service_lock:
        fcntl.flock(service_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if SOCKET.exists():
            if not stat.S_ISSOCK(SOCKET.lstat().st_mode):
                raise RuntimeError('Another file occupies the project CLI socket.')
            SOCKET.unlink()
        wake_path = projects.STATUS.parent / '.project-lifecycle.sock'
        if wake_path.exists():
            if not stat.S_ISSOCK(wake_path.lstat().st_mode):
                raise RuntimeError('Another file occupies the project lifecycle socket.')
            wake_path.unlink()
        with socketserver.ThreadingUnixStreamServer(str(SOCKET), Handler) as server, socket.socket(
                socket.AF_UNIX, socket.SOCK_DGRAM) as wake:
            SOCKET.chmod(0o600)
            wake.bind(str(wake_path))
            wake_path.chmod(0o600)
            wake.settimeout(8)
            server.env, server.lock, server.nonces = env, threading.Lock(), {}
            server.daemon_threads = True
            def watch():
                while True:
                    try:
                        projects.reconcile(staffing.Board(env))
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                        print('Could not reconcile project containers: ' + str(exc)[:180], flush=True)
                    try:
                        wake.recv(32)
                    except TimeoutError:
                        pass
            threading.Thread(target=watch, daemon=True).start()
            try:
                server.serve_forever()
            finally:
                SOCKET.unlink(missing_ok=True)
                wake_path.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', action='store_true')
    if parser.parse_args().build:
        projects.build_image()
    else:
        serve()
