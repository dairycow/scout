"""CLI: --version, headless -p, -c resume miss, REPL dispatch."""

import os

import pytest

from scout.cli import main

FAKE = '''
class FakeClient:
    def __init__(self, cfg):
        self.cfg = cfg
    def complete(self, system, messages, tools, on_text=None, on_usage=None):
        if on_text:
            on_text("hello")
        return {"role": "assistant", "content": [{"type": "text", "text": "hello"}]}

def scout(api):
    api.provider("fake", lambda cfg: FakeClient(cfg))
    api.config({"provider": "fake"})
'''

FAKE_TOOLS = '''
from scout.tools import Tool

class FakeClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.n = 0
    def complete(self, system, messages, tools, on_text=None, on_usage=None):
        self.n += 1
        if self.n == 1:
            return {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "ping", "input": {"z": 1}},
            ]}
        if on_text:
            on_text("done")
        return {"role": "assistant", "content": [{"type": "text", "text": "done"}]}

def scout(api):
    api.provider("fake", lambda cfg: FakeClient(cfg))
    api.config({"provider": "fake"})
    api.tool(Tool("ping", "ping", {"type": "object"}, lambda a, c: "pong"))
'''


def write_plugin(home, source, name="fake.py"):
    d = home / ".agents" / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(source)


@pytest.fixture
def iso(tmp_path, monkeypatch):
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    home.mkdir()
    proj.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for key in [k for k in os.environ if k.startswith("SCOUT_") or k.endswith("_API_KEY")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(proj)
    return home, proj


def test_version_exits_0(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "scout" in capsys.readouterr().out


def test_headless_no_provider_key(iso, capsys):
    assert main(["-p", "hi"]) == 1
    err = capsys.readouterr().err
    assert "scout:" in err
    assert "no API key" in err


def test_headless_happy_path(iso, capsys):
    home, proj = iso
    write_plugin(home, FAKE)
    assert main(["-p", "hi"]) == 0
    out, err = capsys.readouterr()
    assert "hello" in out
    assert out.endswith("\n")


def test_headless_tool_roundtrip_display_on_stderr(iso, capsys):
    home, proj = iso
    write_plugin(home, FAKE_TOOLS)
    assert main(["-p", "do it"]) == 0
    out, err = capsys.readouterr()
    assert "done" in out
    assert "[ping]" in err
    assert "pong" in err
    assert "[ping]" not in out


def test_continue_with_no_store(iso, capsys):
    home, proj = iso
    write_plugin(home, FAKE)
    assert main(["-c"]) == 1
    err = capsys.readouterr().err
    assert "no previous session found" in err


def test_repl_banner_help_unknown_exit(iso, capsys, monkeypatch):
    home, proj = iso
    write_plugin(home, FAKE)
    lines = iter(["hello", "/help", "/bogus", "/exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    assert main([]) == 0
    out, err = capsys.readouterr()
    assert "scout " in out
    assert "(session " in out
    assert "/help for commands, Ctrl-D to exit" in out
    assert "hello" in out
    assert "/fork [n]" in out
    assert "/exit" in out
    assert "unknown command /bogus" in out


def test_repl_clear_switches_session_id(iso, capsys, monkeypatch):
    home, proj = iso
    write_plugin(home, FAKE)
    captured = {}
    import scout.cli as cli

    real = cli.boot

    def wrapping(cwd, cfg):
        rt = real(cwd, cfg)
        captured["rt"] = rt
        captured["id"] = rt.session.id
        return rt

    monkeypatch.setattr(cli, "boot", wrapping)
    lines = iter(["/clear", "/exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    assert main([]) == 0
    new_id = captured["rt"].agent.session.id
    assert new_id != captured["id"]
    assert new_id[:8] != captured["id"][:8]
