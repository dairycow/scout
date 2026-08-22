"""§14 smoke as an offline end-to-end test: boot, run, fork, resume, rebuild."""

import os
import sqlite3
from pathlib import Path

import pytest

from scout.builtin.session import rebuild, reset
from scout.host import boot

FAKE = '''
class FakeClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.n = 0

    def complete(self, system, messages, tools, on_text=None):
        self.n += 1
        if self.n == 1:
            return {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "bash",
                 "input": {"command": "echo smoke"}},
            ]}
        if on_text:
            on_text("done")
        return {"role": "assistant", "content": [{"type": "text", "text": "done"}]}

def scout(api):
    api.provider("fake", lambda cfg: FakeClient(cfg))
    api.config({"fake_greeting": "hi"})
'''


def messages_rows(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT session, n, seq, message FROM messages ORDER BY session, n"
        ).fetchall()
    finally:
        conn.close()


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    home = tmp_path / "home"
    cwd = tmp_path / "proj"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for key in [k for k in os.environ if k.startswith("SCOUT_") or k.endswith("_API_KEY")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(cwd)
    reset()
    yield cwd
    reset()


def test_smoke_boot_run_fork_resume_rebuild(isolated):
    cwd = isolated
    plugin = cwd / ".agents" / "plugins" / "fake.py"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(FAKE)

    rt = boot(cwd, {"prompt": None, "resume": False, "provider": "fake"})
    assert rt.config["fake_greeting"] == "hi"
    assert rt.config["provider"] == "fake"

    answer = rt.agent.run("list the files")
    assert answer == "done"
    parent_id = rt.session.id
    prefix = list(rt.agent.session.messages)
    assert prefix  # user + tool_use + result + final

    rt.commands["/fork"](rt.agent, "")
    fork = rt.agent.session
    assert fork.id != parent_id
    assert fork.messages == prefix

    rt2 = boot(cwd, {"prompt": None, "resume": True, "provider": "fake"})
    assert rt2.session.messages
    assert rt2.session.id == fork.id
    assert rt2.session.messages == fork.messages

    store = Path.home() / ".scout" / "store.db"
    before = messages_rows(store)
    assert before
    rebuild(store)
    assert messages_rows(store) == before
