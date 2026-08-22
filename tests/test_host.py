"""Tests for host.boot: plugin loading, config layering, Runtime shape."""

import os

import pytest

from scout.builtin import MANIFEST
from scout.bus import Bus
from scout.errors import ScoutError
from scout.host import boot, Runtime

FAKE = '''
from scout.tools import Tool

class FakeClient:
    def __init__(self, cfg):
        self.cfg = cfg
    def complete(self, system, messages, tools, on_text=None):
        return {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}

def scout(api):
    api.provider("fake", lambda cfg: FakeClient(cfg))
    api.tool(Tool("echo", "from-fake", {"type": "object"}, lambda a, c: "from-fake"))
    api.prompt("plugin paragraph")
    api.config({"provider": "fake", "max_turns": 40, "model": "base"})
'''

OVERRIDE = '''
from scout.tools import Tool

def scout(api):
    api.tool(Tool("echo", "from-later", {"type": "object"}, lambda a, c: "from-later"))
'''

BAD = '''
def scout(api):
    raise RuntimeError("boom")
'''

GOOD = '''
from scout.tools import Tool

def scout(api):
    api.tool(Tool("good_tool", "from-good", {"type": "object"}, lambda a, c: "from-good"))
'''


def write_plugin(directory, name, source):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(source)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for key in [k for k in os.environ if k.startswith("SCOUT_")]:
        monkeypatch.delenv(key, raising=False)
    proj = tmp_path / "proj"
    proj.mkdir()
    write_plugin(tmp_path / ".agents" / "plugins", "fake.py", FAKE)
    return proj


def test_boot_runtime_shape_and_defaults(isolated):
    rt = boot(isolated, {"prompt": "unused", "resume": False})
    for name in ("bus", "registry", "commands", "providers", "prompts", "config",
                 "client", "session", "skills", "agent", "ctx", "plugins"):
        assert hasattr(rt, name)
    assert isinstance(rt, Runtime)
    assert rt.config["provider"] == "fake"
    assert rt.config["max_turns"] == 40
    assert rt.config["model"] == "base"
    assert "prompt" not in rt.config and "resume" not in rt.config
    assert rt.prompts == ["plugin paragraph"]
    assert "echo" in rt.registry.tools
    assert rt.providers["fake"] is not None
    assert rt.client.cfg is rt.config
    assert rt.session.messages == []
    assert isinstance(rt.session.id, str) and len(rt.session.id) == 32
    assert rt.skills == {}
    assert rt.agent.session is rt.session
    assert rt.ctx.config is rt.config


def test_cli_override_merges_over_defaults(isolated):
    rt = boot(isolated, {"provider": "fake", "model": "from-cli", "max_turns": None})
    assert rt.config["model"] == "from-cli"
    assert rt.config["max_turns"] == 40  # None dropped, default remains


def test_env_override_int_coercion(isolated, monkeypatch):
    monkeypatch.setenv("SCOUT_MAX_TURNS", "7")
    rt = boot(isolated, {})
    assert rt.config["max_turns"] == 7
    assert type(rt.config["max_turns"]) is int

    monkeypatch.setenv("SCOUT_MAX_TURNS", "seven")
    with pytest.raises(ScoutError, match="integer"):
        boot(isolated, {})


def test_plugin_loaded_events_fired(isolated):
    rt = boot(isolated, {})
    for name in ("config", "session", "providers", "tools",
                 "skills", "prompt", "display", "commands"):
        assert name in rt.plugins
    assert "fake" in rt.plugins


def test_later_plugin_tool_override_wins(isolated):
    write_plugin(isolated / ".agents" / "plugins", "override.py", OVERRIDE)
    rt = boot(isolated, {})
    assert rt.registry.tools["echo"].description == "from-later"
    output, is_error = rt.registry.dispatch("echo", {}, rt.ctx)
    assert output == "from-later" and not is_error


def test_unknown_provider(isolated):
    with pytest.raises(ScoutError, match="unknown provider"):
        boot(isolated, {"provider": "nope"})


def test_boot_emits_plugin_loaded_and_session_start(isolated, monkeypatch):
    assert MANIFEST[0] == "config"
    assert MANIFEST.index("session") < MANIFEST.index("display")
    assert MANIFEST == [
        "config", "session", "providers", "tools",
        "skills", "prompt", "display", "commands",
    ]

    events = []
    real_emit = Bus.emit

    def capturing_emit(self, type, **data):
        events.append((type, data))
        return real_emit(self, type, **data)

    monkeypatch.setattr(Bus, "emit", capturing_emit)
    boot(isolated, {})

    loaded = [(d["name"], d["source"]) for t, d in events if t == "plugin.loaded"]
    assert loaded == [(name, "builtin") for name in MANIFEST] + [("fake", "user")]

    starts = [d for t, d in events if t == "session.start"]
    assert len(starts) == 1
    for key in ("cwd", "model", "pid", "repository", "branch"):
        assert key in starts[0]
        assert isinstance(starts[0][key], str)


def test_raising_user_plugin_skipped_later_still_loads(isolated, capsys):
    user_dir = isolated.parent / ".agents" / "plugins"
    write_plugin(user_dir, "bad.py", BAD)
    write_plugin(user_dir, "good.py", GOOD)
    rt = boot(isolated, {})
    err = capsys.readouterr().err
    assert "plugin bad failed" in err
    assert "bad" not in rt.plugins
    assert "good" in rt.plugins
    assert "good_tool" in rt.registry.tools
