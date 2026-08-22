"""Tests for SKILL.md discovery and frontmatter parsing."""

from pathlib import Path

from scout.builtin.skills import load_skills, parse_skill


def test_parse_frontmatter(tmp_path):
    md = tmp_path / "SKILL.md"
    md.write_text("---\nname: commit\ndescription: how to commit\n---\n\nStep one.\n")
    skill = parse_skill(md, "fallback")
    assert skill.name == "commit"
    assert skill.description == "how to commit"
    assert skill.body == "Step one."
    assert skill.path == md


def test_parse_without_frontmatter(tmp_path):
    md = tmp_path / "SKILL.md"
    md.write_text("just a body\n")
    skill = parse_skill(md, "dirname")
    assert skill.name == "dirname"
    assert skill.description == ""
    assert skill.body == "just a body"


def test_unclosed_frontmatter_treated_as_body(tmp_path):
    md = tmp_path / "SKILL.md"
    md.write_text("---\nname: x\nno closing fence\n")
    skill = parse_skill(md, "dirname")
    assert "no closing fence" in skill.body


def make_skill_dir(base: Path, name: str, description: str = "d"):
    d = base / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{name} body\n"
    )


def test_discovery_user_project_and_override(tmp_path):
    user = tmp_path / "user-skills"
    proj = tmp_path / "proj"
    make_skill_dir(user, "shared", "from user")
    make_skill_dir(user, "useronly")
    make_skill_dir(proj / ".agents" / "skills", "shared", "from project")

    skills = load_skills(cwd=proj, user_dir=user)
    assert set(skills) == {"shared", "useronly"}
    assert skills["shared"].description == "from project"  # project wins


def test_flat_md_file_is_a_skill(tmp_path):
    (tmp_path / ".agents" / "skills").mkdir(parents=True)
    (tmp_path / ".agents" / "skills" / "notes.md").write_text(
        "---\ndescription: take notes\n---\nbody\n"
    )
    skills = load_skills(cwd=tmp_path, user_dir=tmp_path / "nope")
    assert skills["notes"].description == "take notes"
