"""Serve reviewed offline package operations through one assignment's Unix socket."""
import base64
import json
import os
import resource
import socket
import subprocess
import sys
import tempfile

LIMIT = 256 * 1024
WIRE_LIMIT = LIMIT * 2


def command(package, args):
    if args == ['--package-version']:
        return ['/usr/bin/dpkg-query', '-W', '-f=${Version}\\n', package]
    if package in ('nmap', 'jq') and args == ['--version']:
        return ['/usr/bin/' + package, '--version']
    if package == 'jq' and 1 <= len(args) <= 5 and not args[-1].startswith('-'):
        if all(flag in ('-c', '-e', '-r', '-s') for flag in args[:-1]):
            return ['/usr/bin/jq', *args]
    options = '--package-version'
    if package == 'nmap':
        options += ' or --version'
    if package == 'jq':
        options += ', --version or a filter on standard input'
    raise ValueError('This offline assignment tool accepts ' + options + '.')


def bound_output():
    resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT, LIMIT))


def execute(package, request):
    args = request['args']
    if not isinstance(args, list) or len(args) > 8 or not all(
            isinstance(arg, str) and len(arg) <= 8192 and '\0' not in arg for arg in args):
        raise ValueError('Invalid package arguments.')
    argv = command(package, args)
    raw = base64.b64decode(request.get('input', ''), validate=True)
    if len(raw) > LIMIT:
        raise ValueError('Input exceeds 256 KiB.')
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        done = subprocess.run(argv, input=raw, stdout=out, stderr=err, timeout=6,
                              env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent'},
                              cwd='/', preexec_fn=bound_output)
        out.seek(0)
        err.seek(0)
        return {'code': done.returncode if done.returncode >= 0 else 1,
                'stdout': out.read(LIMIT).decode(errors='replace'),
                'stderr': err.read(LIMIT).decode(errors='replace')}


def serve(package):
    path = '/ipc/tool.sock'
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    os.umask(0o077)
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(path)
        server.listen(5)
        while True:
            conn, _ = server.accept()
            with conn:
                conn.settimeout(8)
                try:
                    with conn.makefile('rb') as stream:
                        data = stream.readline(WIRE_LIMIT + 1)
                    if len(data) > WIRE_LIMIT or not data.endswith(b'\n'):
                        raise ValueError('Invalid request size.')
                    result = execute(package, json.loads(data))
                except (KeyError, TypeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
                    result = {'code': 2, 'stdout': '', 'stderr': str(exc)[:240] + '\n'}
                try:
                    conn.sendall(json.dumps(result).encode())
                except OSError:
                    pass


if __name__ == '__main__':
    serve(sys.argv[1])
