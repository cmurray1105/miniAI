"""Gateway behavior tests — auth, rate limiting, load shedding, metrics.

The model server is mocked; these test the *platform* layer, which is
exactly the part that must not fail in public.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server.gateway as gw  # noqa: E402
from agent.agent import AgentResult  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    def fake_agent(message):
        return AgentResult(
            answer="Finding: ok.\nAssessment: fine.\nNext step: none.",
            trace=[{"type": "tool_call", "tool": "check_disk",
                    "arguments": {"path": "/"}, "result": {"used_percent": 42.0},
                    "latency_ms": 1.0}],
            steps=2, total_latency_ms=100.0, completion_tokens=50,
        )
    monkeypatch.setattr(gw, "run_agent", fake_agent)
    monkeypatch.setattr(gw, "_buckets", type(gw._buckets)(list))
    gw.DEMO_TOKEN = ""
    return TestClient(gw.app)


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_chat_returns_answer_and_trace(client):
    r = client.post("/api/chat", json={"message": "disk?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"].startswith("Finding:")
    assert body["trace"][0]["tool"] == "check_disk"
    assert body["meta"]["completion_tokens"] == 50


def test_auth_enforced_when_token_set(client):
    gw.DEMO_TOKEN = "s3cret"
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 401
    ok = client.post("/api/chat", json={"message": "hi"},
                     headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200


def test_rate_limit(client):
    for _ in range(gw.RATE_LIMIT_PER_MIN):
        assert client.post("/api/chat", json={"message": "x"}).status_code == 200
    assert client.post("/api/chat", json={"message": "x"}).status_code == 429


def test_input_validation(client):
    assert client.post("/api/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/chat", json={"message": "y" * 3000}).status_code == 422


def test_metrics_exposed(client):
    client.post("/api/chat", json={"message": "warm up metrics"})
    text = client.get("/metrics").text
    assert "gateway_requests_total" in text
    assert "gateway_request_latency_seconds_bucket" in text
    assert "gateway_tool_calls_total" in text
