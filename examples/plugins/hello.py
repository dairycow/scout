"""Example plugin: adds a custom tool.

Install:  cp examples/plugins/hello.py ~/.agents/plugins/
          (or into <project>/.agents/plugins/)

Plugins are plain modules exposing scout(api). The api has exactly three
methods: register_tool, on(event, fn), prompt(text).
"""

from scout.tools import Tool


def hello(args, ctx):
    return f"hello {args.get('name', 'world')} (cwd: {ctx.cwd})"


def scout(api):
    api.register_tool(Tool(
        name="hello",
        description="Say hello. Example tool added by a plugin.",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Who to greet."}},
        },
        run=hello,
    ))
