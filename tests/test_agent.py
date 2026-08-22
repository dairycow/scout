"""Tests for the agent loop, using a scripted fake client."""

import pytest

from scout.config import Config
from scout.session import Session
from scout.tools import Ctx, Registry, Tool


class FakeClient:
    """complete() pops one scripted reply; records what it was called with."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, messages, tools, on_text=None):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        reply = self.replies.pop(0)
        if on_text:
            for block in reply:
                if block["type"] == "text":
                    on_text(block["text"])
        return {"role": "assistant", "content": reply}


def make_agent(tmp_path, replies, max_turns=10):
    seen = []

    def record(args, ctx):
        seen.append(args)
        return f"ran {args['cmd']}"

    registry = Registry()
    registry.register(Tool("run", "test tool", {"type": "object"}, record))
    ctx = Ctx(cwd=tmp_path, config=Config(max_turns=max_turns), skills={})
    from scout.agent import Agent

    agent = Agent(FakeClient(replies), registry, "system prompt", Session([], None),
                  ctx, {h: [] for h in ("session_start", "tool_start", "tool_end", "message_end")})
    return agent, seen


def text(s):
    return {"type": "text", "text": s}


def call(id, args):
    return {"type": "tool_use", "id": id, "name": "run", "input": args}


def result(id, content):
    return {"type": "tool_result", "tool_use_id": id, "content": content, "is_error": False}


def test_plain_reply_runs_no_tools(tmp_path):
    agent, seen = make_agent(tmp_path, [[text("all done")]])
    streamed = []
    assert agent.run("hi", on_text=streamed.append) == "all done"
    assert seen == [] and streamed == ["all done"]


def test_tool_call_roundtrip(tmp_path):
    agent, seen = make_agent(tmp_path, [
        [call("t1", {"cmd": "ls"})],
        [text("listed the files")],
    ])
    out = agent.run("list files")
    assert out == "listed the files"
    assert seen == [{"cmd": "ls"}]
    roles = [m["role"] for m in agent.session.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    results = agent.session.messages[2]["content"]
    assert results == [result("t1", "ran ls")]
    # the second model call saw the tool result
    second_messages = agent.client.calls[1]["messages"]
    assert second_messages[2]["content"][0]["content"] == "ran ls"
    # tools schemas were passed through
    assert agent.client.calls[0]["tools"][0]["name"] == "run"


def test_tool_error_feeds_back_and_loop_continues(tmp_path):
    from scout.tools import Tool as T

    def boom(args, ctx):
        raise ValueError("kaput")

    agent, seen = make_agent(tmp_path, [
        [call("t1", {"cmd": "x"})],
        [text("recovered")],
    ])
    agent.registry.register(T("run", "test tool", {"type": "object"}, boom))
    assert agent.run("go") == "recovered"
    error_result = agent.session.messages[2]["content"][0]
    assert error_result["is_error"] is True
    assert "kaput" in error_result["content"]


def test_multiple_tool_calls_in_one_turn(tmp_path):
    agent, seen = make_agent(tmp_path, [
        [call("a", {"cmd": "1"}), call("b", {"cmd": "2"})],
        [text("done")],
    ])
    agent.run("go")
    assert seen == [{"cmd": "1"}, {"cmd": "2"}]
    results = agent.session.messages[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]


def test_max_turns_guard(tmp_path):
    agent, _ = make_agent(tmp_path, [[call(f"t{i}", {"cmd": str(i)})] for i in range(99)],
                          max_turns=3)
    out = agent.run("loop forever")
    assert "stopped after 3 turns" in out
    assert len(agent.client.calls) == 3


def test_hooks_fire(tmp_path):
    events = []
    agent, _ = make_agent(tmp_path, [
        [call("t1", {"cmd": "ls"})],
        [text("done")],
    ])
    for event in agent.hooks:
        agent.hooks[event].append(lambda **kw: events.append(kw))
    agent.run("go")
    kinds = [type(next(iter(k.values()))).__name__ for k in events]
    assert len([k for k in events if "message" in k]) == 2
    assert len([k for k in events if "name" in k and "output" in k]) == 1  # tool_end
    assert any(k.get("name") == "run" and "output" not in k for k in events)  # tool_start
