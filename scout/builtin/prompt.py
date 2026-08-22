"""System prompt assembly: identity, tools, skills, environment, AGENTS.md,
and plugin paragraphs. Built once at startup, never mutated.
"""

import platform
from datetime import date
from pathlib import Path

from scout.tools import truncate

TEMPLATE = """\
You are scout, a terminal coding agent. You have no personality: no \
greetings, no filler, no opinions — just the task.

Rules:
- Do the task in as few steps as possible.
- Use tools for anything that touches files or commands; never claim an \
action you did not perform.
- Prefer edit over write for changing existing files.
- Tool output is authoritative; if something fails, read the error and adjust.
- When the task is done, stop calling tools and reply with a short final answer.

# Tools

{tools}

# Skills

{skills}

# Environment

- working directory: {cwd}
- platform: {platform}
- date: {date}
{agents_md}{plugin_prompts}"""


def find_agents_md(cwd: Path) -> Path | None:
    for path in (cwd / "AGENTS.md", Path.home() / ".agents" / "AGENTS.md"):
        if path.is_file():
            return path
    return None


def build_prompt(registry, skills, cwd, paragraphs, config) -> str:
    tools = "\n".join(
        f"- {t['name']}: {t['description']}" for t in registry.schemas()
    )
    if skills:
        lines = "\n".join(
            f"- {name}: {s.description or '(no description)'}"
            for name, s in sorted(skills.items())
        )
        skills_md = (
            "Load one with the skill tool before following it.\n" + lines
        )
    else:
        skills_md = "(none installed)"

    agents_md = ""
    path = find_agents_md(cwd)
    if path:
        agents_md = (
            f"\n# Project instructions ({path})\n\n"
            f"{truncate(path.read_text(), 8000)}\n"
        )

    prompts = "".join(
        f"\n# Plugin instructions\n\n{text}\n" for text in (paragraphs or [])
    )

    return TEMPLATE.format(
        tools=tools,
        skills=skills_md,
        cwd=cwd,
        platform=platform.platform(),
        date=date.today().isoformat(),
        agents_md=agents_md,
        plugin_prompts=prompts,
    )


def scout(api) -> None:
    pass
