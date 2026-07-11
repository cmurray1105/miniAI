"""Config/secret resolution: SSM first, env fallback, defaults last."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server.config as cfg  # noqa: E402


def test_ssm_wins_for_config(monkeypatch):
    monkeypatch.setattr(cfg, "_fetch_ssm_path",
                        lambda path: {"rate-limit-per-min": "12", "require-auth": "true"})
    monkeypatch.setenv("MINIAI_RATE_LIMIT", "99")
    c = cfg.load_config()
    assert c["rate-limit-per-min"] == 12          # ssm beats env
    assert c["require-auth"] is True              # bool coercion
    assert c["max-queue-depth"] == 8              # default fills the gap


def test_env_fallback_when_ssm_unavailable(monkeypatch):
    monkeypatch.setattr(cfg, "_fetch_ssm_path", lambda path: None)
    monkeypatch.setenv("MINIAI_QUEUE_TIMEOUT", "45")
    monkeypatch.delenv("MINIAI_RATE_LIMIT", raising=False)
    c = cfg.load_config()
    assert c["queue-timeout-s"] == 45             # env fallback, typed
    assert c["rate-limit-per-min"] == 6           # default


def test_token_ssm_wins_over_env(monkeypatch):
    monkeypatch.setattr(cfg, "_fetch_ssm_param", lambda name: "ssm-token")
    monkeypatch.setenv("MINIAI_TOKEN", "dev-token")
    assert cfg.get_demo_token() == "ssm-token"


def test_token_env_fallback(monkeypatch):
    monkeypatch.setattr(cfg, "_fetch_ssm_param", lambda name: None)
    monkeypatch.setenv("MINIAI_TOKEN", "dev-token")
    assert cfg.get_demo_token() == "dev-token"


def test_token_empty_means_public_demo(monkeypatch):
    monkeypatch.setattr(cfg, "_fetch_ssm_param", lambda name: None)
    monkeypatch.delenv("MINIAI_TOKEN", raising=False)
    assert cfg.get_demo_token() == ""


def test_bool_coercion_variants():
    assert cfg._coerce("True", bool) is True
    assert cfg._coerce("1", bool) is True
    assert cfg._coerce("false", bool) is False
    assert cfg._coerce("7", int) == 7
