#!/usr/bin/env python3
"""Run the once-only JARVIS/four-specialist HUD acceptance workflow.

The private receipt preserves root/follow-up intent and request IDs across
restarts. Existing work is observed rather than recreated. --verify-only sends
no objective, follow-up, approval, retry or other mutation request.
"""
import argparse
import os
import subprocess

import staffing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    env = staffing.settings()
    command = ['docker', 'run', '--rm', '--init', '--name', 'jarvis-workforce-browser',
        '--network', 'host', '--user', '1000:1000', '--cpus', '4', '--memory', '2g',
        '--pids-limit', '512', '--shm-size', '512m', '-e', 'JARVIS_HUD_TOKEN',
        '-v', str(staffing.ROOT) + ':/workspace', '--tmpfs', '/tmp:size=256m',
        'jarvis-command-center:browser-test', 'tests/workforce_e2e.cjs']
    if args.verify_only:
        command.append('--verify-only')
    raise SystemExit(subprocess.run(command,
        env={**os.environ, 'JARVIS_HUD_TOKEN': env['JARVIS_HUD_TOKEN']}).returncode)


if __name__ == '__main__':
    main()
