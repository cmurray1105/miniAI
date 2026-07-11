"""Tool registry for the miniAI incident copilot.

Every tool is read-only and allowlist-guarded. The agent never gets a shell.
Specs follow the OpenAI function-calling schema (which Qwen's chat template
renders into <tool_call> format during training and inference).

This module is the single source of truth for tool schemas: the dataset
generator, the eval harness, and the runtime agent all import from here.
"""

from __future__ import annotations

import json
import shutil
import socket
import time
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Allowlists (edit for your environment)
# ---------------------------------------------------------------------------

LOG_ALLOWLIST: dict[str, str] = {
    "gateway": "logs/gateway.log",
    "mlx-server": "logs/mlx-server.log",
    "system": "/var/log/system.log",
}

HTTP_PROBE_ALLOWLIST: set[str] = {
    "localhost",
    "127.0.0.1",
}

PROMETHEUS_URL = "http://localhost:9090"

# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------


def get_system_metrics() -> dict[str, Any]:
    """CPU, memory, load average, uptime for this host."""
    import psutil

    vm = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory_used_gb": round(vm.used / 1e9, 2),
        "memory_total_gb": round(vm.total / 1e9, 2),
        "memory_percent": vm.percent,
        "load_avg_1m": round(psutil.getloadavg()[0], 2),
        "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 1),
    }


def check_disk(path: str = "/") -> dict[str, Any]:
    """Disk usage for a mount point."""
    usage = shutil.disk_usage(path)
    return {
        "path": path,
        "total_gb": round(usage.total / 1e9, 1),
        "used_gb": round(usage.used / 1e9, 1),
        "free_gb": round(usage.free / 1e9, 1),
        "used_percent": round(100 * usage.used / usage.total, 1),
    }


def tail_log(service: str, lines: int = 20) -> dict[str, Any]:
    """Tail an allowlisted service log."""
    if service not in LOG_ALLOWLIST:
        return {"error": f"unknown service '{service}'", "allowed": sorted(LOG_ALLOWLIST)}
    path = Path(LOG_ALLOWLIST[service])
    if not path.exists():
        return {"error": f"log file not found: {path}"}
    lines = max(1, min(int(lines), 200))
    content = path.read_text(errors="replace").splitlines()[-lines:]
    return {"service": service, "lines": content}


def http_probe(url: str) -> dict[str, Any]:
    """Probe an allowlisted HTTP endpoint; return status and latency."""
    from urllib.parse import urlparse

    import requests

    host = urlparse(url).hostname or ""
    if host not in HTTP_PROBE_ALLOWLIST:
        return {"error": f"host '{host}' not in allowlist", "allowed": sorted(HTTP_PROBE_ALLOWLIST)}
    start = time.monotonic()
    try:
        resp = requests.get(url, timeout=5)
        return {
            "url": url,
            "status_code": resp.status_code,
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
            "ok": resp.ok,
        }
    except requests.RequestException as exc:
        return {"url": url, "error": type(exc).__name__, "ok": False}


def dns_lookup(hostname: str) -> dict[str, Any]:
    """Resolve a hostname to IP addresses."""
    try:
        _, _, addrs = socket.gethostbyname_ex(hostname)
        return {"hostname": hostname, "addresses": addrs}
    except socket.gaierror as exc:
        return {"hostname": hostname, "error": str(exc)}


def list_top_processes(n: int = 5, sort_by: str = "memory") -> dict[str, Any]:
    """Top processes by memory or CPU."""
    import psutil

    n = max(1, min(int(n), 20))
    key = "memory_percent" if sort_by == "memory" else "cpu_percent"
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"]):
        try:
            procs.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda x: x.get(key) or 0, reverse=True)
    return {
        "sort_by": sort_by,
        "processes": [
            {
                "pid": p["pid"],
                "name": p["name"],
                "memory_percent": round(p.get("memory_percent") or 0, 1),
                "cpu_percent": round(p.get("cpu_percent") or 0, 1),
            }
            for p in procs[:n]
        ],
    }


def query_prometheus(query: str) -> dict[str, Any]:
    """Run an instant PromQL query against the local Prometheus."""
    import requests

    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query", params={"query": query}, timeout=5
        )
        data = resp.json()
        if data.get("status") != "success":
            return {"query": query, "error": data.get("error", "query failed")}
        results = data["data"]["result"][:10]
        return {
            "query": query,
            "results": [
                {"metric": r.get("metric", {}), "value": r.get("value", [None, None])[1]}
                for r in results
            ],
        }
    except requests.RequestException as exc:
        return {"query": query, "error": type(exc).__name__}


# ---------------------------------------------------------------------------
# Registry: OpenAI-style function specs + implementations
# ---------------------------------------------------------------------------

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_system_metrics",
            "description": "Get current CPU, memory, load average, and uptime for this host.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_disk",
            "description": "Get disk usage (total/used/free/percent) for a mount point.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Mount point, e.g. '/'"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tail_log",
            "description": "Return the last N lines of an allowlisted service log.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "enum": sorted(LOG_ALLOWLIST),
                        "description": "Which service log to read",
                    },
                    "lines": {"type": "integer", "description": "Number of lines (1-200)"},
                },
                "required": ["service", "lines"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "http_probe",
            "description": "HTTP GET an allowlisted endpoint and report status code and latency.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to probe"}
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dns_lookup",
            "description": "Resolve a hostname to its IP addresses.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hostname": {"type": "string", "description": "Hostname to resolve"}
                },
                "required": ["hostname"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_top_processes",
            "description": "List the top N processes by memory or CPU usage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "How many processes (1-20)"},
                    "sort_by": {"type": "string", "enum": ["memory", "cpu"]},
                },
                "required": ["n", "sort_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_prometheus",
            "description": "Run an instant PromQL query against the local Prometheus server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "PromQL expression"}
                },
                "required": ["query"],
            },
        },
    },
]

TOOL_IMPLS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_system_metrics": get_system_metrics,
    "check_disk": check_disk,
    "tail_log": tail_log,
    "http_probe": http_probe,
    "dns_lookup": dns_lookup,
    "list_top_processes": list_top_processes,
    "query_prometheus": query_prometheus,
}

TOOL_NAMES = set(TOOL_IMPLS)


def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Execute a tool by name and return a JSON string result."""
    if name not in TOOL_IMPLS:
        return json.dumps({"error": f"unknown tool '{name}'", "allowed": sorted(TOOL_NAMES)})
    try:
        return json.dumps(TOOL_IMPLS[name](**arguments))
    except TypeError as exc:
        return json.dumps({"error": f"bad arguments: {exc}"})
    except Exception as exc:  # noqa: BLE001 — tool errors go back to the model
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
