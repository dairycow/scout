"""Tests for session persistence."""

import json

from scout.session import Session, new_session


def test_new_session_appends_jsonl(tmp_path):
    session = new_session(tmp_path)
    assert session.path.parent == tmp_path / ".scout" / "sessions"
    session.append({"role": "user", "content": [{"type": "text", "text": "hi"}]})
    line = session.path.read_text().strip()
    assert json.loads(line)["content"][0]["text"] == "hi"


def test_load_roundtrip(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        json.dumps({"role": "user", "content": [{"type": "text", "text": "a"}]}) + "\n"
        + json.dumps({"role": "assistant", "content": [{"type": "text", "text": "b"}]}) + "\n"
    )
    session = Session.load(path)
    assert [m["role"] for m in session.messages] == ["user", "assistant"]
    session.append({"role": "user", "content": [{"type": "text", "text": "c"}]})
    assert len(Session.load(path).messages) == 3


def test_latest_picks_newest(tmp_path):
    sessions = tmp_path / ".scout" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "20260101-000000-1.jsonl").write_text('{"role": "user", "content": []}\n')
    (sessions / "20260102-000000-1.jsonl").write_text('{"role": "assistant", "content": []}\n')
    assert Session.latest(tmp_path).messages[0]["role"] == "assistant"


def test_latest_none(tmp_path):
    assert Session.latest(tmp_path) is None
