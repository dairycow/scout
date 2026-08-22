"""Event store: append-only log, deterministic projector, resume, /clear /fork."""

import json
import random
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from scout.bus import Bus
from scout.builtin import session as store
from scout.builtin.session import (
    append,
    open_session,
    rebuild,
    reset,
    scout,
)
from scout.tools import Ctx


class Api:
    def __init__(self, bus):
        self.bus = bus
        self.commands = {}

    def on(self, event, fn):
        self.bus.on(event, fn)

    def command(self, name, fn):
        self.commands[name] = fn

    def emit(self, type, **data):
        self.bus.emit(type, **data)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    reset()
    yield tmp_path
    reset()


def db_path():
    return Path.home() / ".scout" / "store.db"


def query(sql, params=(), path=None):
    conn = sqlite3.connect(path or db_path())
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def msg(text, role="user"):
    return {"role": role, "content": [{"type": "text", "text": text}]}


def agent_for(bus, cwd, session, model="m"):
    return SimpleNamespace(
        bus=bus,
        ctx=Ctx(cwd=Path(cwd), config={"model": model}),
        session=session,
    )


def boot(cwd, start=True):
    bus = Bus()
    api = Api(bus)
    scout(api)
    session = open_session(cwd, {}, False)
    if start:
        bus.emit(
            "session.start",
            cwd=str(cwd),
            model="m",
            pid="1",
            repository="",
            branch="",
        )
    return bus, api, agent_for(bus, cwd, session)


def messages_rows(path=None):
    return query(
        "SELECT session, n, seq, message FROM messages ORDER BY session, n",
        path=path,
    )


def test_projector_determinism(tmp_path, monkeypatch):
    for seed in range(20):
        monkeypatch.setenv("HOME", str(tmp_path / f"s{seed}"))
        reset()
        rng = random.Random(seed)
        cwd = Path.home() / "proj"
        cwd.mkdir(parents=True)
        bus, api, agent = boot(cwd)
        ids = [agent.session.id]
        for i in range(3):
            bus.emit("message.user", message=msg(f"warm-{i}-café"))
        for op_i in range(50):
            op = rng.choices(
                ["user", "assistant", "fork", "clear", "switch"],
                weights=[5, 5, 2, 1, 2],
            )[0]
            if op == "user":
                bus.emit("message.user", message=msg(f"u{seed}-{op_i}"))
            elif op == "assistant":
                bus.emit(
                    "message.assistant",
                    message=msg(f"a{seed}-{op_i}", role="assistant"),
                    turn=rng.randint(1, 9),
                )
            elif op == "fork":
                n = query(
                    "SELECT COUNT(*) FROM messages WHERE session = ?",
                    (store._active,),
                )[0][0]
                at_n = rng.randint(0, n) if n else 0
                api.commands["/fork"](agent, str(at_n))
                ids.append(agent.session.id)
            elif op == "clear":
                api.commands["/clear"](agent, "")
                ids.append(agent.session.id)
            else:
                store._active = rng.choice(ids)
        snap = messages_rows()
        assert snap  # warm-up messages always land
        rebuild(db_path())
        assert messages_rows() == snap
        reset()


def test_store_append_only(home):
    scout(Api(Bus()))
    seq = append("-", "plugin.loaded", {"name": "x", "source": "builtin"})
    assert seq >= 1
    src = Path(store.__file__).read_text()
    assert src.count("INSERT INTO events") == 1
    start = src.index("def append")
    nxt = src.index("\ndef ", start + 1)
    assert "INSERT INTO events" in src[start:nxt]
    conn = sqlite3.connect(db_path())
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE events SET type = 'nope'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM events")
    finally:
        conn.close()


def test_resume_latest_by_cwd(home):
    a, b, c = home / "a", home / "b", home / "c"
    for p in (a, b, c):
        p.mkdir()
    bus, api, _ = boot(a)
    s1 = open_session(a, {}, False)
    bus.emit("session.start", cwd=str(a), model="m", pid="1", repository="", branch="")
    bus.emit("message.user", message=msg("one"))

    s2 = open_session(b, {}, False)
    bus.emit("session.start", cwd=str(b), model="m", pid="1", repository="", branch="")
    bus.emit("message.user", message=msg("decoy"))

    s3 = open_session(a, {}, False)
    bus.emit("session.start", cwd=str(a), model="m", pid="1", repository="", branch="")
    bus.emit("message.user", message=msg("two"))
    bus.emit("message.user", message=msg("three"))

    got = open_session(a, {}, True)
    assert got.id == s3.id
    assert [m["content"][0]["text"] for m in got.messages] == ["two", "three"]

    # host always emits session.start after open_session, attributed to the resumed id
    bus.emit("session.start", cwd=str(a), model="m", pid="1", repository="", branch="")
    got = open_session(a, {}, True)
    assert got.id == s3.id
    assert [m["content"][0]["text"] for m in got.messages] == ["two", "three"]

    agent = agent_for(bus, a, got)
    api.commands["/fork"](agent, "1")
    fork_id = agent.session.id
    assert [m["content"][0]["text"] for m in agent.session.messages] == ["two"]

    got = open_session(a, {}, True)
    assert got.id == fork_id
    assert len(got.messages) == 1

    decoy = open_session(b, {}, True)
    assert decoy.id == s2.id
    assert decoy.messages[0]["content"][0]["text"] == "decoy"

    fresh = open_session(c, {}, True)
    assert fresh.id not in {s1.id, s2.id, s3.id, fork_id}
    assert fresh.messages == []
    assert len(fresh.id) == 32


