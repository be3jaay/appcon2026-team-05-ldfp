"""Websocket route + origin checks, through FastAPI's TestClient (no network)."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.config import settings
from src.controllers import claims_controller
from src.controllers.claims_controller import get_llm_factory
from src.main import app
from src.services import soniox_service

from .conftest import KeywordFakeLLM

ALLOWED = {"origin": "http://localhost:3000"}
FOREIGN = {"origin": "https://evil.example"}


@pytest.fixture
def llm():
    return KeywordFakeLLM()


@pytest.fixture
def client(llm, monkeypatch):
    monkeypatch.setattr(settings, "cors_allow_origins", ["http://localhost:3000"])
    app.dependency_overrides[get_llm_factory] = lambda: (lambda: llm)
    yield TestClient(app)
    app.dependency_overrides.clear()


def receive_until_done(ws) -> list[dict]:
    messages = []
    while True:
        m = ws.receive_json()
        messages.append(m)
        if m["type"] == "done" or m.get("fatal"):
            return messages


def test_ws_streams_skips_and_claims(client, llm):
    with client.websocket_connect("/api/v1/claims/ws", headers=ALLOWED) as ws:
        ws.send_json({"type": "segment", "segment": {"segment_id": 0, "text": "Magandang hapon po.", "speaker": "1"}})
        for i, text in enumerate(
            [
                "Ang ₱125 milyon ay naubos sa loob ng 11 araw.",
                "Ayon sa Konstitusyon, dapat agad ang trial.",
                "Sa tingin ko nakakahiya ang ganitong sistema ng gobyerno.",
            ],
            start=1,
        ):
            ws.send_json(
                {"type": "segment", "segment": {"segment_id": i, "text": text, "speaker": "2", "start_ms": i * 1000}}
            )
        ws.send_json({"type": "stop"})
        messages = receive_until_done(ws)

    types = [m["type"] for m in messages]
    assert types[0] == "skipped" and messages[0]["segment_id"] == "0"
    claims = [c for m in messages if m["type"] == "claims" for c in m["claims"]]
    assert [(c["segment_id"], c["type"]) for c in claims] == [("1", "fact"), ("2", "legal"), ("3", "opinion")]
    assert claims[0]["timestamp"] == 1000
    assert messages[-1] == {"type": "done", "claims": 3, "skipped": 1, "llm_calls": 1}
    assert llm.call_count == 1


def test_ws_reports_invalid_messages_and_keeps_going(client):
    with client.websocket_connect("/api/v1/claims/ws", headers=ALLOWED) as ws:
        ws.send_json({"type": "segment", "segment": {"text": "missing id"}})
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "dance"})
        assert "Unknown message type" in ws.receive_json()["message"]
        ws.send_json({"type": "stop"})
        assert ws.receive_json()["type"] == "done"


def test_ws_rejects_foreign_origin(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/v1/claims/ws", headers=FOREIGN) as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_ws_missing_gemini_key_is_a_clear_fatal_error(monkeypatch):
    monkeypatch.setattr(settings, "cors_allow_origins", ["http://localhost:3000"])
    monkeypatch.setattr(settings, "gemini_api_key", None)
    app.dependency_overrides[get_llm_factory] = lambda: claims_controller.gemini_factory
    try:
        with TestClient(app).websocket_connect("/api/v1/claims/ws", headers=ALLOWED) as ws:
            m = ws.receive_json()
    finally:
        app.dependency_overrides.clear()
    assert m["type"] == "error" and m["fatal"] and "GEMINI_API_KEY" in m["message"]


def test_temporary_key_rejects_foreign_origin(client, monkeypatch):
    called = []
    monkeypatch.setattr(soniox_service, "create_temporary_key", lambda s: called.append(s) or {"api_key": "t"})

    assert client.post("/api/soniox/temporary-key", json={}, headers=FOREIGN).status_code == 403
    assert called == []  # no Soniox key minted for a foreign site

    ok = client.post("/api/soniox/temporary-key", json={}, headers=ALLOWED)
    assert ok.status_code == 200 and ok.json() == {"api_key": "t"}


def test_cors_only_allows_configured_origin():
    # CORS middleware reads the list at app construction, so check the real default.
    c = TestClient(app)
    preflight = {"access-control-request-method": "POST"}
    good = c.options("/api/soniox/temporary-key", headers={**preflight, **ALLOWED})
    bad = c.options("/api/soniox/temporary-key", headers={**preflight, **FOREIGN})
    assert good.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers
