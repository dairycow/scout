"""Statusline plugin: slot store, one dim line per completed turn."""

import os

import pytest

from scout.host import boot

FAKE = '''
class FakeClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.replies = []
        self.i = 0
    def complete(self, system, messages, tools, on_text=None, on_usage=None):
        if not self.replies:
            return {"role": "assistant",
                    "content": [{"type": "text", "text": "ok"}]}
        reply = self.replies[min(self.i, len(self.replies) - 1)]
        self.i += 1
        return reply

def scout(api):
    api.provider("fake", lambda cfg: FakeClient(cfg))
    api.config({"provider": "fake", "model": "fake-1"})
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


def _assistant(content):
    return {"role": "assistant", "content": content}


def test_one_status_line_per_completed_turn(capsys, rt):
    rt.agent.client.replies = [
        _assistant([{"type": "tool_use", "id": "1", "name": "bash", "input": {}}]),
        _assistant([{"type": "text", "text": "done"}]),
    ]
    rt.agent.run("hello")
    out, err = capsys.readouterr()
    lines = [ln for ln in out.splitlines() if ln.startswith("model=")]
    assert len(lines) == 1
    assert lines[0].startswith("model=fake-1 turns=2 msg=1")
    assert err == ""


def test_segments_from_session_start(capsys, rt):
    rt.agent.client.replies = [
        _assistant([{"type": "text", "text": "hi"}]),
    ]
    rt.agent.run("hi")
    out, _ = capsys.readouterr()
    line = [ln for ln in out.splitlines() if "turns=" in ln][0]
    assert line.startswith("model=")
    assert "turns=1 msg=1" in line
    assert "\x1b[" not in line  # not a tty -> no ANSI


def test_clear_reseeds_slots(capsys, rt):
    rt.agent.client.replies = [_assistant([{"type": "text", "text": "hi"}])]
    rt.agent.run("hi")
    capsys.readouterr()
    rt.bus.emit("session.start", cwd="/x", model="m2", pid="1",
                repository="", branch="")  # /clear path
    rt.agent.client.replies = [_assistant([{"type": "text", "text": "hi"}])]
    rt.agent.run("again")
    out, _ = capsys.readouterr()
    line = [ln for ln in out.splitlines() if "turns=" in ln][0]
    assert line.startswith("model=m2")
    assert "turns=1 msg=1" in line


def test_stderr_flip_keeps_stdout_clean(capsys, rt):
    rt.bus.emit("display.stderr")
    rt.agent.client.replies = [_assistant([{"type": "text", "text": "hi"}])]
    rt.agent.run("hi")
    out, err = capsys.readouterr()
    assert out == ""
    assert any("model=fake-1" in ln and "turns=1" in ln for ln in err.splitlines())


def test_streamed_answer_gets_leading_newline(capsys, rt):
    streamed = {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}

    def complete(system, messages, tools, on_text=None, on_usage=None):
        if on_text:
            on_text("hi")  # streamed; cursor left mid-line
        return streamed

    rt.agent.client.complete = complete
    rt.agent.run("hi", on_text=lambda d: print(d, end=""))
    out, _ = capsys.readouterr()
    assert "hi\nmodel=" in out  # newline inserted before the status line


def test_newline_omitted_after_trailing_newline(capsys, rt):
    streamed = {"role": "assistant", "content": [{"type": "text", "text": "hi\n"}]}

    def complete(system, messages, tools, on_text=None, on_usage=None):
        if on_text:
            on_text("hi\n")  # answer already ended the line
        return streamed

    rt.agent.client.complete = complete
    rt.agent.run("hi", on_text=lambda d: print(d, end=""))
    out, _ = capsys.readouterr()
    assert "hi\nmodel=" in out
    assert "hi\n\nmodel=" not in out  # no doubled blank line
