"""Example plugin: log every tool call to .scout/tool.log.

Install:  cp examples/plugins/log_hook.py ~/.agents/plugins/

Demonstrates api.on() with the open event vocabulary. Subscribes to
tool.end (payload: name, args, output, is_error).
"""

import time
from pathlib import Path


def on_tool_end(name, args, output, is_error):
    flag = "ERR" if is_error else "ok"
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {flag:3} {name}\n"
    path = Path(".scout") / "tool.log"
    path.parent.mkdir(exist_ok=True)
    with path.open("a") as f:
        f.write(line)


def scout(api):
    api.on("tool.end", on_tool_end)
