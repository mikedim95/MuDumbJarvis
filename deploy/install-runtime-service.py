#!/usr/bin/env python3
"""Install a user timer for approved employee runtimes, not task orchestration."""
from pathlib import Path
import os
import subprocess

root = Path(__file__).resolve().parents[1]
units = Path.home() / '.config/systemd/user'
units.mkdir(parents=True, exist_ok=True)
(units / 'jarvis-employee-runtimes.service').write_text('''[Unit]
Description=Provision human-approved JARVIS employee runtimes

[Service]
Type=oneshot
WorkingDirectory=''' + str(root) + '''
ExecStart=/usr/bin/python3 "''' + str(root / 'deploy/staffing.py') + '''" --apply
TimeoutStartSec=240
UMask=0077
''')
(units / 'jarvis-employee-runtimes.timer').write_text('''[Unit]
Description=Reconcile approved JARVIS runtime lifecycle

[Timer]
OnBootSec=30s
OnUnitInactiveSec=15s
AccuracySec=1s
Persistent=true

[Install]
WantedBy=timers.target
''')
environment = {**os.environ, 'XDG_RUNTIME_DIR': '/run/user/' + str(os.getuid())}
subprocess.run(['systemctl', '--user', 'daemon-reload'], env=environment, check=True)
subprocess.run(['systemctl', '--user', 'enable', '--now', 'jarvis-employee-runtimes.timer'], env=environment, check=True)
print('Employee runtime timer enabled. It does not assign tasks or run inference.')
