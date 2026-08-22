"""Tests for system prompt assembly via build_prompt."""

from scout.builtin.prompt import build_prompt
from scout.builtin.skills import Skill
from scout.tools import Registry, Tool


def test_build_prompt_contains_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "AGENTS.md").write_text("Always use uv instead of pip.\n")
    registry = Registry()
    nop = lambda args, ctx: ""  # noqa: E731
    registry.register(*(Tool(n, n, {"type": "object"}, nop) for n in ("bash", "edit", "skill")))
    skills = {"commit": Skill("commit", "how to commit", tmp_path, "body")}

    system = build_prompt(registry, skills, tmp_path, ["say zebras are grey"], {})

    assert "You are scout" in system
    assert "- bash:" in system and "- edit:" in system and "- skill:" in system
    assert "commit: how to commit" in system
    assert str(tmp_path) in system
    assert "Always use uv instead of pip." in system
    assert "say zebras are grey" in system
    assert "# Plugin instructions" in system


def test_missing_agents_md_and_no_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    system = build_prompt(Registry(), {}, tmp_path, [], {})
    assert "(none installed)" in system
    assert "AGENTS.md" not in system


def test_agents_md_home_fallback(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    (home / ".agents").mkdir(parents=True)
    (home / ".agents" / "AGENTS.md").write_text("from-home-agents\n")
    cwd = tmp_path / "proj"
    cwd.mkdir()
    system = build_prompt(Registry(), {}, cwd, [], {})
    assert "from-home-agents" in system
    assert "AGENTS.md" in system


def test_agents_md_truncated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    body = "A" * 9000
    (tmp_path / "AGENTS.md").write_text(body)
    system = build_prompt(Registry(), {}, tmp_path, [], {})
    assert "characters truncated" in system
    assert body not in system
    assert "A" * 100 in system
