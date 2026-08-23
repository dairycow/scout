"""Config: core defaults and user/project toml layers.

Precedence is resolved by the host: plugin defaults < user toml < project
toml < SCOUT_* env < CLI flags. This plugin declares the v1 keys, parses
the two toml files, and emits `config.loaded` with `user=` / `project=`
dicts that contain only keys present in the accumulated defaults (v1
silently ignored unknown toml keys).

Project toml is `./scout.toml` relative to Path.cwd() at plugin load.
boot() is always invoked before any chdir (cli and the test suite pass a
Path.cwd()-derived cwd); a boot(cwd) whose cwd differs from Path.cwd()
will read the wrong project file.
"""

import tomllib
from pathlib import Path

DEFAULTS = {
    "provider": "anthropic",
    "model": "claude-sonnet-4-5",
    "base_url": "",
    "api_key": "",
    "max_tokens": 16384,
    "max_turns": 40,
    "timeout": 300,
    "retries": 2,
}


def _user_path() -> Path:
    return Path.home() / ".config" / "scout" / "scout.toml"


def _project_path() -> Path:
    return Path.cwd() / "scout.toml"


def _parse(path: Path) -> dict:
    return tomllib.loads(path.read_text()) if path.is_file() else {}


def _keep(raw: dict, known: dict) -> dict:
    return {k: v for k, v in raw.items() if k in known}


def scout(api) -> None:
    known = dict(DEFAULTS)
    user_raw = _parse(_user_path())
    project_raw = _parse(_project_path())
    orig = api.config

    def config(defaults: dict) -> None:
        # Later api.config() calls expand known keys so plugin-declared
        # keys still pick up toml layers (config loads first in the manifest).
        known.update(defaults)
        orig(defaults)
        api.emit("config.loaded", user=_keep(user_raw, known),
                 project=_keep(project_raw, known))

    api.config = config
    api.config(known)
