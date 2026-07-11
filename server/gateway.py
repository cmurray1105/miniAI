"""miniAI API gateway — the production layer in front of the model.

What this adds over exposing mlx_lm.server directly:

  * bounded concurrency + queue  — one 9B model on 16 GB serves exactly one
    request at a time; excess load is shed with 503s instead of OOM-killing
    the box (load shedding > falling over)
  * per-IP token-bucket rate limiting — this is going on the public internet
  * optional bearer-token auth for the demo endpoint
  * Prometheus metrics: request rate, latency histograms, tokens/sec,
    live queue depth (scraped by the local Prometheus, graphed in Grafana)
  * health (/healthz) and readiness (/readyz) endpoints — readiness actually
    checks the upstream model server, so the edge can route around a dead model

Run:  uvicorn server.gateway:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from pathlib import Path

import anyio
import requests as _requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from prometheus_client import (CONTENT_TYPE_LATEST, Counter, Gauge, Histogram,
                               generate_latest)
from pydantic import BaseModel, Field

from agent.agent import MODEL_SERVER, run_agent
from server.config import get_demo_token, load_config

# --- config -------------------------------------------------------------------
# ALL config comes from SSM Parameter Store (Terraform-managed), resolved once
# at startup; env vars are a local-dev fallback only. See server/config.py.
_cfg = load_config()
RATE_LIMIT_PER_MIN = _cfg["rate-limit-per-min"]
MAX_QUEUE_DEPTH = _cfg["max-queue-depth"]
QUEUE_TIMEOUT_S = _cfg["queue-timeout-s"]
# The token (SecureString) is only fetched when auth is actually required;
# empty token = public demo mode
DEMO_TOKEN = get_demo_token() if _cfg["require-auth"] else ""

# --- metrics ------------------------------------------------------------------
REQUESTS = Counter("gateway_requests_total", "Requests by status", ["status"])
LATENCY = Histogram(
    "gateway_request_latency_seconds", "End-to-end request latency",
    buckets=[0.5, 1, 2, 4, 8, 16, 30, 60, 120],
)
TOKENS = Counter("gateway_tokens_generated_total", "Completion tokens generated")
QUEUE_DEPTH = Gauge("gateway_queue_depth", "Requests waiting or running")
TOOL_CALLS = Counter("gateway_tool_calls_total", "Agent tool calls", ["tool"])

app = FastAPI(title="miniAI gateway", docs_url=None, redoc_url=None)

_inference_lock = asyncio.Semaphore(1)   # one model, one request at a time
_queued = 0
_buckets: dict[str, list[float]] = defaultdict(list)

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else None) or request.client.host


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    window = [t for t in _buckets[ip] if now - t < 60]
    _buckets[ip] = window
    if len(window) >= RATE_LIMIT_PER_MIN:
        return True
    window.append(now)
    return False


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/readyz")
async def readyz() -> dict:
    """Ready only if the upstream model server answers."""
    try:
        resp = await anyio.to_thread.run_sync(
            lambda: _requests.get(f"{MODEL_SERVER}/v1/models", timeout=5)
        )
        if resp.ok:
            return {"ok": True, "model_server": "up"}
    except _requests.RequestException:
        pass
    raise HTTPException(status_code=503, detail="model server unreachable")


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/stats")
async def stats() -> dict:
    return {"queue_depth": _queued, "max_queue": MAX_QUEUE_DEPTH,
            "rate_limit_per_min": RATE_LIMIT_PER_MIN}


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request) -> dict:
    global _queued

    if DEMO_TOKEN:
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {DEMO_TOKEN}":
            REQUESTS.labels(status="401").inc()
            raise HTTPException(status_code=401, detail="missing or invalid token")

    ip = _client_ip(request)
    if _rate_limited(ip):
        REQUESTS.labels(status="429").inc()
        raise HTTPException(status_code=429,
                            detail=f"rate limit: {RATE_LIMIT_PER_MIN} requests/min")

    if _queued >= MAX_QUEUE_DEPTH:
        REQUESTS.labels(status="503").inc()
        raise HTTPException(status_code=503, detail="queue full — try again shortly")

    _queued += 1
    QUEUE_DEPTH.set(_queued)
    t0 = time.monotonic()
    try:
        try:
            await asyncio.wait_for(_inference_lock.acquire(), timeout=QUEUE_TIMEOUT_S)
        except (TimeoutError, asyncio.TimeoutError):
            REQUESTS.labels(status="503").inc()
            raise HTTPException(status_code=503, detail="queue wait timed out")
        try:
            result = await anyio.to_thread.run_sync(run_agent, body.message)
        finally:
            _inference_lock.release()
    except HTTPException:
        raise
    except Exception:
        REQUESTS.labels(status="500").inc()
        raise HTTPException(status_code=500, detail="inference failed")
    finally:
        _queued -= 1
        QUEUE_DEPTH.set(_queued)

    elapsed = time.monotonic() - t0
    LATENCY.observe(elapsed)
    TOKENS.inc(result.completion_tokens)
    REQUESTS.labels(status="200").inc()
    for step in result.trace:
        if step["type"] == "tool_call":
            TOOL_CALLS.labels(tool=step["tool"]).inc()

    return {
        "answer": result.answer,
        "trace": result.trace,
        "meta": {
            "steps": result.steps,
            "latency_ms": result.total_latency_ms,
            "completion_tokens": result.completion_tokens,
            "tokens_per_sec": round(result.completion_tokens / elapsed, 1) if elapsed else 0,
        },
    }
