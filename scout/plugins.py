"""Plugins: plain *.py files exposing a `scout(api)` function.

Loaded from ./.agents/plugins/ after ~/.agents/plugins/ (so a project
plugin loaded later can override an earlier registration by name).

The api object has exactly three methods:

    api.register_tool(tool)   add or replace a tool in the registry
    api.on(event, fn)         subscribe to a hook (see HOOKS below)
    api.prompt(text)          append a paragraph to the system prompt
"""

import importlib.util
import sys
from pathlib import Path

HOOKS = ("session_start", "tool_start", "tool_end", "message_end")


class PluginApi:
    """The surface handed to each plugin's scout(api) function."""

    def __init__(self, registry, hooks: dict, prompts: list):
        self._registry = registry
        self._hooks = hooks
        self._prompts = prompts

    def register_tool(self, tool) -> None:
        self._registry.register(tool)

    def on(self, event: str, fn) -> None:
        if event not in HOOKS:
            raise ValueError(f"unknown event {event!r}; want one of {HOOKS}")
        self._hooks[event].append(fn)

    def prompt(self, text: str) -> None:
        self._prompts.append(text)


def new_hooks() -> dict:
    return {event: [] for event in HOOKS}


def emit(hooks: dict, event: str, **kwargs) -> None:
    """Call every subscriber; a broken hook is reported, never fatal."""
    for fn in hooks[event]:
        try:
            fn(**kwargs)
        except Exception as e:  # noqa: BLE001 — plugins must not kill the agent
            print(f"scout: {event} hook failed: {e}", file=sys.stderr)


def load_plugins(cwd: Path, registry, hooks: dict, prompts: list,
                 user_dir: Path | None = None) -> list[str]:
    """Execute every plugin file; return the filenames that loaded."""
    user_dir = user_dir or (Path.home() / ".agents" / "plugins")
    loaded: list[str] = []
    for d in (user_dir, cwd / ".agents" / "plugins"):
        if not d.is_dir():
            continue
        for file in sorted(d.glob("*.py")):
            spec = importlib.util.spec_from_file_location(f"scout_plugin_{file.stem}", file)
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
                if hasattr(module, "scout"):
                    module.scout(PluginApi(registry, hooks, prompts))
                loaded.append(file.name)
            except Exception as e:  # noqa: BLE001 — a bad plugin skips, not crashes
                print(f"scout: plugin {file.name} failed: {e}", file=sys.stderr)
    return loaded
