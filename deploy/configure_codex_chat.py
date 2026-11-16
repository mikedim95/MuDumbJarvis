#!/usr/bin/env python3
"""Configure the user-authorized Codex direct-chat demo; no inference or tasks.

Keeps chat's existing Hermes profile, database and history separate from CEO.
Default is dry-run. Credentials remain server-side in the private profile.
"""
import argparse
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import yaml
import staffing

MODEL = 'gpt-6.1-sol'
ENDPOINT = 'https://chatgpt.com/backend-api/codex'


def codex_config(config):
    config = {**config, 'model': {'provider': 'openai-codex', 'default': MODEL,
        'base_url': ENDPOINT, 'context_length': 65536}, 'fallback_model': None, 'fallback_providers': []}
    config.pop('providers', None)
    config.pop('fallback_models', None)
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = staffing.ROOT; home = root / '.runtime/hermes'
    config = yaml.safe_load((home / 'config.yaml').read_text())
    auth_path = Path.home() / '.codex/auth.json'
    original_auth = auth_path.read_bytes(); credentials = json.loads(original_auth)
    if not credentials.get('tokens', {}).get('access_token'):
        raise RuntimeError('Existing server-side Codex login required')
    view = {'provider': 'openai-codex', 'model': MODEL, 'direct_profile': '.runtime/hermes',
        'ceo_profile_changed': False, 'session_history_recreated': False, 'local_fallback': False,
        'apply': args.apply}
    if not args.apply:
        print(json.dumps(view)); return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = root / '.runtime/backups/codex-chat' / stamp
    backup.mkdir(parents=True, mode=0o700)
    for name in ('config.yaml', 'SOUL.md', 'auth.json'):
        if (home / name).exists():
            shutil.copy2(home / name, backup / name); (backup / name).chmod(0o600)
    mapping = root / 'server/logs/hermes_sessions.json'
    if mapping.exists():
        staffing.write_private(backup / 'session-map.json', mapping.read_text())
    script = ('import json,sys; from hermes_cli.auth import _save_codex_tokens,resolve_codex_runtime_credentials; '
        'a=json.load(sys.stdin); _save_codex_tokens(a["tokens"],a.get("last_refresh")); '
        'c=resolve_codex_runtime_credentials(read_only=True); '
        'assert c["base_url"].startswith("https://chatgpt.com/backend-api/codex"); '
        'print("credential_import_verified")')
    imported = subprocess.run(['docker', 'exec', '-i', 'jarvis-hermes', '/opt/hermes/.venv/bin/python', '-c', script],
        input=json.dumps(credentials), text=True, capture_output=True, timeout=30)
    if imported.returncode or 'credential_import_verified' not in imported.stdout:
        raise RuntimeError('Codex credential import failed; no configuration changed')
    staffing.write_private(home / 'config.yaml', yaml.safe_dump(codex_config(config), sort_keys=False))
    staffing.write_private(home / 'SOUL.md',
        'You are JARVIS, a concise and precise conversational assistant powered by OpenAI Codex. '
        'Talk naturally with the user and answer their current message. Direct chat is separate '
        'from persistent CEO objectives and does not assign Paperclip tasks. Use local_ollama_models '
        'only when actual installed model information is requested; that tool reads metadata, '
        'it does not provide local inference. Never claim tool use without an actual tool result. '
        'Host filesystem changes, shell commands and external actions are unavailable.\n')
    if auth_path.read_bytes() != original_auth:
        raise RuntimeError('Source Codex login unexpectedly changed; inspect private backup')
    view.update(backup=str(backup.relative_to(root)), credentials_verified_without_refresh=True,
        next='Recreate only jarvis and hermes with the Codex chat Compose overlay; verify actual HUD runtime metadata.')
    staffing.write_private(backup / 'receipt.json', json.dumps(view, indent=2))
    print(json.dumps(view))


if __name__ == '__main__':
    main()
