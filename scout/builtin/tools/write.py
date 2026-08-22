"""write: create or overwrite a file."""

from scout.tools import Tool


def _run(args: dict, ctx) -> str:
    path = (ctx.cwd / args["path"]).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args["content"])
    return f"wrote {len(args['content'].splitlines())} lines to {args['path']}"


TOOLS = [
    Tool(
        name="write",
        description="Create or overwrite a file with the given content. Parent directories are created.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path, relative to the project directory."},
                "content": {"type": "string", "description": "Full file content to write."},
            },
            "required": ["path", "content"],
        },
        run=_run,
    ),
]
