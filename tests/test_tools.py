"""Tests for the built-in tools and the registry."""

import pytest

from scout.config import Config
from scout.skills import Skill
from scout.tools import Ctx, Registry, Tool, builtins, truncate


@pytest.fixture
def ctx(tmp_path):
    return Ctx(cwd=tmp_path, config=Config(), skills={})


@pytest.fixture
def reg():
    r = Registry()
    r.register(*builtins())
    return r


def run(reg, ctx, name, args):
    return reg.dispatch(name, args, ctx)


def test_registry_registers_and_overrides(reg):
    reg.register(*builtins())
    assert [t["name"] for t in reg.schemas()][0] == "bash"

    replacement = Tool("bash", "overridden", {"type": "object"}, lambda a, c: "x")
    reg.register(replacement)
    assert reg.tools["bash"] is replacement


def test_unknown_tool(reg, ctx):
    output, is_error = run(reg, ctx, "nope", {})
    assert is_error and "unknown tool" in output


def test_bash_success(reg, ctx):
    output, is_error = run(reg, ctx, "bash", {"command": "echo hello"})
    assert not is_error
    assert "exit code: 0" in output and "hello" in output


def test_bash_failure_is_not_agent_error(reg, ctx):
    output, is_error = run(reg, ctx, "bash", {"command": "exit 3"})
    assert not is_error  # nonzero exit is information, not an exception
    assert "exit code: 3" in output


def test_bash_timeout(reg, ctx):
    output, is_error = run(reg, ctx, "bash", {"command": "sleep 5", "timeout": 1})
    assert is_error and "timed out" in output


def test_read_numbered_lines(reg, ctx, tmp_path):
    (tmp_path / "f.txt").write_text("alpha\nbeta\ngamma\n")
    output, _ = run(reg, ctx, "read", {"path": "f.txt", "offset": 2, "limit": 1})
    assert output.startswith("2: beta")
    assert "1 more lines; use offset=3" in output
    output, _ = run(reg, ctx, "read", {"path": "f.txt"})
    assert output == "1: alpha\n2: beta\n3: gamma"


def test_read_missing_file(reg, ctx):
    _, is_error = run(reg, ctx, "read", {"path": "nope.txt"})
    assert is_error


def test_write_creates_dirs(reg, ctx, tmp_path):
    _, is_error = run(reg, ctx, "write", {"path": "a/b/c.txt", "content": "x\ny"})
    assert not is_error
    assert (tmp_path / "a" / "b" / "c.txt").read_text() == "x\ny"


def test_edit_unique_replace(reg, ctx, tmp_path):
    (tmp_path / "f.txt").write_text("one two three")
    output, is_error = run(reg, ctx, "edit", {"path": "f.txt",
                                              "old_string": "two", "new_string": "2"})
    assert not is_error
    assert (tmp_path / "f.txt").read_text() == "one 2 three"


def test_edit_not_found(reg, ctx, tmp_path):
    (tmp_path / "f.txt").write_text("one")
    output, is_error = run(reg, ctx, "edit", {"path": "f.txt",
                                              "old_string": "zzz", "new_string": "x"})
    assert is_error and "not found" in output


def test_edit_ambiguous_requires_replace_all(reg, ctx, tmp_path):
    (tmp_path / "f.txt").write_text("a a a")
    _, is_error = run(reg, ctx, "edit", {"path": "f.txt", "old_string": "a", "new_string": "b"})
    assert is_error
    output, is_error = run(reg, ctx, "edit", {"path": "f.txt", "old_string": "a",
                                              "new_string": "b", "replace_all": True})
    assert not is_error
    assert (tmp_path / "f.txt").read_text() == "b b b"


def test_grep_and_glob(reg, ctx, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("hello world\nnothing\n")
    (tmp_path / "src" / "b.txt").write_text("hello again\n")

    output, _ = run(reg, ctx, "grep", {"pattern": "hello"})
    assert "src/a.py:1: hello world" in output and "src/b.txt:1: hello again" in output

    output, _ = run(reg, ctx, "grep", {"pattern": "hello", "include": "*.py"})
    assert "a.py" in output and "b.txt" not in output

    output, _ = run(reg, ctx, "glob", {"pattern": "src/*.py"})
    assert output == "src/a.py"

    output, _ = run(reg, ctx, "grep", {"pattern": "zzz"})
    assert output == "no matches"


def test_grep_stops_at_200(reg, ctx, tmp_path):
    (tmp_path / "big.txt").write_text("\n".join(["hit"] * 250))
    output, _ = run(reg, ctx, "grep", {"pattern": "hit"})
    assert "stopped at 200" in output


def test_skill_tool(ctx, tmp_path):
    ctx.skills["commit"] = Skill("commit", "how to commit", tmp_path / "SKILL.md",
                                 "body of skill")
    reg = Registry()
    reg.register(*builtins())
    output, _ = run(reg, ctx, "skill", {"name": "commit"})
    assert output == "body of skill"
    output, is_error = run(reg, ctx, "skill", {"name": "nope"})
    assert is_error and "commit" in output  # suggests what exists


def test_truncate():
    assert truncate("short") == "short"
    long = "x" * 100
    out = truncate(long, limit=10)
    assert len(out) < 100 and "characters truncated" in out
    assert out.startswith("xxxxx") and out.endswith("xxxxx")
