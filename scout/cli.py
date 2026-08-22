"""scout's entry point and the only file that talks to the human.

Modes:
    scout                 interactive REPL
    scout -p "prompt"     one headless run, prints the answer, exits
    scout -c              resume the latest session in this directory
"""

import argparse
import sys
from pathlib import Path

from . import __version__
from .agent import Agent
from .config import load as load_config
from .context import build_system
from .errors import ScoutError
from .llm import get_client
from .plugins import emit, load_plugins, new_hooks
from .session import Session, new_session
from .skills import load_skills
from .tools import Ctx, Registry, builtins

HELP = """\
/help     show this list
/exit     quit (Ctrl-D also works)
/clear    start a fresh session
/skills   list installed skills
/plugins  list loaded plugins"""


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="scout", description="a minimal terminal coding agent"
    )
    parser.add_argument("prompt_pos", nargs="?", metavar="prompt",
                        help="run this prompt once headlessly, then exit")
    parser.add_argument("-p", "--prompt", help="run this prompt once headlessly, then exit")
    parser.add_argument("-c", "--continue", dest="resume", action="store_true",
                        help="resume the latest session in this directory")
    parser.add_argument("--provider", choices=["anthropic", "openai"])
    parser.add_argument("--model")
    parser.add_argument("--base-url", help="override the provider's API endpoint")
    parser.add_argument("--api-key")
    parser.add_argument("--max-turns", type=int)
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("-V", "--version", action="version",
                        version=f"scout {__version__}")
    return parser.parse_args(argv)


def cli_overrides(args) -> dict:
    return {
        "provider": args.provider,
        "model": args.model,
        "base_url": args.base_url,
        "api_key": args.api_key,
        "max_turns": args.max_turns,
        "max_tokens": args.max_tokens,
    }


def display_hooks(hooks: dict, file) -> None:
    """Print one line per tool call so the human sees what the agent is doing."""

    def tool_start(name, args):
        print(f"[{name}] {str(args)[:120]}", file=file)

    def tool_end(name, output, is_error, **_):
        first = output.splitlines()[0][:120] if output else "(no output)"
        mark = "!" if is_error else ""
        print(f"[{name}]{mark} {first}", file=file)

    hooks["tool_start"].append(tool_start)
    hooks["tool_end"].append(tool_end)


def main(argv=None) -> int:
    args = parse_args(argv)
    cwd = Path.cwd()
    prompt = args.prompt or args.prompt_pos

    try:
        cfg = load_config(cli_overrides(args), cwd)
        client = get_client(cfg)
        skills = load_skills(cwd)

        registry = Registry()
        registry.register(*builtins())
        hooks = new_hooks()
        plugin_prompts: list[str] = []
        plugins = load_plugins(cwd, registry, hooks, plugin_prompts)

        if args.resume:
            session = Session.latest(cwd)
            if session is None:
                raise ScoutError("no previous session found in this directory")
        else:
            session = new_session(cwd)

        ctx = Ctx(cwd=cwd, config=cfg, skills=skills)
        agent = Agent(client, registry, build_system(registry, skills, cwd, plugin_prompts),
                      session, ctx, hooks)
        emit(hooks, "session_start", cwd=str(cwd), model=cfg.model)
    except ScoutError as e:
        print(f"scout: {e}", file=sys.stderr)
        return 1

    if prompt is not None:
        display_hooks(hooks, sys.stderr)  # keep stdout clean for the answer
        try:
            answer = agent.run(
                prompt, on_text=lambda d: (sys.stdout.write(d), sys.stdout.flush())
            )
        except ScoutError as e:
            print(f"scout: {e}", file=sys.stderr)
            return 1
        print()
        return 0 if answer.strip() else 1

    return repl(agent, skills, plugins, cwd)


def repl(agent: Agent, skills: dict, plugins: list, cwd: Path) -> int:
    display_hooks(agent.hooks, sys.stdout)
    print(
        f"scout {__version__}  ({agent.session.path})\n"
        "/help for commands, Ctrl-D to exit"
    )
    while True:
        try:
            line = input("scout> ").strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            return 0
        if not line:
            continue
        if line.startswith("/"):
            command = line.split()[0]
            if command in ("/exit", "/quit"):
                return 0
            elif command == "/help":
                print(HELP)
            elif command == "/clear":
                agent.session = new_session(cwd)
                print(f"fresh session ({agent.session.path})")
            elif command == "/skills":
                print("\n".join(f"{n}: {s.description}" for n, s in sorted(skills.items()))
                      or "(no skills installed)")
            elif command == "/plugins":
                print("\n".join(plugins) or "(no plugins loaded)")
            else:
                print(f"unknown command {command} — /help")
            continue
        try:
            agent.run(line, on_text=lambda d: (sys.stdout.write(d), sys.stdout.flush()))
            print()
        except ScoutError as e:
            print(f"\nscout: {e}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\n(interrupted)")
