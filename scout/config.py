"""Config: plain dataclass + layered loading.

Precedence (later wins):
    defaults  <  ~/.config/scout/scout.toml  <  ./scout.toml
              <  SCOUT_* environment  <  CLI flags
"""

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from .errors import ScoutError

USER_CONFIG = Path.home() / ".config" / "scout" / "scout.toml"
USER_AGENTS_DIR = Path.home() / ".agents"
PROJECT_AGENTS_DIR = Path(".agents")
SESSIONS_DIR = Path(".scout") / "sessions"


@dataclass
class Config:
    provider: str = "anthropic"      # "anthropic" or "openai" (any compatible API)
    model: str = "claude-sonnet-4-5"  # for openai provider, e.g. "gpt-4o"
    base_url: str = ""               # override the provider's API endpoint
    api_key: str = ""                # else ANTHROPIC_API_KEY / OPENAI_API_KEY
    max_tokens: int = 4096           # per model response
    max_turns: int = 40              # tool-loop guard, per user message
    timeout: int = 300               # seconds per HTTP request


def _apply(cfg: Config, values: dict) -> None:
    names = {f.name for f in fields(Config)}
    for key, value in values.items():
        if key in names and value is not None:
            setattr(cfg, key, value)


def _load_toml(cfg: Config, path: Path) -> None:
    if path.is_file():
        _apply(cfg, tomllib.loads(path.read_text()))


def _load_env(cfg: Config) -> None:
    for name in (f.name for f in fields(Config)):
        value = os.environ.get("SCOUT_" + name.upper())
        if value:
            if isinstance(getattr(cfg, name), int):
                try:
                    value = int(value)
                except ValueError:
                    raise ScoutError(f"SCOUT_{name.upper()} must be an integer")
            _apply(cfg, {name: value})


def load(cli: dict | None = None, cwd: Path = Path.cwd(),
         user_config: Path = USER_CONFIG) -> Config:
    cfg = Config()
    _load_toml(cfg, user_config)
    _load_toml(cfg, cwd / "scout.toml")
    _load_env(cfg)
    _apply(cfg, cli or {})
    if cfg.provider not in ("anthropic", "openai"):
        raise ScoutError(f"unknown provider {cfg.provider!r} (want 'anthropic' or 'openai')")
    return cfg
