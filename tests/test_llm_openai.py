"""Tests for the OpenAI-compatible client: message translation and
stream assembly, with post_sse monkeypatched (no network)."""

import pytest

from scout.builtin.providers.openai import OpenAIClient, to_openai

TOOLS = [{"name": "bash", "description": "run", "input_schema": {"type": "object"}}]

CFG = {"model": "gpt-4o", "max_tokens": 64, "base_url": "", "timeout": 60, "api_key": "k"}


def test_to_openai_translation():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "list files"}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "sure"},
            {"type": "tool_use", "id": "c1", "name": "bash", "input": {"command": "ls"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": "a\nb", "is_error": False},
        ]},
    ]
    out = to_openai("be terse", messages)
    assert out[0] == {"role": "system", "content": "be terse"}
    assert out[1] == {"role": "user", "content": "list files"}
    assert out[2]["role"] == "assistant"
    assert out[2]["content"] == "sure"
    assert out[2]["tool_calls"] == [{
        "id": "c1", "type": "function",
        "function": {"name": "bash", "arguments": '{"command": "ls"}'},
    }]
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "a\nb"}


def test_to_openai_tool_only_assistant_has_null_content():
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "c1", "name": "bash", "input": {}},
        ]},
    ]
    out = to_openai("sys", messages)
    assert out[1]["content"] is None


def chunks_of(*deltas):
    return [{"choices": [{"delta": d}]} for d in deltas]


@pytest.fixture
def client(monkeypatch):
    def fake_post_sse(url, headers, payload, timeout):
        assert url == "https://api.openai.com/v1/chat/completions"
        assert headers["Authorization"].startswith("Bearer ")
        if payload.get("tools"):
            assert payload["tools"][0]["function"]["name"] == "bash"
        client.payload = payload
        yield from client.events

    monkeypatch.setattr("scout.builtin.providers.openai.post_sse", fake_post_sse)
    client = OpenAIClient(CFG, "k")
    client.events = []
    client.payload = None
    return client


def test_stream_assembles_text_and_tool_call(client):
    client.events = chunks_of(
        {"content": "Hel"},
        {"content": "lo"},
        {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "bash",
                                                              "arguments": '{"comm'}}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": 'and": "ls"}'}}]},
    )
    streamed = []
    message = client.complete("sys", [], TOOLS, on_text=streamed.append)

    assert streamed == ["Hel", "lo"]
    assert message["content"][0] == {"type": "text", "text": "Hello"}
    call = message["content"][1]
    assert call == {"type": "tool_use", "id": "c1", "name": "bash",
                    "input": {"command": "ls"}}


def test_stream_without_tools_omits_tools_key(client):
    client.events = chunks_of({"content": "hi"})
    message = client.complete("sys", [], [])
    assert "tools" not in client.payload
    assert message["content"] == [{"type": "text", "text": "hi"}]


def test_malformed_tool_arguments_become_empty_input(client):
    client.events = chunks_of(
        {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "bash",
                                                              "arguments": "{oops"}}]},
    )
    message = client.complete("sys", [], TOOLS)
    assert message["content"][0]["input"] == {}
