"""Dataset invariants — these run in CI on every push.

If the dataset generator drifts (bad JSON, schema-invalid tool calls,
train/test leakage), training silently degrades. Catch it before it costs
a two-hour training run.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.tools import TOOL_NAMES, TOOL_SPECS  # noqa: E402
from eval.run_eval import validate_schema  # noqa: E402


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    subprocess.run(
        [sys.executable, str(ROOT / "data/generate_dataset.py"), "--out", str(out)],
        check=True, capture_output=True,
    )
    return {
        f: [json.loads(line) for line in (out / f"{f}.jsonl").open()]
        for f in ("train", "valid", "test", "eval_cases")
    }


def test_split_sizes(dataset):
    assert len(dataset["train"]) >= 300
    assert len(dataset["valid"]) >= 20
    assert len(dataset["test"]) >= 20


def test_deterministic(tmp_path):
    """Same seed -> byte-identical dataset (reproducibility claim in README)."""
    outs = []
    for sub in ("a", "b"):
        d = tmp_path / sub
        subprocess.run(
            [sys.executable, str(ROOT / "data/generate_dataset.py"), "--out", str(d)],
            check=True, capture_output=True,
        )
        outs.append((d / "train.jsonl").read_bytes())
    assert outs[0] == outs[1]


def test_every_tool_call_is_schema_valid(dataset):
    for split in ("train", "valid", "test"):
        for row in dataset[split]:
            specs = {t["function"]["name"]: t for t in row["tools"]}
            for msg in row["messages"]:
                for call in msg.get("tool_calls", []) or []:
                    fn = call["function"]
                    assert fn["name"] in TOOL_NAMES
                    assert fn["name"] in specs, "target tool must be in offered toolset"
                    args = fn["arguments"]
                    assert isinstance(args, dict)  # Qwen chat template needs a mapping
                    assert validate_schema(args, specs[fn["name"]])


def test_no_train_test_leakage(dataset):
    def keys(rows):
        return {json.dumps(r["messages"][1]["content"]) + json.dumps(
            [m.get("tool_calls") for m in r["messages"]], default=str) for r in rows}
    assert not (keys(dataset["train"]) & keys(dataset["test"]))


def test_tools_key_on_every_row(dataset):
    """mlx-lm infers dataset format; a row missing 'tools' would flip it."""
    for split in ("train", "valid", "test"):
        for row in dataset[split]:
            assert row["tools"], "every row must carry a toolset"
            assert row["messages"][0]["role"] == "system"


def test_specs_match_registry():
    names = {s["function"]["name"] for s in TOOL_SPECS}
    assert names == TOOL_NAMES
