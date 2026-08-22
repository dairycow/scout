"""Skills: SKILL.md files with simple `key: value` frontmatter.

Discovered in ./.agents/skills/ (project) and ~/.agents/skills/ (user);
on a name clash the project skill wins. A skill is either:

    .agents/skills/<name>/SKILL.md    (a folder, may ship extra files)
    .agents/skills/<name>.md          (a single file)

Only name + description go into the system prompt; the model pulls the
full body on demand through the `skill` tool.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    body: str  # markdown below the frontmatter


def parse_skill(path: Path, fallback_name: str) -> Skill:
    lines = path.read_text().splitlines()
    meta: dict[str, str] = {}
    body_start = 0
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                body_start = i + 1
                break
            key, sep, value = line.partition(":")
            if sep:
                meta[key.strip().lower()] = value.strip()
    return Skill(
        name=meta.get("name") or fallback_name,
        description=meta.get("description", ""),
        path=path,
        body="\n".join(lines[body_start:]).strip(),
    )


def load_skills(cwd: Path = Path.cwd(),
                user_dir: Path | None = None) -> dict[str, Skill]:
    user_dir = user_dir or (Path.home() / ".agents" / "skills")
    skills: dict[str, Skill] = {}
    for d in (user_dir, cwd / ".agents" / "skills"):  # project loads last, wins
        if not d.is_dir():
            continue
        for child in sorted(d.iterdir()):
            if child.is_dir() and (child / "SKILL.md").is_file():
                skills[child.name] = parse_skill(child / "SKILL.md", child.name)
            elif child.is_file() and child.suffix == ".md":
                skills[child.stem] = parse_skill(child, child.stem)
    return skills
