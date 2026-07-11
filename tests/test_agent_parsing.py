"""Parsing/scoring unit tests for the agent loop and eval harness."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.agent import _extract_tool_call  # noqa: E402
from agent.tools import execute_tool  # noqa: E402
from eval.run_eval import TRIAGE_FORMAT, extract_tool_call, validate_schema  # noqa: E402

DISK_SPEC = {
    "function": {
        "name": "check_disk",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    }
}


def test_native_tool_call_parsed():
    msg = {"tool_calls": [{"function": {"name": "check_disk",
                                        "arguments": '{"path": "/"}'}}]}
    assert _extract_tool_call(msg) == ("check_disk", {"path": "/"})


def test_qwen_tag_tool_call_parsed():
    msg = {"content": 'Let me check.\n<tool_call>\n'
                      '{"name": "check_disk", "arguments": {"path": "/"}}\n'
                      '</tool_call>'}
    assert _extract_tool_call(msg) == ("check_disk", {"path": "/"})
    assert extract_tool_call(msg)[0] == "check_disk"


def test_plain_answer_is_not_a_tool_call():
    assert _extract_tool_call({"content": "Finding: all good."}) is None


def test_malformed_json_handled():
    msg = {"content": "<tool_call>{not json}</tool_call>"}
    assert _extract_tool_call(msg) is None


def test_schema_validation():
    assert validate_schema({"path": "/"}, DISK_SPEC)
    assert not validate_schema({}, DISK_SPEC)                  # missing required
    assert not validate_schema({"path": 5}, DISK_SPEC)         # wrong type
    assert not validate_schema({"path": "/", "x": 1}, DISK_SPEC)  # unknown key


def test_triage_format_regex():
    good = "Finding: disk 91% full.\nAssessment: critical.\nNext step: clean up."
    assert TRIAGE_FORMAT.search(good)
    assert not TRIAGE_FORMAT.search("Sure! The disk looks pretty full to me.")


def test_unknown_tool_rejected():
    out = execute_tool("rm_rf_slash", {})
    assert "unknown tool" in out


def test_tool_allowlist_enforced():
    out = execute_tool("tail_log", {"service": "/etc/passwd", "lines": 5})
    assert "unknown service" in out
