#!/usr/local/bin/python3 -I
"""Call the approved, offline Debian package tool for this assignment."""
import base64
import json
import os
import socket
import sys

LIMIT = 256 * 1024
binary = os.path.abspath(__file__)
args = sys.argv[1:]
stdin = b''
if os.path.basename(binary) == 'jq' and args not in (['--version'], ['--package-version']) and not sys.stdin.isatty():
    stdin = sys.stdin.buffer.read(LIMIT + 1)
if len(stdin) > LIMIT:
    sys.exit('Input exceeds 256 KiB.')
os.chdir(os.path.dirname(binary))
try:
    with socket.socket(socket.AF_UNIX) as conn:
        conn.settimeout(12)
        conn.connect('.apt-' + os.path.basename(binary) + '.sock')
        data = {'args': args, 'input': base64.b64encode(stdin).decode()}
        conn.sendall(json.dumps(data).encode() + b'\n')
        conn.shutdown(socket.SHUT_WR)
        with conn.makefile('rb') as stream:
            reply = json.loads(stream.read(4 * 1024 * 1024))
    sys.stdout.write(reply['stdout'])
    sys.stderr.write(reply['stderr'])
    sys.exit(reply['code'])
except (ValueError, KeyError, OSError):
    sys.exit('The assignment package environment is unavailable.')
