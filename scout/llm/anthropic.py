"""Streaming client for the Anthropic Messages API.

Docs: https://docs.anthropic.com/en/api/messages-streaming
The normalized message format is already Anthropic's, so requests pass
through untouched; only the SSE stream needs assembling.
"""

import json

from ..errors import ScoutError
from ..http import post_sse

DEFAULT_BASE_URL = "https://api.anthropic.com"


def to_anthropic(messages: list) -> list:
    return messages  # scout's normalized format IS Anthropic's format


class AnthropicClient:
    def __init__(self, cfg, api_key: str):
        self.cfg = cfg
        self.api_key = api_key
        self.base_url = (cfg.base_url or DEFAULT_BASE_URL).rstrip("/")

    def complete(self, system: str, messages: list, tools: list, on_text=None) -> dict:
        payload = {
            "model": self.cfg.model,
            "max_tokens": self.cfg.max_tokens,
            "system": system,
            "messages": to_anthropic(messages),
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
        for event in post_sse(
            f"{self.base_url}/v1/messages", headers, payload, self.cfg.timeout
        ):
            etype = event.get("type")
            if etype == "content_block_start":
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
            elif etype == "error":
                raise ScoutError(f"anthropic stream error: {event.get('error')}")

        # empty text blocks are rejected by the API on the next turn
        blocks = [b for b in blocks if b["type"] != "text" or b["text"]]
        return {"role": "assistant", "content": blocks}
