"""Tools: the agent's hands.

A Tool is a name, a description, a JSON Schema for its input object, and a
run(args, ctx) -> str function. The Registry holds them and converts them
to provider schemas. Tool errors never raise out of dispatch — they come
back to the model as an error string, which is how it learns to retry.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

MAX_OUTPUT = 30_000  # hard cap on any single tool result


def truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    """Keep the head and tail, drop the middle."""
    if len(text) <= limit:
        return text
    half = limit // 2
    cut = len(text) - limit
    return text[:half] + f"\n... [{cut} characters truncated] ...\n" + text[-half:]


@dataclass
class Ctx:
    """Everything a tool is allowed to know about the run."""
    cwd: Path
    config: dict          # plain dict (kernel may not import scout.config)
    skills: dict = field(default_factory=dict)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict                       # JSON Schema for the input object
    run: Callable[[dict, Ctx], str]        # raise ValueError for user errors


class Registry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}

    def register(self, *tools: Tool) -> None:
        for tool in tools:
            self.tools[tool.name] = tool  # later registration wins by name

    def schemas(self) -> list[dict]:
        """Provider-neutral tool list: {"name", "description", "input_schema"}."""
        return [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in self.tools.values()
        ]

    def dispatch(self, name: str, args: dict, ctx: Ctx) -> tuple[str, bool]:
        """Run a tool; always returns (output, is_error)."""
        tool = self.tools.get(name)
        if tool is None:
            return f"Error: unknown tool {name!r}", True
        try:
            return truncate(str(tool.run(args, ctx))), False
        except Exception as e:  # noqa: BLE001 — feed errors back to the model
            return f"Error: {e}", True

