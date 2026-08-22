"""Example plugin: add a custom tool and a prompt paragraph.

Install:  cp examples/plugins/hello.py ~/.agents/plugins/
          (or into <project>/.agents/plugins/)

Demonstrates api.tool() and api.prompt() — Plugin API v2.
"""

from scout.tools import Tool


def hello(args, ctx):
    return f"hello {args.get('name', 'world')} (cwd: {ctx.cwd})"


def scout(api):
    api.tool(Tool(
        name="hello",
        description="Say hello. Example tool added by a plugin.",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Who to greet."}},
        },
        run=hello,
    ))
    api.prompt("You have a hello tool; use it when asked to greet.")
