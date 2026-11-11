"""Create local defaults once; never overwrite existing settings or secrets."""
from pathlib import Path
import secrets
import shutil

root = Path(__file__).resolve().parents[1]
config = root / 'server/config/server.yaml'
if not config.exists():
    shutil.copyfile(root / 'server/config/server.local.example.yaml', config)
(root / 'server/logs').mkdir(exist_ok=True)
hermes = root / '.runtime/hermes'
hermes.mkdir(parents=True, exist_ok=True)
if not (hermes / 'config.yaml').exists():
    shutil.copyfile(root / 'deploy/hermes.config.example.yaml', hermes / 'config.yaml')
env = root / 'deploy/.env'
if not env.exists():
    with env.open('x', opener=lambda path, flags: __import__('os').open(path, flags, 0o600)) as stream:
        stream.write(f'JARVIS_HUD_TOKEN={secrets.token_urlsafe(32)}\n')
        stream.write(f'API_SERVER_KEY={secrets.token_urlsafe(40)}\n')
print('Local config is ready; secrets remain in deploy/.env.')
