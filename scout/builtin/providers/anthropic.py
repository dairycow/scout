"""Streaming client for the Anthropic Messages API.

Docs: https://docs.anthropic.com/en/api/messages-streaming
The normalized message format is already Anthropic's, so requests pass
through untouched; only the SSE stream needs assembling.
"""

import json

from scout.errors import ScoutError
from scout.http import post_sse

DEFAULT_BASE_URL = "https://api.anthropic.com"


def to_anthropic(messages: list) -> list:
    return messages  # scout's normalized format IS Anthropic's format


def _with_cache_control(messages: list) -> list:
    """Copy only the tail; mark the last block of the last message.

    O(1) regardless of history length: earlier message dicts are shared
    (history is append-only, so they are never mutated afterwards).
    """
    if not messages or not messages[-1].get("content"):
        return messages
    last = messages[-1]
    block = {**last["content"][-1], "cache_control": {"type": "ephemeral"}}
    return messages[:-1] + [{**last, "content": last["content"][:-1] + [block]}]


class AnthropicClient:
    def __init__(self, cfg, api_key: str):
        self.cfg = cfg
        self.api_key = api_key
        self.base_url = (cfg["base_url"] or DEFAULT_BASE_URL).rstrip("/")

    def complete(self, system: str, messages: list, tools: list,
                 on_text=None, on_usage=None) -> dict:
        payload = {
            "model": self.cfg["model"],
            "max_tokens": self.cfg["max_tokens"],
            "system": [{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }],
            "messages": _with_cache_control(to_anthropic(messages)),
            "stream": True,
        }
        if tools:
            payload["tools"] = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["input_schema"],
                }
                for t in tools
            ]
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        blocks: list[dict] = []
        json_buffers: dict[int, list[str]] = {}  # block index -> tool input parts
        usage: dict = {}  # message_start usage, finalized by message_delta
        for event in post_sse(
            f"{self.base_url}/v1/messages", headers, payload, self.cfg["timeout"],
            retries=self.cfg.get("retries", 2),
        ):
            etype = event.get("type")
            if etype == "message_start":
                usage.update(event.get("message", {}).get("usage", {}))
            elif etype == "content_block_start":
                block = event["content_block"]
                if block["type"] == "tool_use":
                    blocks.append(
                        {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}
                    )
                    json_buffers[event["index"]] = []
                else:
                    blocks.append({"type": "text", "text": ""})
            elif etype == "content_block_delta":
                delta = event["delta"]
                index = event["index"]
                if delta["type"] == "text_delta":
                    blocks[index]["text"] += delta["text"]
                    if on_text:
                        on_text(delta["text"])
                elif delta["type"] == "input_json_delta":
                    json_buffers[index].append(delta["partial_json"])
            elif etype == "content_block_stop":
                index = event["index"]
                if index in json_buffers:
                    raw = "".join(json_buffers.pop(index))
                    blocks[index]["input"] = json.loads(raw) if raw else {}
            elif etype == "message_delta":
                usage.update(event.get("usage", {}))
            elif etype == "error":
                raise ScoutError(f"anthropic stream error: {event.get('error')}")

        if on_usage:
            on_usage({
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
                "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            })

        # empty text blocks are rejected by the API on the next turn
        blocks = [b for b in blocks if b["type"] != "text" or b["text"]]
        return {"role": "assistant", "content": blocks}
