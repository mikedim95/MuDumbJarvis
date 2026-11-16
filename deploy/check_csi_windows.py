#!/usr/bin/env python3
"""Verify real CSI UI records read-only, or run one explicitly authorized demo.

Default: no task submission or inference. --live creates exactly one objective;
--verify-only observes the existing durable receipt without submitting again.
"""
import argparse
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true')
    mode.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    token = None
    for line in (root / 'deploy/.env').read_text().splitlines():
        if line.startswith('JARVIS_HUD_TOKEN='):
            token = line.split('=', 1)[1].strip().strip('"\'')
    if not token:
        parser.error('Configure the existing server-side JARVIS_HUD_TOKEN first')
    flags = ['--' + name.replace('_', '-') for name, enabled in vars(args).items() if enabled]
    command = ['docker', 'run', '--rm', '--name', 'jarvis-csi-browser',
        '--network', 'host', '--user', '1000:1000', '--cpus', '4', '--memory', '2g',
        '--pids-limit', '512', '-e', 'JARVIS_HUD_TOKEN', '-v', str(root) + ':/workspace',
        '--tmpfs', '/tmp:size=256m', 'jarvis-command-center:browser-test',
        'tests/csi_windows_e2e.cjs', *flags]
    result = subprocess.run(command, env={**os.environ, 'JARVIS_HUD_TOKEN': token})
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
