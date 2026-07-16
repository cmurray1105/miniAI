"""The miniAI agent loop.

Talks to an OpenAI-compatible model server (mlx_lm.server), executes tool
calls against the read-only tool registry, and returns the final answer plus
a full trace of every step — the trace is surfaced in the demo UI so an
engineer can see exactly what the model did, not just what it said.

Usage as a library:  run_agent("is the disk full?") -> AgentResult
Usage as a REPL:     python -m agent.agent
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import requests
from opentelemetry import trace

from .prompts import SYSTEM_PROMPT
from .tools import TOOL_SPECS, execute_tool

MODEL_SERVER = "http://localhost:8080"
MAX_STEPS = 6  # hard cap on tool-call rounds — no runaway loops
tracer = trace.get_tracer("miniai.agent")


@dataclass
class AgentResult:
    answer: str
    trace: list[dict] = field(default_factory=list)
    steps: int = 0
    total_latency_ms: float = 0.0
    completion_tokens: int = 0


def _extract_tool_call(message: dict) -> tuple[str, dict] | None:
    """Handle both native tool_calls and Qwen-style <tool_call> tags."""
    calls = message.get("tool_calls") or []
    if calls:
        fn = calls[0].get("function", {})
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args) if args else {}
            except json.JSONDecodeError:
                return None
        return fn.get("name", ""), args

    content = message.get("content") or ""
    start = content.find("<tool_call>")
    end = content.find("</tool_call>")
    if start != -1 and end != -1:
        try:
            obj = json.loads(content[start + len("<tool_call>"):end].strip())
            return obj.get("name", ""), obj.get("arguments", {})
        except json.JSONDecodeError:
            return None
    return None


def run_agent(user_message: str, server: str = MODEL_SERVER,
              history: list[dict] | None = None) -> AgentResult:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    result = AgentResult(answer="")
    t_start = time.monotonic()

    for step in range(MAX_STEPS):
        with tracer.start_as_current_span("agent.model_completion") as span:
            span.set_attribute("gen_ai.request.model", "Qwen3.5-9B-MLX-4bit")
            span.set_attribute("agent.step", step + 1)
            resp = requests.post(
                f"{server}/v1/chat/completions",
                json={"model": "mlx-community/Qwen3.5-9B-MLX-4bit", "messages": messages,
                      "tools": TOOL_SPECS, "max_tokens": 600, "temperature": 0.2},
                timeout=300,
            )
        resp.raise_for_status()
        data = resp.json()
        message = data["choices"][0]["message"]
        result.completion_tokens += data.get("usage", {}).get("completion_tokens", 0)
        result.steps = step + 1

        call = _extract_tool_call(message)
        if call is None:
            result.answer = (message.get("content") or "").strip()
            result.trace.append({"type": "answer", "content": result.answer})
            break

        name, args = call
        t_tool = time.monotonic()
        with tracer.start_as_current_span("agent.tool") as span:
            span.set_attribute("agent.tool.name", name)
            tool_output = execute_tool(name, args)
        result.trace.append({
            "type": "tool_call", "tool": name, "arguments": args,
            "result": json.loads(tool_output),
            "latency_ms": round((time.monotonic() - t_tool) * 1000, 1),
        })
        # Feed the call + result back in OpenAI message format; the server's
        # chat template renders it into what the model saw during training.
        messages.append({"role": "assistant", "tool_calls": [{
            "id": f"call_{step}", "type": "function",
            "function": {"name": name, "arguments": args},
        }]})
        messages.append({"role": "tool", "content": tool_output})
    else:
        result.answer = "Stopped: hit the tool-call limit without a final answer."
        result.trace.append({"type": "limit", "content": result.answer})

    result.total_latency_ms = round((time.monotonic() - t_start) * 1000, 1)
    return result


def main() -> None:
    print("miniAI agent REPL — ctrl-d to exit")
    while True:
        try:
            q = input("\n> ").strip()
        except EOFError:
            break
        if not q:
            continue
        res = run_agent(q)
        for t in res.trace:
            if t["type"] == "tool_call":
                print(f"  [tool] {t['tool']}({json.dumps(t['arguments'])}) "
                      f"-> {json.dumps(t['result'])[:200]}")
        print(f"\n{res.answer}")
        print(f"  ({res.steps} steps, {res.total_latency_ms} ms, "
              f"{res.completion_tokens} tokens)")


if __name__ == "__main__":
    main()
