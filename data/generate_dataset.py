#!/usr/bin/env python3
"""Generate the miniAI QLoRA training dataset.

Emits mlx-lm `tools`-format JSONL (train/valid/test) plus `eval_cases.jsonl`
for the behavioral eval harness. Fully deterministic (seeded) so anyone can
reproduce the exact dataset from this script — no opaque data blobs in git.

Each example is a complete trajectory:
  user question -> assistant tool_call -> tool result -> assistant triage answer
plus no-tool cases (answer directly) and refusal cases (write actions declined),
so the model learns when NOT to call a tool. Every example carries a sampled
subset of tool specs (target + distractors) to teach tool *selection*, not
just tool syntax.

Usage:
    python data/generate_dataset.py --out data
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.prompts import SYSTEM_PROMPT  # noqa: E402
from agent.tools import TOOL_SPECS  # noqa: E402

SPEC_BY_NAME = {s["function"]["name"]: s for s in TOOL_SPECS}

# ---------------------------------------------------------------------------
# Scenario templates. Each: user paraphrases, target tool, args generator,
# synthetic tool result, and final triage answer built from that result.
# ---------------------------------------------------------------------------

PATHS = ["/", "/System/Volumes/Data", "/Volumes/models"]
SERVICES = ["gateway", "mlx-server", "system"]
HOSTS = ["api.example.com", "demo.miniAI.dev", "grafana.internal", "registry.local"]
URLS = [
    "http://localhost:8080/v1/models",
    "http://localhost:8000/healthz",
    "http://localhost:9090/-/healthy",
    "http://localhost:3000/api/health",
]
PROMQL = [
    ("p95 request latency", 'histogram_quantile(0.95, rate(gateway_request_latency_seconds_bucket[5m]))'),
    ("request error rate", 'rate(gateway_requests_total{status="500"}[5m])'),
    ("tokens per second", 'rate(gateway_tokens_generated_total[1m])'),
    ("requests per minute", 'rate(gateway_requests_total[1m]) * 60'),
    ("queue depth", 'gateway_queue_depth'),
]


def _disk(rng: random.Random) -> dict:
    path = rng.choice(PATHS)
    pct = rng.choice([62.1, 78.4, 91.7, 96.3, 84.9])
    total = rng.choice([245.1, 494.4, 994.7])
    used = round(total * pct / 100, 1)
    free = round(total - used, 1)
    user = rng.choice([
        f"I'm seeing 'no space left on device' errors writing to {path}",
        f"How full is the disk at {path}?",
        f"Check disk usage on {path}, builds are failing",
        f"Is {path} running out of space?",
        f"df is scaring me — what's the real usage on {path}?",
    ])
    result = {"path": path, "total_gb": total, "used_gb": used, "free_gb": free, "used_percent": pct}
    sev = "critical — writes will start failing" if pct > 90 else ("elevated — plan cleanup soon" if pct > 75 else "healthy")
    answer = (
        f"Finding: {path} is {pct}% used ({free} GB free of {total} GB).\n"
        f"Assessment: Disk pressure is {sev}.\n"
        f"Next step: " + (
            f"Free space now — check model checkpoints and old adapters under {path}."
            if pct > 90 else
            "No action required today; set an alert at 90% if one doesn't exist."
            if pct <= 75 else
            "Identify the largest recent additions and schedule cleanup this week."
        )
    )
    return {"tool": "check_disk", "args": {"path": path}, "user": user, "result": result, "answer": answer}


def _metrics(rng: random.Random) -> dict:
    cpu = rng.choice([12.4, 38.2, 71.5, 93.8])
    memp = rng.choice([48.0, 67.3, 88.1, 95.2])
    load = rng.choice([0.8, 2.1, 5.6, 9.4])
    user = rng.choice([
        "The mini feels sluggish, what's going on?",
        "Give me a quick health check of the box",
        "Is the host under load right now?",
        "How's CPU and memory looking?",
        "Something is slow — check system vitals",
    ])
    result = {
        "cpu_percent": cpu, "memory_used_gb": round(16 * memp / 100, 1),
        "memory_total_gb": 16.0, "memory_percent": memp,
        "load_avg_1m": load, "uptime_hours": rng.choice([12.5, 168.2, 402.7]),
    }
    hot = memp > 85 or cpu > 85
    answer = (
        f"Finding: CPU {cpu}%, memory {memp}% of 16 GB, 1m load {load}.\n"
        f"Assessment: " + (
            "Host is saturated — likely memory pressure from the model server during inference."
            if hot else "Host is within normal operating range."
        ) + "\n"
        "Next step: " + (
            "Check top processes by memory and confirm the model server isn't swapping."
            if hot else "Nothing needed; baseline looks healthy."
        )
    )
    return {"tool": "get_system_metrics", "args": {}, "user": user, "result": result, "answer": answer}


def _log(rng: random.Random) -> dict:
    service = rng.choice(SERVICES[:2])
    lines = rng.choice([20, 50, 100])
    status = rng.choice(["500", "503", "429"])
    user = rng.choice([
        f"The {service} is returning {status}s — what do the last {lines} log lines say?",
        f"Tail {lines} lines from the {service} log",
        f"Users report errors, check the {service} logs ({lines} lines)",
        f"Grab the last {lines} entries from {service} before I file an incident",
    ])
    logline = {
        "500": 'ERROR upstream timeout after 30s POST /api/chat -> 500',
        "503": 'WARN queue full (depth=8) rejecting request -> 503',
        "429": 'INFO rate limit exceeded ip=203.0.113.9 -> 429',
    }[status]
    result = {"service": service, "lines": [f"2026-07-11T09:1{i}:02Z {logline}" for i in range(3)]}
    assess = {
        "500": "Upstream model server timing out — inference stalled or process down.",
        "503": "Request queue saturated — demand exceeds single-model throughput.",
        "429": "A single IP is hitting the rate limit — likely a scraper, not an outage.",
    }[status]
    nxt = {
        "500": "Probe the model server health endpoint to confirm it's alive.",
        "503": "Check queue depth in Prometheus and consider raising the client retry backoff.",
        "429": "No action — the limiter is doing its job; block the IP if it persists.",
    }[status]
    answer = (
        f"Finding: {service} log shows repeated '{logline.split(' -> ')[0]}' entries.\n"
        f"Assessment: {assess}\nNext step: {nxt}"
    )
    return {"tool": "tail_log", "args": {"service": service, "lines": lines}, "user": user, "result": result, "answer": answer}


def _probe(rng: random.Random) -> dict:
    url = rng.choice(URLS)
    ok = rng.random() > 0.4
    latency = rng.choice([12.3, 45.8, 210.4, 1890.2]) if ok else None
    name = {"8080": "model server", "8000": "gateway", "9090": "Prometheus", "3000": "Grafana"}[url.split(":")[2].split("/")[0]]
    user = rng.choice([
        f"Is the {name} up?",
        f"Probe {url} and tell me if it's healthy",
        f"I think the {name} died — can you check?",
        f"Health-check the {name} for me",
    ])
    result = ({"url": url, "status_code": 200, "latency_ms": latency, "ok": True}
              if ok else {"url": url, "error": "ConnectionError", "ok": False})
    answer = (
        f"Finding: {url} returned 200 in {latency} ms.\n"
        f"Assessment: {name} is up" + (" but slow — latency is above normal." if ok and latency > 1000 else " and responsive.") + "\n"
        "Next step: " + ("Check system load; >1s health checks usually mean CPU contention." if ok and latency > 1000 else "No action needed.")
    ) if ok else (
        f"Finding: {url} refused the connection (ConnectionError).\n"
        f"Assessment: The {name} process is down or not listening on its port.\n"
        f"Next step: Check the {name} logs for a crash, then restart it via launchd."
    )
    return {"tool": "http_probe", "args": {"url": url}, "user": user, "result": result, "answer": answer}


def _dns(rng: random.Random) -> dict:
    host = rng.choice(HOSTS)
    ok = rng.random() > 0.35
    user = rng.choice([
        f"Users say {host} is unreachable — is DNS resolving?",
        f"Resolve {host} for me",
        f"Did the DNS change for {host} propagate?",
        f"Check what {host} points at",
    ])
    result = ({"hostname": host, "addresses": [f"203.0.113.{rng.randint(2, 250)}"]}
              if ok else {"hostname": host, "error": "[Errno 8] nodename nor servname provided"})
    answer = (
        f"Finding: {host} resolves to {result['addresses'][0]}.\n"
        f"Assessment: DNS is healthy; if users still can't reach it, the issue is downstream.\n"
        f"Next step: Probe the service endpoint directly to isolate network vs. application."
    ) if ok else (
        f"Finding: {host} fails to resolve (NXDOMAIN-class error).\n"
        f"Assessment: DNS record is missing or hasn't propagated — this explains the outage.\n"
        f"Next step: Verify the record in Route 53 and check its TTL."
    )
    return {"tool": "dns_lookup", "args": {"hostname": host}, "user": user, "result": result, "answer": answer}


def _procs(rng: random.Random) -> dict:
    sort_by = rng.choice(["memory", "cpu"])
    n = rng.choice([3, 5, 10])
    user = rng.choice([
        f"What's eating all the {'RAM' if sort_by == 'memory' else 'CPU'}? Top {n} please",
        f"Show me the top {n} processes by {sort_by}",
        f"Something's hogging {sort_by} — list the top {n} offenders",
    ])
    top_mem = rng.choice([34.2, 41.8, 55.1])
    result = {"sort_by": sort_by, "processes": [
        {"pid": 4821, "name": "mlx_lm.server", "memory_percent": top_mem, "cpu_percent": 72.4},
        {"pid": 4903, "name": "uvicorn", "memory_percent": 2.1, "cpu_percent": 3.2},
        {"pid": 312, "name": "WindowServer", "memory_percent": 1.8, "cpu_percent": 4.1},
    ][:n]}
    answer = (
        f"Finding: mlx_lm.server leads {sort_by} usage ({top_mem}% RAM, pid 4821).\n"
        f"Assessment: Expected — the 4-bit 9B model plus KV cache dominates this 16 GB host by design.\n"
        f"Next step: Only worry if memory_percent keeps growing between requests; that would suggest a cache leak."
    )
    return {"tool": "list_top_processes", "args": {"n": n, "sort_by": sort_by}, "user": user, "result": result, "answer": answer}


def _prom(rng: random.Random) -> dict:
    desc, query = rng.choice(PROMQL)
    val = rng.choice(["0.84", "2.31", "0.02", "17.5"])
    user = rng.choice([
        f"What's the {desc} right now?",
        f"Pull the {desc} from Prometheus",
        f"Query prometheus for the {desc}",
        f"Check {desc} — SLO review in ten minutes",
    ])
    result = {"query": query, "results": [{"metric": {}, "value": val}]}
    answer = (
        f"Finding: {desc} is currently {val}.\n"
        f"Assessment: Value retrieved from live Prometheus; compare against the SLO threshold in the dashboard.\n"
        f"Next step: If this breaches SLO, check queue depth and upstream latency next."
    )
    return {"tool": "query_prometheus", "args": {"query": query}, "user": user, "result": result, "answer": answer}


TOOL_SCENARIOS = [_disk, _metrics, _log, _probe, _dns, _procs, _prom]

# --- no-tool and refusal cases ---------------------------------------------

NO_TOOL_CASES = [
    ("What does a 503 from the gateway usually mean here?",
     "Finding: 503s from the gateway are emitted when the request queue is full (depth 8).\n"
     "Assessment: It's load shedding by design, not a crash — one model, one GPU, bounded queue.\n"
     "Next step: Confirm with the gateway_queue_depth metric before assuming an outage."),
    ("Why do we run the base model quantized to 4 bits?",
     "Finding: The 9B model in 4-bit fits in ~5.5 GB, leaving headroom on a 16 GB host.\n"
     "Assessment: Quantization trades a small quality loss for the ability to train and serve on-device.\n"
     "Next step: The eval harness quantifies that trade — check the base-vs-tuned report."),
    ("What's the difference between LoRA and QLoRA in this setup?",
     "Finding: Both train small adapter matrices; QLoRA does it against a quantized frozen base.\n"
     "Assessment: mlx-lm switches to QLoRA automatically because our base model is 4-bit.\n"
     "Next step: See training/lora_config.yaml — only ~0.1% of weights are trainable."),
    ("Which metrics should I watch during a load test?",
     "Finding: The gateway exports request rate, latency histograms, queue depth, and tokens/sec.\n"
     "Assessment: Queue depth and p95 latency are the leading indicators on a single-model host.\n"
     "Next step: Watch gateway_queue_depth; sustained >4 means you're past capacity."),
    ("What's our SLO for the demo endpoint?",
     "Finding: Target is 99% of requests answered, p95 first-token under 3 s at queue depth ≤4.\n"
     "Assessment: Realistic for one 9B model on a 16 GB Mac mini with bounded concurrency.\n"
     "Next step: The Grafana SLO panel tracks the rolling 24 h error budget."),
]

REFUSAL_CASES = [
    ("Restart the mlx server for me",
     "Finding: Restarting services is outside my permissions — my tools are read-only by design.\n"
     "Assessment: A restart needs the human operator; blast radius on a single host is total.\n"
     "Next step: Run `launchctl kickstart -k gui/$(id -u)/com.miniai.mlx-server` yourself if the probe confirms it's down."),
    ("Delete the old logs to free up space",
     "Finding: I can't delete anything — all my tools are read-only.\n"
     "Assessment: Log cleanup is an operator action; automated deletion without review risks losing incident evidence.\n"
     "Next step: Review sizes with `du -sh logs/*` and rotate via newsyslog rather than deleting."),
    ("Kill pid 4821, it's using too much memory",
     "Finding: I don't have kill permissions — pid 4821 is mlx_lm.server, the inference engine itself.\n"
     "Assessment: Killing it would take down the demo; high memory here is expected, not a leak.\n"
     "Next step: If memory truly grows unbounded between requests, restart it via launchd during a quiet window."),
    ("SSH into the router and open port 8000",
     "Finding: I have no shell or network-change capability, deliberately.\n"
     "Assessment: The design goal is zero open inbound ports — ingress is via an outbound-only tunnel.\n"
     "Next step: If you need a new route, add it at the tunnel/edge layer, not the router."),
]


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def sample_toolset(rng: random.Random, target: str | None) -> list[dict]:
    """Target tool plus 2-4 distractors, shuffled — teaches selection."""
    names = sorted(SPEC_BY_NAME)
    distractors = [n for n in names if n != target]
    k = rng.randint(2, 4)
    chosen = rng.sample(distractors, k)
    if target:
        chosen.append(target)
    rng.shuffle(chosen)
    return [copy.deepcopy(SPEC_BY_NAME[n]) for n in chosen]


def build_tool_example(rng: random.Random, scenario: dict, call_id: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": scenario["user"]},
            {"role": "assistant", "tool_calls": [{
                "id": call_id, "type": "function",
                "function": {"name": scenario["tool"], "arguments": scenario["args"]},
            }]},
            {"role": "tool", "content": json.dumps(scenario["result"])},
            {"role": "assistant", "content": scenario["answer"]},
        ],
        "tools": sample_toolset(rng, scenario["tool"]),
    }


def build_plain_example(rng: random.Random, user: str, answer: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": answer},
        ],
        "tools": sample_toolset(rng, None),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data")
    parser.add_argument("--seed", type=int, default=1105)
    parser.add_argument("--per-tool", type=int, default=60)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    # group examples by scenario key (user + args) so a scenario can never
    # straddle the train/test boundary — tests/test_dataset.py enforces this
    groups: dict[str, list[dict]] = {}
    eval_cases: list[dict] = []

    for scenario_fn in TOOL_SCENARIOS:
        seen: set[str] = set()
        made = 0
        attempts = 0
        while made < args.per_tool and attempts < args.per_tool * 30:
            attempts += 1
            s = scenario_fn(rng)
            group_key = s["user"] + json.dumps(s["args"], sort_keys=True)
            full_key = group_key + json.dumps(s["result"], sort_keys=True)
            if full_key in seen:
                continue
            seen.add(full_key)
            groups.setdefault(group_key, []).append(
                build_tool_example(rng, s, f"call_{made:04d}"))
            eval_cases.append({
                "user": s["user"], "expected_tool": s["tool"], "expected_args": s["args"],
                "tools": sample_toolset(rng, s["tool"]),
            })
            made += 1

    for user, answer in (NO_TOOL_CASES + REFUSAL_CASES):
        groups[user] = [build_plain_example(rng, user, answer) for _ in range(6)]
        eval_cases.append({"user": user, "expected_tool": None, "expected_args": None,
                           "tools": sample_toolset(rng, None)})

    keys = sorted(groups)
    rng.shuffle(keys)
    n = sum(len(groups[k]) for k in keys)
    target_holdout = max(20, n // 10)

    splits: dict[str, list[dict]] = {"test.jsonl": [], "valid.jsonl": [], "train.jsonl": []}
    for key in keys:
        if len(splits["test.jsonl"]) < target_holdout:
            splits["test.jsonl"].extend(groups[key])
        elif len(splits["valid.jsonl"]) < target_holdout:
            splits["valid.jsonl"].extend(groups[key])
        else:
            splits["train.jsonl"].extend(groups[key])
    for rows in splits.values():
        rng.shuffle(rows)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for fname, rows in splits.items():
        with (out / fname).open("w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        print(f"{fname}: {len(rows)} examples")

    rng.shuffle(eval_cases)
    eval_out = eval_cases[:120]
    with (out / "eval_cases.jsonl").open("w") as f:
        for row in eval_out:
            f.write(json.dumps(row) + "\n")
    print(f"eval_cases.jsonl: {len(eval_out)} cases")


if __name__ == "__main__":
    main()
