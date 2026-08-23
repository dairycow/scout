"""REPL commands: /help, /skills, /plugins. /exit and /quit are REPL-owned."""

from . import MANIFEST

HELP = """\
/help     show this list
/exit     quit (Ctrl-D also works)
/clear    start a fresh session
/fork [n] fork this session at message n (default: all)
/skills   list installed skills
/plugins  list loaded plugins"""


def scout(api) -> None:
    # Builtins fire plugin.loaded before this module subscribed; MANIFEST
    # order is normative for those names.
    loaded = list(MANIFEST)

    def on_loaded(name, **_):
        if name not in loaded:
            loaded.append(name)

    api.on("plugin.loaded", on_loaded)

    def help_cmd(agent, rest):
        print(HELP)

    def skills_cmd(agent, rest):
        print("\n".join(f"{n}: {s.description}" for n, s in sorted(agent.ctx.skills.items()))
              or "(no skills installed)")

    def plugins_cmd(agent, rest):
        print("\n".join(loaded) or "(no plugins loaded)")

    api.command("/help", help_cmd)
    api.command("/skills", skills_cmd)
    api.command("/plugins", plugins_cmd)
