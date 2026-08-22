"""Tests for the Anthropic client: payload shape and SSE assembly,
with post_sse monkeypatched (no network)."""

import pytest

from scout.config import Config
from scout.llm.anthropic import AnthropicClient

TOOLS = [{"name": "bash", "description": "run", "input_schema": {"type": "object"}}]

START_TEXT = {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
START_TOOL = {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "t1", "name": "bash"}}


@pytest.fixture
def client(monkeypatch):
    def fake_post_sse(url, headers, payload, timeout):
        assert url == "https://api.anthropic.com/v1/messages"
        assert headers["x-api-key"] == "k"
        assert payload["system"] == "sys"
        client.payload = payload
        yield from client.events

    monkeypatch.setattr("scout.llm.anthropic.post_sse", fake_post_sse)
    client = AnthropicClient(Config(model="claude-sonnet-4-5", max_tokens=64), "k")
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
