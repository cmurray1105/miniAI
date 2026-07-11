#!/usr/bin/env python3
"""Behavioral eval harness: measures what the fine-tune actually changed.

Perplexity tells you almost nothing about whether an agent works. This harness
scores concrete, binary behaviors against data/eval_cases.jsonl:

  tool_selection   — did it call the right tool (or correctly call none)?
  json_validity    — do the tool arguments parse as JSON?
  schema_validity  — do the arguments satisfy the tool's JSON schema?
  args_exact       — do the arguments match the expected values exactly?
  format_adherence — do no-tool answers follow the triage contract
                     (Finding/Assessment/Next step)?

Run against a live mlx_lm.server (OpenAI-compatible):

  # baseline (server started WITHOUT --adapter-path)
  python eval/run_eval.py --label base

  # fine-tuned (server started WITH --adapter-path adapters/incident-copilot-v1)
  python eval/run_eval.py --label tuned

  # side-by-side report
  python eval/run_eval.py --compare eval/results-base.json eval/results-tuned.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.prompts import SYSTEM_PROMPT  # noqa: E402

TOOL_CALL_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
TRIAGE_FORMAT = re.compile(
    r"Finding:\s*\S.*\n+Assessment:\s*\S.*\n+Next step:\s*\S", re.IGNORECASE
)


def extract_tool_call(message: dict) -> tuple[str, str] | None:
    """Return (name, raw_arguments_json) from either native tool_calls or
    <tool_call> tags in content. None if no call was made."""
    calls = message.get("tool_calls") or []
    if calls:
        fn = calls[0].get("function", {})
        args = fn.get("arguments", "")
        if isinstance(args, dict):
            args = json.dumps(args)
        return fn.get("name", ""), args
    content = message.get("content") or ""
    m = TOOL_CALL_TAG.search(content)
    if m:
        try:
            obj = json.loads(m.group(1))
            return obj.get("name", ""), json.dumps(obj.get("arguments", {}))
        except json.JSONDecodeError:
            return "", m.group(1)
    return None


def validate_schema(args: dict, spec: dict) -> bool:
    """Minimal JSON-schema check: required keys, primitive types, enums."""
    params = spec["function"]["parameters"]
    props, required = params.get("properties", {}), params.get("required", [])
    if any(k not in args for k in required):
        return False
    typemap = {"string": str, "integer": int, "number": (int, float), "boolean": bool}
    for key, val in args.items():
        if key not in props:
            return False
        prop = props[key]
        expected = typemap.get(prop.get("type"))
        if expected and not isinstance(val, expected):
            return False
        if "enum" in prop and val not in prop["enum"]:
            return False
    return True


def score_case(case: dict, message: dict) -> dict:
    call = extract_tool_call(message)
    expected = case["expected_tool"]
    s = {"tool_selection": False, "json_validity": None, "schema_validity": None,
         "args_exact": None, "format_adherence": None}

    if expected is None:
        s["tool_selection"] = call is None
        content = message.get("content") or ""
        s["format_adherence"] = bool(TRIAGE_FORMAT.search(content))
        return s

    if call is None:
        return s
    name, raw_args = call
    s["tool_selection"] = name == expected
    try:
        args = json.loads(raw_args) if raw_args else {}
        s["json_validity"] = True
    except json.JSONDecodeError:
        s["json_validity"] = False
        return s
    spec = next((t for t in case["tools"] if t["function"]["name"] == name), None)
    if spec:
        s["schema_validity"] = validate_schema(args, spec)
    if s["tool_selection"]:
        s["args_exact"] = args == case["expected_args"]
    return s


def run(args: argparse.Namespace) -> None:
    cases = [json.loads(line) for line in open(args.cases)]
    if args.limit:
        cases = cases[: args.limit]

    results, t0 = [], time.monotonic()
    for i, case in enumerate(cases):
        payload = {
            "model": "default",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": case["user"]},
            ],
            "tools": case["tools"],
            "max_tokens": 400,
            "temperature": 0.0,
        }
        try:
            resp = requests.post(f"{args.server}/v1/chat/completions", json=payload, timeout=180)
            resp.raise_for_status()
            message = resp.json()["choices"][0]["message"]
        except (requests.RequestException, KeyError, IndexError) as exc:
            print(f"  case {i}: request failed ({exc})", file=sys.stderr)
            message = {"content": ""}
        results.append({"case": case["user"], "expected": case["expected_tool"],
                        "scores": score_case(case, message)})
        done = i + 1
        rate = done / (time.monotonic() - t0)
        print(f"\r{done}/{len(cases)} cases  ({rate:.1f}/s)", end="", flush=True)
    print()

    summary = summarize(results)
    out = Path(args.out or f"eval/results-{args.label}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"label": args.label, "summary": summary,
                               "results": results}, indent=2))
    print(f"\n== {args.label} ==")
    print_summary(summary)
    print(f"\nSaved {out}")


def summarize(results: list[dict]) -> dict:
    metrics: dict[str, list[bool]] = {}
    for r in results:
        for k, v in r["scores"].items():
            if v is not None:
                metrics.setdefault(k, []).append(v)
    return {k: {"rate": round(100 * sum(v) / len(v), 1), "n": len(v)}
            for k, v in metrics.items()}


def print_summary(summary: dict, other: dict | None = None) -> None:
    width = max(len(k) for k in summary)
    for k, v in summary.items():
        line = f"  {k:<{width}}  {v['rate']:>5.1f}%  (n={v['n']})"
        if other and k in other:
            delta = v["rate"] - other[k]["rate"]
            line += f"   {'+' if delta >= 0 else ''}{delta:.1f} pts vs base"
        print(line)


def compare(path_a: str, path_b: str) -> None:
    a, b = json.loads(Path(path_a).read_text()), json.loads(Path(path_b).read_text())
    print(f"\n== {b['label']} vs {a['label']} ==")
    print_summary(b["summary"], a["summary"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://localhost:8080")
    parser.add_argument("--cases", default="data/eval_cases.jsonl")
    parser.add_argument("--label", default="run")
    parser.add_argument("--out", default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--compare", nargs=2, metavar=("BASE_JSON", "TUNED_JSON"))
    ns = parser.parse_args()
    if ns.compare:
        compare(*ns.compare)
    else:
        run(ns)
