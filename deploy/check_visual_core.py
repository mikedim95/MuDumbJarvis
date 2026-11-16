#!/usr/bin/env python3
"""Run read-only visual browser checks; never starts an agent or model job."""
import argparse
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--fallback', action='store_true')
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    token = None
    for line in (root / 'deploy/.env').read_text().splitlines():
        if line.startswith('JARVIS_HUD_TOKEN='):
            token = line.split('=', 1)[1].strip().strip('\"\'')
    if not token:
        parser.error('Configure the existing server-side JARVIS_HUD_TOKEN first')
    flags = ['--' + name for name, enabled in vars(args).items() if enabled]
    command = ['docker', 'run', '--rm', '--network', 'host', '--user', '1000:1000',
        '--cpus', '4', '--memory', '2g', '--pids-limit', '512', '-e', 'JARVIS_HUD_TOKEN',
        '-v', str(root) + ':/workspace', '--tmpfs', '/tmp:size=256m',
        'jarvis-command-center:browser-test', 'tests/visual_core_e2e.cjs', *flags]
    result = subprocess.run(command, env={**os.environ, 'JARVIS_HUD_TOKEN': token})
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
