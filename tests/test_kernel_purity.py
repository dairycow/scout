"""Kernel purity: no sqlite3/tomllib, and builtin imports only at the three seams."""

import ast
from pathlib import Path

import scout

ROOT = Path(scout.__file__).parent
BANNED = {"sqlite3", "tomllib"}
SEAMS = {"session", "prompt", "skills"}


def _kernel_modules():
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if rel.parts[0] == "builtin":
            continue
        yield path


def _top(name: str) -> str:
    return name.split(".")[0] if name else ""


def _builtin_seams(node) -> list[str]:
    """Seam names referenced by a static import of scout.builtin ('' = package)."""
    found = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name == "scout.builtin" or alias.name.startswith("scout.builtin."):
                found.append(alias.name[len("scout.builtin"):].lstrip("."))
    elif isinstance(node, ast.ImportFrom):
        mod = node.module or ""
        names = [a.name for a in node.names]
        if node.level == 0:
            if mod == "scout.builtin" or mod.startswith("scout.builtin."):
                found.append(mod[len("scout.builtin"):].lstrip("."))
            elif mod == "scout" and any(n == "builtin" or n.startswith("builtin.") for n in names):
                found.append("")
        else:
            if mod == "builtin" or mod.startswith("builtin."):
                found.append(mod[len("builtin"):].lstrip("."))
            elif not mod and any(n == "builtin" or n.startswith("builtin.") for n in names):
                found.append("")
    return found


def test_kernel_purity():
    violations = []
    for path in _kernel_modules():
        tree = ast.parse(path.read_text(), filename=str(path))
        rel = path.relative_to(ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _top(alias.name) in BANNED:
                        violations.append(f"{rel}:{node.lineno} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if _top(node.module or "") in BANNED:
                    violations.append(f"{rel}:{node.lineno} imports {node.module}")
            seams = _builtin_seams(node)
            if not seams:
                continue
            if rel != Path("host.py"):
                violations.append(f"{rel}:{node.lineno} imports scout.builtin ({seams})")
            else:
                for seam in seams:
                    if seam not in SEAMS:
                        violations.append(
                            f"{rel}:{node.lineno} host may only import "
                            f"session/prompt/skills, got {seam!r}"
                        )
    assert violations == []
