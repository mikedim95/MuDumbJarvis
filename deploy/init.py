"""Create local defaults once; never overwrite existing settings or secrets."""
from pathlib import Path
import secrets
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
config = root / 'server/config/server.yaml'
if not config.exists():
    shutil.copyfile(root / 'server/config/server.local.example.yaml', config)
(root / 'server/logs').mkdir(exist_ok=True)
hermes = root / '.runtime/hermes'
hermes.mkdir(parents=True, exist_ok=True)
if not (hermes / 'config.yaml').exists():
    shutil.copyfile(root / 'deploy/hermes.config.example.yaml', hermes / 'config.yaml')
if not (hermes / 'SOUL.md').exists():
    shutil.copyfile(root / 'deploy/hermes.SOUL.md', hermes / 'SOUL.md')
env = root / 'deploy/.env'
if not env.exists():
    with env.open('x', opener=lambda path, flags: __import__('os').open(path, flags, 0o600)) as stream:
        stream.write(f'JARVIS_HUD_TOKEN={secrets.token_urlsafe(32)}\n')
        stream.write(f'API_SERVER_KEY={secrets.token_urlsafe(40)}\n')
current = env.read_text()
with env.open('a') as stream:
    for name in ('BETTER_AUTH_SECRET', 'PAPERCLIP_TOOL_ACTION_SIGNING_SECRET', 'PAPERCLIP_SECRETS_MASTER_KEY', 'PAPERCLIP_AGENT_JWT_SECRET', 'API_SERVER_CEO_KEY', 'JARVIS_EXECUTION_PROOF_KEY'):
        if not any(line.startswith(name + '=') for line in current.splitlines()):
            stream.write(f'{name}={secrets.token_hex(32)}\n')
ceo = root / '.runtime/hermes-ceo'
ceo.mkdir(parents=True, exist_ok=True)
if not (ceo / 'config.yaml').exists():
    shutil.copyfile(root / 'deploy/hermes.ceo.config.example.yaml', ceo / 'config.yaml')
if not (ceo / 'SOUL.md').exists():
    shutil.copyfile(root / 'deploy/CEO_POLICY.md', ceo / 'SOUL.md')
(root / '.runtime/paperclip').mkdir(parents=True, exist_ok=True)
tls = root / '.runtime/tls'
tls.mkdir(exist_ok=True)
if not (tls / 'hermes.crt').exists():
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-days', '3650', '-subj', '/CN=jarvis-hermes-internal',
        '-addext', 'subjectAltName=DNS:hermes-tls',
        '-keyout', str(tls / 'hermes.key'), '-out', str(tls / 'hermes.crt')],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (tls / 'hermes.key').chmod(0o600)
print('Local config is ready; secrets remain in deploy/.env.')
