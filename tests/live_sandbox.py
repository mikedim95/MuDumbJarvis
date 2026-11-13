#!/usr/bin/env python3
"""Opt-in real sandbox transport test. No agent/task/inference is created."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if not args.run:
        print(json.dumps({'status': 'not_executed'}))
        return
    suffix = uuid4().hex[:10]
    network, server = 'jarvis-test-net-' + suffix, 'jarvis-test-ssh-' + suffix
    label = 'io.jarvis.test=' + suffix
    image = 'jarvis-command-center:employee-sandbox-v1'

    def run(argv, check=True):
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        if check and result.returncode:
            raise RuntimeError(argv[0] + ' failed: ' + result.stderr[:500])
        return result

    with tempfile.TemporaryDirectory(prefix='jarvis-sandbox-check-') as directory:
        root = Path(directory)
        root.chmod(0o755)
        keys, workspace = root / 'keys', root / 'workspace'
        keys.mkdir(); workspace.mkdir()
        run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(root / 'client')])
        run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(keys / 'host_key')])
        (keys / 'authorized_keys').write_text((root / 'client.pub').read_text())
        try:
            run(['docker', 'network', 'create', '--internal', '--opt',
                'com.docker.network.bridge.gateway_mode_ipv4=isolated', '--label', label, network])
            run(['docker', 'run', '-d', '--name', server, '--network', network, '--dns', '127.0.0.1',
                '--label', label, '--user', '1000:1000', '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges:true', '--pids-limit', '128', '--cpus', '2', '--memory', '2g',
                '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m', '--tmpfs', '/home/employee:rw,uid=1000,gid=1000,size=32m',
                '-v', str(keys) + ':/run/jarvis-ssh:ro', '-v', str(workspace) + ':/workspace', image])
            code = ('import os,json,pathlib; p=pathlib.Path("/workspace/check.txt"); p.write_text("real isolated execution"); '
                    'routes=pathlib.Path("/proc/net/route").read_text().splitlines()[1:]; '
                    'no_default=not any(x.split()[1]=="00000000" for x in routes); '
                    'print(json.dumps({"uid":os.getuid(),"workspace_write":p.read_text()=="real isolated execution",'
                    '"host_files_absent":not pathlib.Path("/home/kali").exists(),'
                    '"docker_socket_absent":not pathlib.Path("/var/run/docker.sock").exists(),'
                    '"credentials_absent":not any(k in os.environ for k in ["API_SERVER_KEY","PAPERCLIP_API_KEY","HERMES_PAPERCLIP_AGENT_KEY","JARVIS_EXECUTION_PROOF_KEY"]),'
                    '"no_default_route":no_default}))')
            import shlex
            command = 'python3 -c ' + shlex.quote(code)
            client = ['docker', 'run', '--rm', '--network', network, '--user', '1000:1000', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges:true', '-v', str(root / 'client') + ':/tmp/client:ro',
                '--entrypoint', 'ssh', image, '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'ConnectTimeout=2', '-p', '2222', '-i', '/tmp/client', 'employee@' + server, command]
            result = None
            for _ in range(10):
                result = run(client, check=False)
                if result.returncode == 0:
                    break
                time.sleep(1)
            if result.returncode:
                raise RuntimeError('Sandbox SSH failed: ' + result.stderr[:500])
            proof = json.loads(result.stdout)
            assert proof['uid'] == 1000 and all(value is True for key, value in proof.items() if key != 'uid')
            assert (workspace / 'check.txt').read_text() == 'real isolated execution'
            state = json.loads(run(['docker', 'network', 'inspect', network]).stdout)[0]
            assert state['Internal'] and state['Options']['com.docker.network.bridge.gateway_mode_ipv4'] == 'isolated'
            evidence = {'status': 'passed', 'real_ssh_execution': True, 'sandbox': proof,
                'isolated_gateway_mode': True, 'agent_or_task_created': False, 'inference_requested': False,
                'cleanup': 'Only test resources bearing this unique ownership label'}
            target = Path(__file__).resolve().parents[1] / 'docs/evidence/phase11-sandbox-transport.json'
            target.write_text(json.dumps(evidence, indent=2))
            print(json.dumps(evidence))
        finally:
            state = run(['docker', 'inspect', server], check=False)
            if state.returncode == 0:
                obj = json.loads(state.stdout)[0]
                if (obj['Config'].get('Labels') or {}).get('io.jarvis.test') == suffix:
                    run(['docker', 'rm', '-f', server], check=False)
            state = run(['docker', 'network', 'inspect', network], check=False)
            if state.returncode == 0 and (json.loads(state.stdout)[0].get('Labels') or {}).get('io.jarvis.test') == suffix:
                run(['docker', 'network', 'rm', network], check=False)


if __name__ == '__main__':
    main()
