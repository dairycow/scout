"""read: read a text file with line numbers, like an error message refers to."""

from . import Tool

DEFAULT_LIMIT = 2000


def _run(args: dict, ctx) -> str:
    path = (ctx.cwd / args["path"]).resolve()
    try:
        text = path.read_text()
    except UnicodeDecodeError:
        raise ValueError(f"{args['path']} is not a text file") from None
    lines = text.splitlines()
    offset = args.get("offset", 1)
    limit = args.get("limit", DEFAULT_LIMIT)
    end = offset - 1 + limit
    chunk = lines[offset - 1:end]
    numbered = "\n".join(f"{offset + i}: {line}" for i, line in enumerate(chunk))
    if len(lines) > end:
        numbered += f"\n... [{len(lines) - end} more lines; use offset={end + 1}] ..."
    return numbered or "(empty file)"


TOOLS = [
    Tool(
        name="read",
        description="Read a text file with line numbers. Use offset/limit for large files.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path, relative to the project directory."},
                "offset": {"type": "integer", "description": "Line number to start from (1-based, default 1)."},
                "limit": {"type": "integer", "description": f"Max lines to return (default {DEFAULT_LIMIT})."},
            },
            "required": ["path"],
        },
        run=_run,
    ),
]
