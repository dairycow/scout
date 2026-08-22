"""Tests for plugin loading, the api surface, and hook emission."""

from scout.plugins import emit, load_plugins, new_hooks
from scout.tools import Registry, Tool

PLUGIN = '''
from scout.tools import Tool

seen = []

def scout(api):
    api.register_tool(Tool(
        name="ping",
        description="example",
        parameters={"type": "object", "properties": {}},
        run=lambda args, ctx: "pong",
    ))
    api.on("tool_start", lambda name, args: seen.append(name))
    api.prompt("always reply in lowercase")
'''


def write_plugin(tmp_path, name, source=PLUGIN):
    plugins = tmp_path / ".agents" / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    (plugins / name).write_text(source)
    return plugins


def test_plugin_registers_tool_hook_and_prompt(tmp_path):
    write_plugin(tmp_path, "myplug.py")

    registry, hooks, prompts = Registry(), new_hooks(), []
    loaded = load_plugins(tmp_path, registry, hooks, prompts, user_dir=tmp_path / "nope")

    assert loaded == ["myplug.py"]
    assert "ping" in registry.tools
    assert registry.dispatch("ping", {}, None) == ("pong", False)
    assert len(hooks["tool_start"]) == 1
    assert prompts == ["always reply in lowercase"]


def test_emit_swallows_hook_errors():
    hooks = new_hooks()
    calls = []
    hooks["tool_start"].append(lambda name, args: (_ for _ in ()).throw(RuntimeError("boom")))
    hooks["tool_start"].append(lambda name, args: calls.append(name))
    emit(hooks, "tool_start", name="bash", args={})
    assert calls == ["bash"]


def test_broken_plugin_is_skipped(tmp_path, capsys):
    write_plugin(tmp_path, "bad.py", "raise RuntimeError('nope')\n")
    loaded = load_plugins(tmp_path, Registry(), new_hooks(), [], user_dir=tmp_path / "nope")
    assert loaded == []
    assert "bad.py failed" in capsys.readouterr().err


def test_module_without_scout_function_loads_silently(tmp_path):
    write_plugin(tmp_path, "silent.py", "X = 1\n")
    loaded = load_plugins(tmp_path, Registry(), new_hooks(), [], user_dir=tmp_path / "nope")
    assert loaded == ["silent.py"]
