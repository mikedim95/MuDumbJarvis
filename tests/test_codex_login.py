import base64
import json
from pathlib import Path
import sys
import time
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import codex_login as mirror


def token(expiry, account='account', subject='operator'):
    payload = {'iss': 'https://auth.openai.com', 'sub': subject, 'exp': expiry,
               'https://api.openai.com/auth': {'chatgpt_account_id': account}}
    return 'header.' + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=') + '.fixture'


@pytest.fixture
def stores(tmp_path):
    store = tmp_path / 'auth.json'
    login = tmp_path / 'cli.json'
    previous = token(int(time.time()) - 100)
    current = token(int(time.time()) + 10000)
    mirror.write_store(store, {'providers': {mirror.PROVIDER: {'tokens': {
        'access_token': previous, 'refresh_token': 'stale-refresh'}}, 'unrelated': {'keep': True}}})
    mirror.write_store(login, {'tokens': {'access_token': current, 'refresh_token': 'cli-only'}})
    return store, login


def test_enrollment_and_rotation_preserve_source_identity_other_providers_and_quota(stores):
    store, login = stores
    original = login.read_bytes()
    assert not mirror.maintain(store, login)
    assert mirror.sync(store, login, enroll=True)
    initial = json.loads(store.read_bytes())
    assert initial['providers'] == {'unrelated': {'keep': True}}
    row = initial['credential_pool'][mirror.PROVIDER][0]
    assert row['access_token'] == json.loads(original)['tokens']['access_token'] and row['base_url'] == mirror.BASE
    assert 'refresh_token' not in store.read_text() and login.read_bytes() == original
    assert store.stat().st_mode & 0o777 == 0o600
    assert not mirror.maintain(store, login)
    row['last_error_reset_at'] = int(time.time()) + 500
    mirror.write_store(store, initial)
    new = token(int(time.time()) + 20000)
    mirror.write_store(login, {'tokens': {'access_token': new}})
    assert mirror.maintain(store, login)
    assert json.loads(store.read_bytes())['credential_pool'][mirror.PROVIDER] == [dict(row, access_token=new)]


@pytest.mark.parametrize('account,subject,offset', [('other', 'operator', 20000), ('account', 'other', 20000),
                                                     ('account', 'operator', -1), ('account', 'operator', 100)])
def test_rejects_different_accounts_expired_and_older_tokens(stores, account, subject, offset):
    store, login = stores
    mirror.sync(store, login, enroll=True)
    original = store.read_bytes()
    mirror.write_store(login, {'tokens': {'access_token': token(int(time.time()) + offset, account, subject)}})
    with pytest.raises(ValueError):
        mirror.sync(store, login)
    assert store.read_bytes() == original


def test_near_expiry_renews_via_codex_before_mirroring(stores, monkeypatch):
    store, login = stores
    now = int(time.time())
    mirror.write_store(login, {'tokens': {'access_token': token(now + 10)}})
    mirror.sync(store, login, enroll=True)
    renewed = token(now + 10000)
    refresh = AsyncMock(side_effect=lambda *args, **kwargs: mirror.write_store(login, {'tokens': {'access_token': renewed}}))
    monkeypatch.setattr(mirror, 'read_cli_account', refresh)
    assert mirror.maintain(store, login)
    refresh.assert_awaited_once_with(login, refresh=True)
    assert json.loads(store.read_bytes())['credential_pool'][mirror.PROVIDER][0]['access_token'] == renewed


def test_conflicting_manual_pool_cannot_be_replaced(stores):
    store, login = stores
    data = json.loads(store.read_bytes())
    data['credential_pool'] = {mirror.PROVIDER: [{'id': 'manual'}]}
    mirror.write_store(store, data)
    original = store.read_bytes()
    with pytest.raises(ValueError):
        mirror.sync(store, login, enroll=True)
    assert store.read_bytes() == original
