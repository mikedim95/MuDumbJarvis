#!/usr/bin/env python3
"""Run one minimal-UI CEO objective; existing receipt means observe only.

The first invocation creates one read-only inventory objective through @ceo.
Subsequent invocations reuse its native receipt. --verify-only refuses to create.
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
    command = ['docker', 'run', '--rm', '--name', 'jarvis-minimal-ceo-browser', '--network', 'host',
        '--user', '1000:1000', '--cpus', '4', '--memory', '2g', '--pids-limit', '512',
        '-e', 'JARVIS_HUD_TOKEN', '-v', str(staffing.ROOT) + ':/workspace', '--tmpfs', '/tmp:size=256m',
        'jarvis-command-center:browser-test', 'tests/minimal_ceo_e2e.cjs']
    if args.verify_only:
        command.append('--verify-only')
    raise SystemExit(subprocess.run(command,
        env={**os.environ, 'JARVIS_HUD_TOKEN': env['JARVIS_HUD_TOKEN']}).returncode)


if __name__ == '__main__':
    main()
