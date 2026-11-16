#!/usr/bin/env python3
"""Verify real Codex chat and an agent tool-triggered popup; no task creation."""
import os
import subprocess
import staffing


if __name__ == '__main__':
    env = staffing.settings()
    command = ['docker','run','--rm','--name','jarvis-minimal-browser','--network','host',
        '--user','1000:1000','--cpus','4','--memory','2g','--pids-limit','512','-e','JARVIS_HUD_TOKEN',
        '-v',str(staffing.ROOT)+':/workspace','--tmpfs','/tmp:size=256m',
        'jarvis-command-center:browser-test','tests/minimal_codex_e2e.cjs']
    raise SystemExit(subprocess.run(command,env={**os.environ,'JARVIS_HUD_TOKEN':env['JARVIS_HUD_TOKEN']}).returncode)
