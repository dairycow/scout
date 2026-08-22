"""Tests for config precedence: defaults < user toml < project toml < env < CLI."""

import pytest

from scout.config import Config, load
from scout.errors import ScoutError


def test_defaults(tmp_path):
    cfg = load(cwd=tmp_path, user_config=tmp_path / "nope.toml")
    assert cfg.provider == "anthropic"
    assert cfg.max_turns == 40


def test_toml_layers_and_cli_override(tmp_path, monkeypatch):
    for name in list(vars(Config()).keys()):
        monkeypatch.delenv(f"SCOUT_{name.upper()}", raising=False)

    user = tmp_path / "user.toml"
    user.write_text('model = "from-user"\nmax_tokens = 100\n')
    proj = tmp_path / "cwd"
    proj.mkdir()
    (proj / "scout.toml").write_text('model = "from-project"\nprovider = "openai"\n')

    cfg = load(cwd=proj, user_config=user)
    assert cfg.model == "from-project"  # project beats user
    assert cfg.max_tokens == 100  # user layer still applies for untouched keys
    assert cfg.provider == "openai"

    cfg = load({"model": "from-cli"}, cwd=proj, user_config=user)
    assert cfg.model == "from-cli"  # cli beats everything


def test_env_between_toml_and_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_MODEL", "from-env")
    cfg = load(cwd=tmp_path, user_config=tmp_path / "nope.toml")
    assert cfg.model == "from-env"
    cfg = load({"model": "from-cli"}, cwd=tmp_path, user_config=tmp_path / "nope.toml")
    assert cfg.model == "from-cli"


def test_env_int_and_bad_int(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_MAX_TURNS", "7")
    cfg = load(cwd=tmp_path, user_config=tmp_path / "nope.toml")
    assert cfg.max_turns == 7

    monkeypatch.setenv("SCOUT_MAX_TURNS", "seven")
    with pytest.raises(ScoutError, match="integer"):
        load(cwd=tmp_path, user_config=tmp_path / "nope.toml")


def test_unknown_provider_rejected(tmp_path):
    with pytest.raises(ScoutError, match="provider"):
        load({"provider": "smokestack"}, cwd=tmp_path, user_config=tmp_path / "nope.toml")