def test_fork_prefix(home):
    cwd = home / "proj"
    cwd.mkdir()
    bus, api, agent = boot(cwd)
    parent_id = agent.session.id
    for text in ("m1", "m2", "m3"):
        bus.emit("message.user", message=msg(text))
    before = query(
        "SELECT n, seq, message FROM messages WHERE session = ? ORDER BY n",
        (parent_id,),
    )
    assert len(before) == 3

    api.commands["/fork"](agent, "2")
    child = agent.session
    assert child.id != parent_id
    assert [m["content"][0]["text"] for m in child.messages] == ["m1", "m2"]
    child_rows = query(
        "SELECT n, seq, message FROM messages WHERE session = ? ORDER BY n",
        (child.id,),
    )
    assert [n for n, _, _ in child_rows] == [1, 2]
    assert [(s, m) for _, s, m in child_rows] == [(s, m) for _, s, m in before[:2]]
    assert query(
        "SELECT n, seq, message FROM messages WHERE session = ? ORDER BY n",
        (parent_id,),
    ) == before

    bus.emit("message.user", message=msg("fork-only"))
    assert [m["content"][0]["text"] for m in agent.session.messages] == [
        "m1", "m2", "fork-only",
    ]
    assert query(
        "SELECT n, seq, message FROM messages WHERE session = ? ORDER BY n",
        (parent_id,),
    ) == before

    api.commands["/fork"](agent, "")
    full = agent.session
    assert [m["content"][0]["text"] for m in full.messages] == [
        "m1", "m2", "fork-only",
    ]
    assert query(
        "SELECT n, seq, message FROM messages WHERE session = ? ORDER BY n",
        (parent_id,),
    ) == before


def test_projection_current_after_emit(home):
    cwd = home / "proj"
    cwd.mkdir()
    bus = Bus()
    scout(Api(bus))
    view = open_session(cwd, {}, False)
    live = view.messages
    payload = msg("hi")
    bus.emit("message.user", message=payload)
    assert view.messages is live
    assert view.messages == [payload]
    assert view.messages[0] is payload
    rows = query("SELECT n, message FROM messages WHERE session = ?", (view.id,))
    assert len(rows) == 1
    assert rows[0][0] == 1
    assert json.loads(rows[0][1]) == payload


def test_first_event_invariant(home):
    cwd = home / "proj"
    cwd.mkdir()
    bus, api, agent = boot(cwd)
    old = agent.session.id
    bus.emit("message.user", message=msg("before-clear"))
    api.commands["/clear"](agent, "")
    new = agent.session.id
    assert new != old
    assert agent.session.messages == []
    assert agent.session is store._view
    bus.emit("message.user", message=msg("after-clear"))
    assert [m["content"][0]["text"] for m in agent.session.messages] == ["after-clear"]

    api.commands["/fork"](agent, "")
    fork_id = agent.session.id

    for sid, in query("SELECT DISTINCT session FROM events"):
        if sid == "-":
            continue
        typ = query(
            "SELECT type FROM events WHERE session = ? ORDER BY seq LIMIT 1",
            (sid,),
        )[0][0]
        assert typ in ("session.start", "session.fork")
    assert query(
        "SELECT type FROM events WHERE session = ? ORDER BY seq LIMIT 1", (old,),
    )[0][0] == "session.start"
    assert query(
        "SELECT type FROM events WHERE session = ? ORDER BY seq LIMIT 1", (new,),
    )[0][0] == "session.start"
    assert query(
        "SELECT type FROM events WHERE session = ? ORDER BY seq LIMIT 1", (fork_id,),
    )[0][0] == "session.fork"


def test_malformed_message_skipped_both_paths(home):
    cwd = home / "proj"
    cwd.mkdir()
    bus, api, agent = boot(cwd)
    bus.emit("message.user", message=msg("good-before"))
    bus.emit("message.user")  # plugin payload missing `message`
    bus.emit("message.user", message=msg("good-after"))

    assert [m["content"][0]["text"] for m in agent.session.messages] == [
        "good-before", "good-after",
    ]
    events = query(
        "SELECT type, data FROM events WHERE type = 'message.user' ORDER BY seq"
    )
    assert len(events) == 3
    assert json.loads(events[1][1]) == {}
    snap = messages_rows()
    assert len(snap) == 2
    rebuild(db_path())
    assert messages_rows() == snap
    assert query(
        "SELECT type, data FROM events WHERE type = 'message.user' ORDER BY seq"
    ) == events


def test_pre_session_events_dash_rebuild_neutral(home):
    bus = Bus()
    scout(Api(bus))
    bus.emit("plugin.loaded", name="session", source="builtin")
    bus.emit("plugin.loaded", name="display", source="builtin")
    rows = query("SELECT session, type, data FROM events ORDER BY seq")
    assert [r[0] for r in rows] == ["-", "-"]
    assert [r[1] for r in rows] == ["plugin.loaded", "plugin.loaded"]
    assert json.loads(rows[0][2]) == {"name": "session", "source": "builtin"}
    assert query("SELECT COUNT(*) FROM messages")[0][0] == 0
    rebuild(db_path())
    assert query("SELECT COUNT(*) FROM messages")[0][0] == 0
    assert query("SELECT session, type FROM events ORDER BY seq") == [
        ("-", "plugin.loaded"),
        ("-", "plugin.loaded"),
    ]
