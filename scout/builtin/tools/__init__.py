"""Built-in tools. Implementations register via PluginApi."""


def scout(api) -> None:
    from . import bash, edit, read, search, skill, write

    for module in (bash, read, write, edit, search, skill):
        for t in module.TOOLS:
            api.tool(t)
