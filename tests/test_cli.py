"""CLI-level tests: arg parsing and error paths that need no API."""

import pytest

from scout.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "scout" in capsys.readouterr().out


def test_headless_without_api_key_fails_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SCOUT_API_KEY", raising=False)
    assert main(["-p", "hello"]) == 1
    assert "no API key" in capsys.readouterr().err
