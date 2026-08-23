"""search: grep (contents) and glob (filenames). Stdlib only, skips junk dirs."""

import fnmatch
import os
import re
from pathlib import Path

from scout.tools import Tool, clip_line

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".scout"}
MATCH_LINE = 500  # grep hits carry context; cap them harder than read lines


def _walk(root: Path):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        yield Path(dirpath), sorted(files)


def _grep(args: dict, ctx) -> str:
    root = (ctx.cwd / args.get("path", ".")).resolve()
    pattern = re.compile(args["pattern"])
    include = args.get("include")
    hits: list[str] = []
    for dirpath, files in _walk(root):
        for name in files:
            if include and not fnmatch.fnmatch(name, include):
                continue
            file = dirpath / name
            try:
                lines = file.read_text().splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(lines, start=1):
                if pattern.search(line):
                    rel = file.relative_to(ctx.cwd)
                    hits.append(f"{rel}:{number}: {clip_line(line.strip(), MATCH_LINE)}")
                if len(hits) >= 200:
                    hits.append("... [stopped at 200 matches]")
                    return "\n".join(hits)
    return "\n".join(hits) if hits else "no matches"


def _glob(args: dict, ctx) -> str:
    root = (ctx.cwd / args.get("path", ".")).resolve()
    pattern = args["pattern"]
    matches: list[str] = []
    for dirpath, files in _walk(root):
        for name in files:
            rel = (dirpath / name).relative_to(ctx.cwd)
            if fnmatch.fnmatch(rel.as_posix(), pattern):
                matches.append(str(rel))
                if len(matches) >= 500:
                    matches.append("... [stopped at 500 matches]")
                    return "\n".join(matches)
    return "\n".join(matches) if matches else "no matches"


TOOLS = [
    Tool(
        name="grep",
        description=(
            "Search file contents with a Python regular expression. Returns "
            "path:line: text matches. Use include (e.g. '*.py') to filter filenames."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python regex to search for."},
                "path": {"type": "string", "description": "Directory to search (default: project directory)."},
                "include": {"type": "string", "description": "Only search files matching this glob, e.g. '*.py'."},
            },
            "required": ["pattern"],
        },
        run=_grep,
    ),
    Tool(
        name="glob",
        description=(
            "Find files by glob pattern (e.g. '*.py', 'src/**/*.json'), matched "
            "against paths relative to the search directory. * also crosses '/'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern for relative file paths."},
                "path": {"type": "string", "description": "Directory to search (default: project directory)."},
            },
            "required": ["pattern"],
        },
        run=_glob,
    ),
]
