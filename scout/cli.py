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
from .errors import ScoutError
from .host import boot


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="scout", description="a minimal terminal coding agent"
    )
    parser.add_argument("prompt_pos", nargs="?", metavar="prompt",
                        help="run this prompt once headlessly, then exit")
    parser.add_argument("-p", "--prompt", help="run this prompt once headlessly, then exit")
    parser.add_argument("-c", "--continue", dest="resume", action="store_true",
                        help="resume the latest session in this directory")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--base-url", help="override the provider's API endpoint")
    parser.add_argument("--api-key")
    parser.add_argument("--max-turns", type=int)
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("-V", "--version", action="version",
                        version=f"scout {__version__}")
    return parser.parse_args(argv)


def _on_text(delta: str) -> None:
    sys.stdout.write(delta)
    sys.stdout.flush()


def main(argv=None) -> int:
    args = parse_args(argv)
    cwd = Path.cwd()
    prompt = args.prompt or args.prompt_pos
    cli = {
        "provider": args.provider,
        "model": args.model,
        "base_url": args.base_url,
        "api_key": args.api_key,
        "max_turns": args.max_turns,
        "max_tokens": args.max_tokens,
        "prompt": prompt,
        "resume": args.resume,
    }
    try:
        rt = boot(cwd, cli)
    except ScoutError as e:
        print(f"scout: {e}", file=sys.stderr)
        return 1

    if prompt is not None:
        rt.bus.emit("display.stderr")
        try:
            answer = rt.agent.run(prompt, on_text=_on_text)
        except ScoutError as e:
            print(f"scout: {e}", file=sys.stderr)
            return 1
        print()
        return 0 if answer.strip() else 1

    return repl(rt)


def repl(rt) -> int:
    print(
        f"scout {__version__}  (session {rt.session.id[:8]})\n"
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
            command, _, rest = line.partition(" ")
            if command in ("/exit", "/quit"):
                return 0
            fn = rt.commands.get(command)
            if fn is None:
                print(f"unknown command {command} — /help")
            else:
                fn(rt.agent, rest.strip())
            continue
        try:
            rt.agent.run(line, on_text=_on_text)
            print()
        except ScoutError as e:
            print(f"\nscout: {e}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\n(interrupted)")
