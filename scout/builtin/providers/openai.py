"""Streaming client for any OpenAI-compatible Chat Completions API.

Works with OpenAI, OpenRouter, Groq, Ollama, vLLM, llama.cpp server, ...
Set base_url (CLI --base-url, SCOUT_BASE_URL, or scout.toml) to point it
anywhere that speaks the protocol.
"""

import json

from scout.errors import ScoutError
from scout.http import post_sse

DEFAULT_BASE_URL = "https://api.openai.com/v1"


def to_openai(system: str, messages: list) -> list[dict]:
    """Translate normalized messages to Chat Completions format.

    tool_use blocks become `tool_calls` on the assistant message;
    tool_result blocks become standalone `role: "tool"` messages.
    """
    out = [{"role": "system", "content": system}]
    for msg in messages:
        texts = [b["text"] for b in msg["content"] if b["type"] == "text"]
        calls = [b for b in msg["content"] if b["type"] == "tool_use"]
        if msg["role"] == "assistant":
            entry = {"role": "assistant", "content": "\n".join(texts) or None}
            if calls:
                entry["tool_calls"] = [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {
                            "name": c["name"],
                            "arguments": json.dumps(c["input"]),
                        },
                    }
                    for c in calls
                ]
            out.append(entry)
        else:
            if any(texts):
                out.append({"role": "user", "content": "\n".join(texts)})
            for block in msg["content"]:
                if block["type"] == "tool_result":
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": block["content"],
                        }
                    )
    return out


class OpenAIClient:
    def __init__(self, cfg, api_key: str):
        self.cfg = cfg
        self.api_key = api_key
        self.base_url = (cfg["base_url"] or DEFAULT_BASE_URL).rstrip("/")

    def complete(self, system: str, messages: list, tools: list, on_text=None) -> dict:
        payload = {
            "model": self.cfg["model"],
            "max_tokens": self.cfg["max_tokens"],
            "messages": to_openai(system, messages),
            "stream": True,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]
        headers = {"Authorization": f"Bearer {self.api_key}"}

        text_parts: list[str] = []
        calls: dict[int, dict] = {}  # tool_call index -> {"id", "name", "args": [parts]}
        for chunk in post_sse(
            f"{self.base_url}/chat/completions", headers, payload, self.cfg["timeout"]
        ):
            if chunk.get("error"):
                raise ScoutError(f"openai stream error: {chunk['error']}")
            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            if delta.get("content"):
                text_parts.append(delta["content"])
                if on_text:
                    on_text(delta["content"])
            for tc in delta.get("tool_calls") or []:
                call = calls.setdefault(tc["index"], {"id": None, "name": "", "args": []})
                if tc.get("id"):
                    call["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    call["name"] += fn["name"]
                if fn.get("arguments"):
                    call["args"].append(fn["arguments"])

        blocks: list[dict] = []
        if text_parts:
            blocks.append({"type": "text", "text": "".join(text_parts)})
        for index in sorted(calls):
            call = calls[index]
            try:
                args = json.loads("".join(call["args"]) or "{}")
            except json.JSONDecodeError:
                args = {}  # malformed call; empty input, model sees the error
            blocks.append(
                {
                    "type": "tool_use",
                    "id": call["id"] or f"call_{index}",
                    "name": call["name"],
                    "input": args,
                }
            )
        return {"role": "assistant", "content": blocks}
