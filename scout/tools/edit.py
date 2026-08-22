"""edit: exact string replacement — the safe way to change a file."""

from . import Tool


def _run(args: dict, ctx) -> str:
    path = (ctx.cwd / args["path"]).resolve()
    text = path.read_text()
    old, new = args["old_string"], args["new_string"]
    count = text.count(old)
    if count == 0:
        raise ValueError("old_string not found in file")
    if count > 1 and not args.get("replace_all"):
        raise ValueError(
            f"old_string appears {count} times; add surrounding context to make it "
            "unique, or pass replace_all=true"
        )
    text = text.replace(old, new, -1 if args.get("replace_all") else 1)
    path.write_text(text)
    replaced = count if args.get("replace_all") else 1
    return f"replaced {replaced} occurrence(s) in {args['path']}"


TOOLS = [
    Tool(
        name="edit",
        description=(
            "Replace an exact string in a file. old_string must match the file "
            "byte-for-byte including indentation; it must be unique unless "
            "replace_all is true."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path, relative to the project directory."},
                "old_string": {"type": "string", "description": "Exact text to replace."},
                "new_string": {"type": "string", "description": "Replacement text."},
                "replace_all": {"type": "boolean", "description": "Replace every occurrence (default false)."},
            },
            "required": ["path", "old_string", "new_string"],
        },
        run=_run,
    ),
]
