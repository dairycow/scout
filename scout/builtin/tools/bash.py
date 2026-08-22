"""bash: run a shell command in the project directory."""

import subprocess

from scout.tools import Tool


def _run(args: dict, ctx) -> str:
    timeout = args.get("timeout", 120)
    proc = subprocess.run(
        args["command"],
        shell=True,
        cwd=ctx.cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    out = out.rstrip()
    return f"exit code: {proc.returncode}" + (f"\n{out}" if out else "")


TOOLS = [
    Tool(
        name="bash",
        description=(
            "Run a shell command in the project directory. Returns the exit "
            "code and combined stdout/stderr. Any file work you can't do with "
            "read/write/edit/grep/glob, do here."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to run."},
                "timeout": {
                    "type": "integer",
                    "description": "Seconds before the command is killed (default 120).",
                },
            },
            "required": ["command"],
        },
        run=_run,
    ),
]
