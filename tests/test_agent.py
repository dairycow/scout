"""Tests for the agent loop, using a scripted fake client."""

import time

from scout.agent import Agent
from scout.bus import Bus
from scout.tools import Ctx, Registry, Tool


class FakeClient:
    """complete() pops one scripted reply; records what it was called with."""

    def __init__(self, replies, usage=None):
        self.replies = list(replies)
        self.usage = usage
        self.calls = []

    def complete(self, system, messages, tools, on_text=None, on_usage=None):
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        if on_usage and self.usage is not None:
            on_usage(dict(self.usage))
        reply = self.replies.pop(0)
        if on_text:
            for block in reply:
                if block["type"] == "text":
                    on_text(block["text"])
        return {"role": "assistant", "content": reply}


class MemorySession:
    def __init__(self):
        self.id = "test"
        self.messages = []


def make_agent(tmp_path, replies, max_turns=10, usage=None, config=None):
    seen = []

    def record(args, ctx):
        seen.append(args)
        return f"ran {args['cmd']}"

    registry = Registry()
    registry.register(Tool("run", "test tool", {"type": "object"}, record))
    cfg = {"max_turns": max_turns}
    if config:
        cfg.update(config)
    ctx = Ctx(cwd=tmp_path, config=cfg, skills={})
    bus = Bus()
    session = MemorySession()

    def persist(message, **_):
        session.messages.append(message)

    bus.on("message.user", persist)
    bus.on("message.assistant", persist)
    agent = Agent(FakeClient(replies, usage), registry, "system prompt", session, ctx, bus)
    return agent, seen


def text(s):
    return {"type": "text", "text": s}


def call(id, args):
    return {"type": "tool_use", "id": id, "name": "run", "input": args}


def result(id, content, is_error=False):
    return {"type": "tool_result", "tool_use_id": id, "content": content, "is_error": is_error}


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
    # bus projection was current BEFORE each complete() call
    first_messages = agent.client.calls[0]["messages"]
    assert first_messages[0] == {
        "role": "user", "content": [{"type": "text", "text": "list files"}],
    }
    assert len(first_messages) == 1
    second_messages = agent.client.calls[1]["messages"]
    assert second_messages[2]["content"] == [result("t1", "ran ls")]
    assert len(second_messages) == 3
    # tools schemas were passed through
    assert agent.client.calls[0]["tools"][0]["name"] == "run"


def test_tool_error_feeds_back_and_loop_continues(tmp_path):
    def boom(args, ctx):
        raise ValueError("kaput")

    agent, seen = make_agent(tmp_path, [
        [call("t1", {"cmd": "x"})],
        [text("recovered")],
    ])
    agent.registry.register(Tool("run", "test tool", {"type": "object"}, boom))
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


def test_parallel_tool_calls_run_concurrently(tmp_path):
    def slow(args, ctx):
        time.sleep(args["seconds"])
        return f"ran {args['seconds']}"

    agent, _ = make_agent(tmp_path, [
        [call("a", {"seconds": 0.5}), call("b", {"seconds": 0.05})],
        [text("done")],
    ], config={"parallel_tools": True})
    agent.registry.register(Tool("run", "test tool", {"type": "object"}, slow))
    events = []
    agent.bus.on("*", lambda type, **data: events.append((type, data)))

    start = time.monotonic()
    agent.run("go")
    elapsed = time.monotonic() - start
    assert elapsed < 0.9  # serial would be sum=0.55; parallel is max=0.5

    # the API sees call order, always
    results = agent.session.messages[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]
    assert [r["content"] for r in results] == ["ran 0.5", "ran 0.05"]
    # tool.start in call order, tool.end in completion order
    starts = [data["args"]["seconds"] for t, data in events if t == "tool.start"]
    ends = [data["args"]["seconds"] for t, data in events if t == "tool.end"]
    assert starts == [0.5, 0.05]
    assert ends == [0.05, 0.5]


def test_kill_switch_runs_tools_serially(tmp_path):
    def slow(args, ctx):
        time.sleep(args["seconds"])
        return "ok"

    agent, _ = make_agent(tmp_path, [
        [call("a", {"seconds": 0.4}), call("b", {"seconds": 0.4})],
        [text("done")],
    ], config={"parallel_tools": False})
    agent.registry.register(Tool("run", "test tool", {"type": "object"}, slow))
    events = []
    agent.bus.on("*", lambda type, **data: events.append((type, data)))

    start = time.monotonic()
    agent.run("go")
    elapsed = time.monotonic() - start
    assert elapsed >= 0.8  # sum, not max
    ends = [data["args"]["seconds"] for t, data in events if t == "tool.end"]
    assert ends == [0.4, 0.4]  # call order throughout


def test_parallel_tool_errors_feed_back(tmp_path):
    def flaky(args, ctx):
        if args["fail"]:
            raise ValueError("kaput")
        return "ok"

    agent, _ = make_agent(tmp_path, [
        [call("a", {"fail": True}), call("b", {"fail": False})],
        [text("recovered")],
    ], config={"parallel_tools": True})
    agent.registry.register(Tool("run", "test tool", {"type": "object"}, flaky))

    assert agent.run("go") == "recovered"
    results = {r["tool_use_id"]: r for r in agent.session.messages[2]["content"]}
    assert results["a"]["is_error"] is True and "kaput" in results["a"]["content"]
    assert results["b"]["is_error"] is False


def test_usage_emitted_after_message_assistant(tmp_path):
    usage = {"input_tokens": 12, "output_tokens": 3,
             "cache_read_input_tokens": 400, "cache_creation_input_tokens": 40}
    agent, _ = make_agent(tmp_path, [[text("ok")]], usage=usage)
    events = []
    agent.bus.on("*", lambda type, **data: events.append((type, data)))
    agent.run("hi")
    assert [t for t, _ in events] == ["message.user", "message.assistant", "usage"]
    assert events[2] == ("usage", {"model": "", **usage})


def test_loop_events(tmp_path):
    agent, _ = make_agent(tmp_path, [
        [call("t1", {"cmd": "ls"})],
        [text("listed the files")],
    ])
    events = []
    agent.bus.on("*", lambda type, **data: events.append((type, data)))
    agent.run("list files")
    types = [t for t, _ in events]
    assert types == [
        "message.user", "message.assistant", "tool.start", "tool.end",
        "message.user", "message.assistant",
    ]
    assert events[0][1] == {
        "message": {"role": "user", "content": [{"type": "text", "text": "list files"}]},
    }
    assert events[1][1]["turn"] == 1
    assert events[1][1]["message"]["content"] == [call("t1", {"cmd": "ls"})]
    assert events[2][1] == {"name": "run", "args": {"cmd": "ls"}}
    assert events[3][1] == {
        "name": "run", "args": {"cmd": "ls"}, "output": "ran ls", "is_error": False,
    }
    assert events[4][1] == {
        "message": {"role": "user", "content": [result("t1", "ran ls")]},
    }
    assert events[5][1]["turn"] == 2
    assert events[5][1]["message"]["content"] == [text("listed the files")]
