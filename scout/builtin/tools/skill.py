"""skill: pull a skill's full instructions into the conversation."""

from scout.tools import Tool


def _run(args: dict, ctx) -> str:
    skill = ctx.skills.get(args["name"])
    if skill is None:
        available = ", ".join(sorted(ctx.skills)) or "(none installed)"
        raise ValueError(f"unknown skill {args['name']!r}; available: {available}")
    return skill.body


TOOLS = [
    Tool(
        name="skill",
        description=(
            "Load a skill's full instructions. Skill names and one-line "
            "descriptions are listed in the system prompt; call this before "
            "following a skill."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the skill to load."},
            },
            "required": ["name"],
        },
        run=_run,
    ),
]
