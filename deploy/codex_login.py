"""Keep an enrolled Hermes pool on the operator's existing local Codex login."""
import argparse
import asyncio
import base64
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time


PROVIDER = 'openai-codex'
ENTRY = 'jarvis-local-codex'
BASE = 'https://chatgpt.com/backend-api/codex'
LOCAL_LOGIN = Path.home() / '.codex-nektarios/auth.json'
STORE = Path(__file__).resolve().parents[1] / '.runtime/codex-shared/auth.json'


def claims(token):
    # Both tokens originate in operator-owned local files. The provider verifies
    # signatures. These claims only prevent mirroring a different local login.
    try:
        _, payload, _ = token.split('.')
        data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        account = data['https://api.openai.com/auth']['chatgpt_account_id']
        subject = data['sub']
        if data['iss'] != 'https://auth.openai.com' or not account or not subject:
            raise ValueError
        return (account, subject), int(data['exp'])
    except (AttributeError, TypeError, KeyError, ValueError):
        raise ValueError('Unrecognized local Codex identity.') from None


def private_json(path):
    if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError('Codex credentials must be private operator-owned files.')
    return json.loads(path.read_bytes())


def write_store(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.codex-login-')
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out, indent=2)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


async def read_cli_account(login, *, refresh):
    """Let the installed Codex client own rotation. Suppress account and token output."""
    client = await asyncio.create_subprocess_exec(
        str(Path.home() / '.local/bin/codex'), 'app-server', '--listen', 'stdio://',
        cwd=login.parent, env={**os.environ, 'CODEX_HOME': str(login.parent)},
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)

    async def rpc(request_id, method, params):
        client.stdin.write((json.dumps({'id': request_id, 'method': method, 'params': params}) + '\n').encode())
        await client.stdin.drain()
        while line := await client.stdout.readline():
            response = json.loads(line)
            if response.get('id') == request_id:
                if 'result' in response:
                    return response['result']
                break
        raise RuntimeError('Codex could not confirm the local login.')

    try:
        async with asyncio.timeout(30):
            await rpc(1, 'initialize', {'clientInfo': {'name': 'jarvis-login', 'version': '1'}})
            client.stdin.write(b'{"method":"initialized"}\n')
            result = await rpc(2, 'account/read', {'refreshToken': refresh})
            if not result.get('account'):
                raise RuntimeError('Local Codex sign-in is required.')
    finally:
        client.stdin.close()
        try:
            await asyncio.wait_for(client.wait(), 2)
        except TimeoutError:
            client.kill()
            await client.wait()


def maintain(store=STORE, login=LOCAL_LOGIN):
    if not store.exists():
        return False
    data = private_json(store)
    rows = data.get('credential_pool', {}).get(PROVIDER) or []
    if len(rows) != 1 or rows[0].get('id') != ENTRY:
        return False
    # Network I/O runs outside the Hermes lock. sync rechecks both identities
    # under lock in case either file changed while Codex renewed the login.
    account, expiry = claims(private_json(login)['tokens']['access_token'])
    if account == claims(rows[0]['access_token'])[0] and expiry <= time.time() + 1800:
        asyncio.run(read_cli_account(login, refresh=True))
    return sync(store, login)


def sync(store=STORE, login=LOCAL_LOGIN, *, enroll=False):
    if not store.exists() and not enroll:
        return False
    # Same lock and atomic replacement as native Hermes auth.json writers.
    with store.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        data = private_json(store)
        rows = data.get('credential_pool', {}).get(PROVIDER, [])
        managed = next((row for row in rows if row.get('id') == ENTRY), None)
        if managed is None and not enroll:
            return False
        state = data.get('providers', {}).get(PROVIDER)
        if managed:
            if len(rows) != 1 or state or managed.get('base_url') != BASE or managed.get('refresh_token'):
                raise ValueError('Conflicting Hermes Codex configuration.')
            previous = managed['access_token']
        else:
            if rows or not state:
                raise ValueError('Enrollment requires a single existing Hermes Codex login.')
            previous = state['tokens']['access_token']
        current = private_json(login)['tokens']['access_token']
        identity, expiry = claims(current)
        previous_identity, previous_expiry = claims(previous)
        if identity != previous_identity or expiry <= time.time() or expiry < previous_expiry:
            raise ValueError('The local Codex login is expired, older, or belongs to another account.')
        if managed:
            if current == previous:
                return False
            managed['access_token'] = current
        else:
            del data['providers'][PROVIDER]
            data.setdefault('credential_pool', {})[PROVIDER] = [{
                'id': ENTRY, 'label': 'Operator Codex login', 'priority': 0,
                'source': 'manual:api_key', 'auth_type': 'api_key',
                'base_url': BASE, 'access_token': current,
            }]
        write_store(store, data)
        return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enroll', action='store_true', help='Migrate the existing same-account Hermes login.')
    changed = sync(enroll=True) if parser.parse_args().enroll else maintain()
    print('Codex login updated.' if changed else 'No update.')
