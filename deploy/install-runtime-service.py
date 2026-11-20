#!/usr/bin/env python3
"""Install a user timer for approved employee runtimes, not task orchestration."""
from pathlib import Path
import argparse
import os
import subprocess

parser = argparse.ArgumentParser()
selection = parser.add_mutually_exclusive_group()
selection.add_argument('--packages-only', action='store_true', help='Install only the assignment package service')
selection.add_argument('--projects-only', action='store_true', help='Install only automatic project CLI provisioning')
args = parser.parse_args()

root = Path(__file__).resolve().parents[1]
units = Path.home() / '.config/systemd/user'
units.mkdir(parents=True, exist_ok=True)
environment = {**os.environ, 'XDG_RUNTIME_DIR': '/run/user/' + str(os.getuid())}
if not args.packages_only:
    (units / 'jarvis-project-cli.service').write_text('''[Unit]
Description=Start project CLI containers for active JARVIS missions

[Service]
WorkingDirectory=''' + str(root) + '''
ExecStart=/usr/bin/python3 "''' + str(root / 'deploy/project_cli_service.py') + '''"
Restart=on-failure
RestartSec=3
UMask=0077

[Install]
WantedBy=default.target
''')
if args.projects_only:
    subprocess.run(['systemctl','--user','daemon-reload'], env=environment, check=True)
    subprocess.run(['systemctl','--user','enable','--now','jarvis-project-cli.service'], env=environment, check=True)
    raise SystemExit(0)
(units / 'jarvis-approved-packages.service').write_text('''[Unit]
Description=Provision owner-approved Debian packages for JARVIS assignments

[Service]
Type=oneshot
WorkingDirectory=''' + str(root) + '''
ExecStart=/usr/bin/python3 "''' + str(root / 'deploy/approved_packages.py') + '''"
TimeoutStartSec=12min
UMask=0077
''')
(units / 'jarvis-approved-packages.timer').write_text('''[Unit]
Description=Process approved JARVIS software requests

[Timer]
OnStartupSec=15s
OnUnitInactiveSec=30s
AccuracySec=2s

[Install]
WantedBy=timers.target
''')

if not args.packages_only:
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
    (units / 'jarvis-codex-login.service').write_text('''[Unit]
Description=Keep the enrolled Hermes login current through the operator's Codex client

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 "''' + str(root / 'deploy/codex_login.py') + '''"
TimeoutStartSec=50
UMask=0077
''')
    (units / 'jarvis-codex-login.timer').write_text('''[Unit]
Description=Check the enrolled JARVIS Codex login

[Timer]
OnStartupSec=20s
OnUnitInactiveSec=2min
AccuracySec=5s

[Install]
WantedBy=timers.target
''')

timers = ['jarvis-approved-packages.timer']
if not args.packages_only:
    timers.extend(['jarvis-employee-runtimes.timer', 'jarvis-codex-login.timer'])
if not args.packages_only:
    timers.append('jarvis-project-cli.service')
subprocess.run(['systemctl', '--user', 'daemon-reload'], env=environment, check=True)
subprocess.run(['systemctl', '--user', 'enable', '--now', *timers], env=environment, check=True)
print('Enabled ' + ', '.join(timers))
