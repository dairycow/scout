"""Example plugin: log every tool call to .scout/tool.log.

Install:  cp examples/plugins/log_hook.py ~/.agents/plugins/

Demonstrates hooks. Events and their keyword arguments:

    session_start(cwd, model)
    tool_start(name, args)
    tool_end(name, args, output, is_error)
    message_end(message, turn)
"""

import time
from pathlib import Path


def log(kind, name):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {kind:5} {name}\n"
    path = Path(".scout") / "tool.log"
    path.parent.mkdir(exist_ok=True)
    with path.open("a") as f:
        f.write(line)


def scout(api):
    api.on("tool_start", lambda name, args: log("start", name))
    api.on("tool_end", lambda name, **kw: log("end", name))
