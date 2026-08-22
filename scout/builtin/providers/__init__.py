"""LLM providers. Anthropic and OpenAI register via PluginApi."""

import os

from scout.errors import ScoutError

from .anthropic import AnthropicClient
from .openai import OpenAIClient


def _client(cls, name, config: dict):
    key = config.get("api_key") or os.environ.get(name.upper() + "_API_KEY")
    if not key:
        raise ScoutError(
            f"no API key: set {name.upper()}_API_KEY, api_key in scout.toml, "
            "or --api-key"
        )
    return cls(config, key)


def scout(api) -> None:
    api.provider("anthropic", lambda config: _client(AnthropicClient, "anthropic", config))
    api.provider("openai", lambda config: _client(OpenAIClient, "openai", config))
