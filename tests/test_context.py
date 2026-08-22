"""Tests for system prompt assembly."""

from scout.context import build_system
from scout.skills import Skill
from scout.tools import Registry, Tool


def test_system_prompt_contains_everything(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Always use uv instead of pip.\n")
    registry = Registry()
    nop = lambda args, ctx: ""  # noqa: E731
    registry.register(*(Tool(n, n, {"type": "object"}, nop) for n in ("bash", "edit", "skill")))
    skills = {"commit": Skill("commit", "how to commit", tmp_path, "body")}

    system = build_system(registry, skills, tmp_path, ["say zebras are grey"])

    assert "You are scout" in system
    assert "- bash:" in system and "- edit:" in system and "- skill:" in system
    assert "commit: how to commit" in system
    assert str(tmp_path) in system
    assert "Always use uv instead of pip." in system
    assert "say zebras are grey" in system


def test_missing_agents_md_and_no_skills(tmp_path):
    system = build_system(Registry(), {}, tmp_path)
    assert "(none installed)" in system
    assert "AGENTS.md" not in system
