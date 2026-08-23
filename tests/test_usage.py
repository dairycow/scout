"""Usage meter plugin: per-turn lines, session totals, stream flip."""

import os

import pytest

from scout.host import boot

FAKE = '''
class FakeClient:
    def __init__(self, cfg):
        self.cfg = cfg
    def complete(self, system, messages, tools, on_text=None, on_usage=None):
        if on_usage:
            on_usage({"input_tokens": 10, "output_tokens": 4,
                      "cache_read_input_tokens": 100,
                      "cache_creation_input_tokens": 5})
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


def test_turn_line_carries_delta_and_running_total(rt, capsys):
    rt.agent.run("one")
    rt.agent.run("two")
    lines = [ln for ln in capsys.readouterr().out.splitlines()
             if ln.startswith("tok ")]
    assert lines[0] == "tok in=10 out=4 cache_r=100 cache_w=5 session in=10 out=4"
    assert lines[1].endswith("session in=20 out=8")


def test_usage_line_flips_to_stderr_with_display(rt, capsys):
    rt.bus.emit("display.stderr")
    rt.agent.run("headless")
    out, err = capsys.readouterr()
    assert out == ""
    assert any(ln.startswith("tok in=10") for ln in err.splitlines())


def test_no_usage_command_registered(rt):
    assert "/usage" not in rt.commands


def test_totals_reset_on_session_start(rt, capsys):
    rt.agent.run("one")
    capsys.readouterr()
    rt.bus.emit("session.start")
    rt.agent.run("two")
    lines = [ln for ln in capsys.readouterr().out.splitlines()
             if ln.startswith("tok ")]
    assert lines[0].endswith("session in=10 out=4")
