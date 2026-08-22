"""LLM clients. Both providers normalize to one message format:

    messages = [{"role": "user" | "assistant", "content": [block, ...]}]

    block = {"type": "text", "text": str}
          | {"type": "tool_use", "id": str, "name": str, "input": dict}
          | {"type": "tool_result", "tool_use_id": str, "content": str, "is_error": bool}

This IS the Anthropic wire format; the OpenAI client translates to/from
Chat Completions. Both clients expose one method:

    complete(system, messages, tools, on_text) -> assistant message dict

`on_text(delta)` fires as text streams in (for live display), and the full
assembled assistant message is the return value.
"""

import os

from ..config import Config
from ..errors import ScoutError
from .anthropic import AnthropicClient
from .openai import OpenAIClient


def get_client(cfg: Config):
    """Build the client for cfg.provider, resolving the API key."""
    key = cfg.api_key or os.environ.get(cfg.provider.upper() + "_API_KEY")
    if not key:
        raise ScoutError(
            f"no API key: set {cfg.provider.upper()}_API_KEY, api_key in scout.toml, "
            "or --api-key"
        )
    return {  # type: ignore[return-value]
        "anthropic": AnthropicClient,
        "openai": OpenAIClient,
    }[cfg.provider](cfg, key)
