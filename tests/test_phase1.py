import importlib.util
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('JARVIS_HUD_TOKEN', 'phase1-test-token')
spec = importlib.util.spec_from_file_location('jarvis_server', ROOT / 'server/server.py')
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)


def test_text_startup_health_and_auth():
    with TestClient(server.app) as client:
        assert client.get('/hud/').status_code == 200
        assert client.get('/api/health').status_code == 401
        response = client.get('/api/health', headers={'X-Jarvis-Token': server.hud_token()})
        assert response.json() == {'status': 'ok', 'voice_enabled': False}
        assert server.PIPELINE is None


def test_browser_websocket_auth_and_text_only():
    with TestClient(server.app) as client:
        client.cookies.set('jarvis_token', server.hud_token())
        with client.websocket_connect('/ws', headers={'origin': 'http://localhost:8765'}) as ws:
            assert ws.receive_json()['type'] == 'status'
            ws.send_json({'type': 'start'})
            assert 'Voice is disabled' in ws.receive_json()['message']
        assert not server._proxy_allowed('POST', '/api/sessions')
        assert not server._proxy_allowed('GET', '/../../etc/passwd')


def test_bad_browser_origin_rejected():
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with TestClient(server.app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws', headers={'origin': 'https://evil.example'}):
                pass
