"""Plugin host: boot, PluginApi v2, and runtime assembly.

Loads the builtin manifest, then ~/.agents/plugins/ and ./.agents/plugins/.
Resolves layered config, opens a session, and returns Runtime.
"""

import importlib
import importlib.util
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .agent import Agent
from .bus import Bus
from .builtin.prompt import build_prompt
from .builtin.session import open_session
from .builtin.skills import load_skills
from .errors import ScoutError
from .tools import Ctx, Registry


@dataclass
class Runtime:
    bus: Bus
    registry: Registry
    commands: dict
    providers: dict
    prompts: list
    config: dict
    client: object
    session: object
    skills: dict
    agent: Agent
    ctx: Ctx
    plugins: list


class PluginApi:
    """Surface handed to each plugin's scout(api). Later wins by name."""

    def __init__(self, registry, bus, commands, providers, prompts, defaults):
        self._registry, self._bus = registry, bus
        self._commands, self._providers = commands, providers
        self._prompts, self._defaults = prompts, defaults

    def tool(self, tool) -> None: self._registry.register(tool)
    def on(self, event: str, fn) -> None: self._bus.on(event, fn)
    def prompt(self, text: str) -> None: self._prompts.append(text)
    def command(self, name: str, fn) -> None: self._commands[name] = fn
    def provider(self, name: str, factory) -> None: self._providers[name] = factory
    def config(self, defaults: dict) -> None: self._defaults.update(defaults)
    def emit(self, type: str, **data) -> None: self._bus.emit(type, **data)


def _activate(name, source, module, api, bus, plugins):
    try:
        getattr(module, "scout", lambda api: None)(api)
    except Exception as e:  # noqa: BLE001 — a bad plugin skips, not crashes
        print(f"scout: plugin {name} failed: {e}", file=sys.stderr)
        return
    bus.emit("plugin.loaded", name=name, source=source)
    plugins.append(name)


def _git(cwd: Path, *args) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           text=True, timeout=2)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:  # noqa: BLE001 — probes must never fail boot
        return ""


def boot(cwd: Path, cli: dict) -> Runtime:
    cli = dict(cli)
    cli.pop("prompt", None)
    resume = cli.pop("resume", False)
    overrides = {k: v for k, v in cli.items() if v is not None}

    bus, registry, commands, providers, prompts, defaults = (
        Bus(), Registry(), {}, {}, [], {},
    )
    layers: dict = {}
    bus.on("config.loaded", lambda **data: layers.update(data))
    api = PluginApi(registry, bus, commands, providers, prompts, defaults)
    plugins: list[str] = []

    for name in importlib.import_module("scout.builtin").MANIFEST:
        try:
            module = importlib.import_module(f"scout.builtin.{name}")
        except Exception as e:  # noqa: BLE001
            print(f"scout: plugin {name} failed: {e}", file=sys.stderr)
            continue
        _activate(name, "builtin", module, api, bus, plugins)

    seen: set = set()
    for source, d in (("user", Path.home() / ".agents" / "plugins"),
                      ("project", cwd / ".agents" / "plugins")):
        if not d.is_dir() or (resolved := d.resolve()) in seen:
            continue
        seen.add(resolved)
        for file in sorted(d.glob("*.py")):
            spec = importlib.util.spec_from_file_location(f"scout_plugin_{file.stem}", file)
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as e:  # noqa: BLE001
                print(f"scout: plugin {file.name} failed: {e}", file=sys.stderr)
                continue
            _activate(file.stem, source, module, api, bus, plugins)

    config = dict(defaults)
    for key in ("user", "project"):
        if isinstance(layers.get(key), dict):
            config.update(layers[key])
    for key in list(config):
        raw = os.environ.get("SCOUT_" + key.upper())
        if not raw:
            continue
        if isinstance(config[key], int):
            try:
                raw = int(raw)
            except ValueError:
                raise ScoutError(f"SCOUT_{key.upper()} must be an integer")
        config[key] = raw
    config.update(overrides)
    if config.get("provider") not in providers:
        raise ScoutError(f"unknown provider {config.get('provider')!r}")

    client = providers[config["provider"]](config)
    session = open_session(cwd, config, resume)
    bus.emit("session.start", cwd=str(cwd), model=config.get("model", ""),
             pid=str(os.getpid()), repository=_git(cwd, "rev-parse", "--show-toplevel"),
             branch=_git(cwd, "branch", "--show-current"))
    skills = load_skills(cwd)
    ctx = Ctx(cwd=cwd, config=config, skills=skills)
    agent = Agent(client, registry, build_prompt(registry, skills, cwd, prompts, config),
                  session, ctx, bus)
    return Runtime(bus, registry, commands, providers, prompts, config,
                   client, session, skills, agent, ctx, plugins)
