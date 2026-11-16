#!/usr/bin/env python3
"""Run two real local direct-chat turns; never create a Paperclip objective."""
import os
import subprocess
import staffing


def main():
    env = staffing.settings()
    command = ['docker', 'run', '--rm', '--name', 'jarvis-direct-chat-browser', '--network', 'host',
        '--user', '1000:1000', '--cpus', '4', '--memory', '2g', '--pids-limit', '512',
        '-e', 'JARVIS_HUD_TOKEN', '-v', str(staffing.ROOT) + ':/workspace', '--tmpfs', '/tmp:size=256m',
        'jarvis-command-center:browser-test', 'tests/direct_chat_fix_e2e.cjs']
    raise SystemExit(subprocess.run(command, env={**os.environ, 'JARVIS_HUD_TOKEN': env['JARVIS_HUD_TOKEN']}).returncode)


if __name__ == '__main__':
    main()
