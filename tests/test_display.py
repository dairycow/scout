"""Display plugin: tool.start/end lines, stdout by default, stderr after flip."""

import os

import pytest

from scout.host import boot

FAKE = '''
class FakeClient:
    def __init__(self, cfg):
        self.cfg = cfg
    def complete(self, system, messages, tools, on_text=None, on_usage=None):
        return {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}

def scout(api):
    api.provider("fake", lambda cfg: FakeClient(cfg))
    api.config({"provider": "fake"})
'''


@pytest.fixture
def rt(tmp_path, monkeypatch):
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    home.mkdir()
    proj.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for key in [k for k in os.environ if k.startswith("SCOUT_") or k.endswith("_API_KEY")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(proj)
    plug = home / ".agents" / "plugins"
    plug.mkdir(parents=True)
    (plug / "fake.py").write_text(FAKE)
    return boot(proj, {})


def test_tool_lines_go_to_stdout_by_default(capsys, rt):
    rt.bus.emit("tool.start", name="bash", args={"command": "ls"})
    rt.bus.emit("tool.end", name="bash", args={}, output="hello\nworld", is_error=False)
    out, err = capsys.readouterr()
    assert "[bash] {'command': 'ls'}" in out
    assert "[bash] hello" in out
    assert err == ""


def test_display_stderr_flips_stream(capsys, rt):
    rt.bus.emit("display.stderr")
    rt.bus.emit("tool.start", name="echo", args={"x": "y"})
    rt.bus.emit("tool.end", name="echo", args={}, output="", is_error=True)
    out, err = capsys.readouterr()
    assert out == ""
    assert "[echo] {'x': 'y'}" in err
    assert "[echo]! (no output)" in err
