"""Tests for the Anthropic client: payload shape and SSE assembly,
with post_sse monkeypatched (no network)."""

import copy
import json

import pytest

from scout.builtin.providers.anthropic import AnthropicClient

TOOLS = [{"name": "bash", "description": "run", "input_schema": {"type": "object"}}]

START_TEXT = {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
START_TOOL = {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "t1", "name": "bash"}}

CFG = {"model": "claude-sonnet-4-5", "max_tokens": 64, "base_url": "", "timeout": 60, "api_key": "k"}


@pytest.fixture
def client(monkeypatch):
    def fake_post_sse(url, headers, payload, timeout):
        assert url == "https://api.anthropic.com/v1/messages"
        assert headers["x-api-key"] == "k"
        assert payload["system"][0]["text"] == "sys"
        client.payload = payload
        yield from client.events

    monkeypatch.setattr("scout.builtin.providers.anthropic.post_sse", fake_post_sse)
    client = AnthropicClient(CFG, "k")
    client.events = []
    client.payload = None
    return client


def test_stream_assembles_text_and_tool_input(client):
    client.events = [
        START_TEXT,
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
        START_TOOL,
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta",
                                                              "partial_json": '{"comm'}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta",
                                                              "partial_json": 'and": "ls"}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_stop"},
    ]
    streamed = []
    message = client.complete("sys", [], TOOLS, on_text=streamed.append)

    assert streamed == ["Hi"]
    assert message["content"][0] == {"type": "text", "text": "Hi"}
    assert message["content"][1] == {"type": "tool_use", "id": "t1", "name": "bash",
                                     "input": {"command": "ls"}}
    wire = client.payload["tools"][0]
    assert wire == {"name": "bash", "description": "run", "input_schema": {"type": "object"}}


def test_empty_text_block_dropped(client):
    client.events = [
        START_TEXT,  # text block that never receives a delta
        {"type": "content_block_stop", "index": 0},
        {"type": "message_stop"},
    ]
    message = client.complete("sys", [], [])
    assert message["content"] == []


def test_no_tools_omits_tools_key(client):
    client.events = [{"type": "message_stop"}]
    client.complete("sys", [], [])
    assert "tools" not in client.payload


def test_stream_error_raises_scout_error(client):
    from scout.errors import ScoutError

    client.events = [{"type": "error", "error": {"type": "overloaded_error"}}]
    with pytest.raises(ScoutError, match="overloaded"):
        client.complete("sys", [], [])


HISTORY = [
    {"role": "user", "content": [{"type": "text", "text": "list files"}]},
    {"role": "assistant", "content": [
        {"type": "text", "text": "sure"},
        {"type": "tool_use", "id": "c1", "name": "bash", "input": {"command": "ls"}},
    ]},
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "c1", "content": "a\nb", "is_error": False},
        {"type": "text", "text": "now summarize"},
    ]},
]


def test_cache_control_on_system_and_last_block(client):
    messages = copy.deepcopy(HISTORY)
    client.events = [{"type": "message_stop"}]
    client.complete("sys", messages, [])

    system = client.payload["system"]
    assert isinstance(system, list)
    assert sum(1 for b in system if "cache_control" in b) == 1
    assert system[0]["type"] == "text"
    assert system[0]["cache_control"] == {"type": "ephemeral"}

    marked = []
    for i, msg in enumerate(client.payload["messages"]):
        for j, block in enumerate(msg["content"]):
            if "cache_control" in block:
                marked.append((i, j, block["cache_control"]))
    last_i = len(client.payload["messages"]) - 1
    last_j = len(client.payload["messages"][last_i]["content"]) - 1
    assert marked == [(last_i, last_j, {"type": "ephemeral"})]


def test_cache_control_does_not_mutate_caller_or_return(client):
    messages = copy.deepcopy(HISTORY)
    snapshot = copy.deepcopy(messages)
    client.events = [
        START_TEXT,
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_stop"},
    ]
    message = client.complete("sys", messages, [])

    assert messages == snapshot
    assert "cache_control" not in json.dumps(message)
    assert "cache_control" not in json.dumps(messages)
