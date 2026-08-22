"""Append-only SQLite event store; message history is a projection."""

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  seq     INTEGER PRIMARY KEY,
  session TEXT  NOT NULL,
  ts      TEXT  NOT NULL,
  type    TEXT  NOT NULL,
  data    TEXT  NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  session TEXT  NOT NULL,
  n       INTEGER NOT NULL,
  seq     INTEGER NOT NULL,
  message TEXT  NOT NULL,
  PRIMARY KEY (session, n)
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
"""

_conn = None
_path = None
_active = "-"
_view = None


class Session:
    def __init__(self, id: str, messages: list | None = None):
        self.id = id
        self.messages: list[dict] = messages if messages is not None else []


def reset() -> None:
    global _conn, _path, _active, _view
    if _conn is not None:
        _conn.close()
        _conn = None
    _path, _active, _view = None, "-", None


def _store_path() -> Path:
    return Path.home() / ".scout" / "store.db"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _db() -> sqlite3.Connection:
    global _conn, _path
    if _conn is None:
        _path = _store_path()
        _conn = _connect(_path)
    return _conn


def append(session_id: str, type: str, data: dict) -> int:
    conn = _db()
    cur = conn.execute(
        "INSERT INTO events (session, ts, type, data) VALUES (?, ?, ?, ?)",
        (session_id, datetime.now(timezone.utc).isoformat(), type,
         json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()
    return cur.lastrowid


def _project(conn, session_id, seq, type, data, live=True) -> None:
    try:
        if type in ("message.user", "message.assistant"):
            n = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session = ?", (session_id,),
            ).fetchone()[0] + 1
            conn.execute(
                "INSERT INTO messages (session, n, seq, message) VALUES (?, ?, ?, ?)",
                (session_id, n, seq, json.dumps(data["message"], ensure_ascii=False)),
            )
            if live and _view is not None and _view.id == session_id:
                _view.messages.append(data["message"])
        elif type == "session.fork":
            rows = conn.execute(
                "SELECT seq, message FROM messages WHERE session = ? AND n <= ? ORDER BY n",
                (data["from"], data["at_n"]),
            ).fetchall()
            for n, (orig, message) in enumerate(rows, start=1):
                conn.execute(
                    "INSERT INTO messages (session, n, seq, message) VALUES (?, ?, ?, ?)",
                    (session_id, n, orig, message),
                )
            if live and _view is not None and _view.id == session_id:
                _view.messages[:] = [json.loads(m) for _, m in rows]
    except Exception as e:  # noqa: BLE001 — skip; events row stays append-only
        print(f"scout: projector skipped {type} seq={seq}: {e}", file=sys.stderr)


def _on_event(type, **data) -> None:
    seq = append(_active, type, data)
    conn = _db()
    _project(conn, _active, seq, type, data)
    conn.commit()


def _load(session_id: str) -> Session:
    rows = _db().execute(
        "SELECT message FROM messages WHERE session = ? ORDER BY n", (session_id,),
    ).fetchall()
    return Session(session_id, [json.loads(r[0]) for r in rows])


def _meta(agent) -> dict:
    return {
        "cwd": str(agent.ctx.cwd),
        "model": agent.ctx.config.get("model", ""),
        "pid": str(os.getpid()),
    }


def _clear(agent, rest) -> None:
    global _active, _view
    _active = uuid.uuid4().hex
    _view = Session(_active, [])
    agent.bus.emit("session.start", **_meta(agent), repository="", branch="")
    agent.session = _view


def _fork(agent, rest) -> None:
    global _active, _view
    parent, rest = _active, (rest or "").strip()
    at_n = int(rest) if rest else len(_view.messages) if _view else 0
    _active = uuid.uuid4().hex
    _view = Session(_active, [])
    agent.bus.emit("session.fork", **{"from": parent, "at_n": at_n, **_meta(agent)})
    agent.session = _view


def open_session(cwd, config, resume: bool) -> Session:
    global _active, _view
    conn = _db()
    sid = None
    if resume:
        row = conn.execute(
            "SELECT session FROM events "
            "WHERE type IN ('session.start', 'session.fork') "
            "AND json_extract(data, '$.cwd') = ? "
            "ORDER BY seq DESC LIMIT 1",
            (str(cwd),),
        ).fetchone()
        if row:
            sid = row[0]
    if sid is None:
        sid = uuid.uuid4().hex
        _view = Session(sid, [])
    else:
        _view = _load(sid)
    _active = sid
    return _view


def rebuild(store_or_path) -> None:
    if isinstance(store_or_path, sqlite3.Connection):
        conn, close = store_or_path, False
    else:
        path = Path(store_or_path)
        if _conn is not None and _path is not None and path.resolve() == Path(_path).resolve():
            conn, close = _conn, False
        else:
            conn, close = _connect(path), True
    try:
        conn.execute("DROP TABLE IF EXISTS messages")
        conn.executescript(
            "CREATE TABLE messages ("
            " session TEXT NOT NULL, n INTEGER NOT NULL, seq INTEGER NOT NULL,"
            " message TEXT NOT NULL, PRIMARY KEY (session, n))"
        )
        for seq, session_id, typ, raw in conn.execute(
            "SELECT seq, session, type, data FROM events ORDER BY seq"
        ):
            _project(conn, session_id, seq, typ, json.loads(raw), live=False)
        conn.commit()
    finally:
        if close:
            conn.close()


def scout(api) -> None:
    reset()
    _db()
    api.on("*", _on_event)
    api.command("/clear", _clear)
    api.command("/fork", _fork)
