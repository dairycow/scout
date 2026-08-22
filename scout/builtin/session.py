"""In-memory session. The SQLite event store lands in Phase 2."""

import uuid
from dataclasses import dataclass, field


@dataclass
class MemorySession:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    messages: list = field(default_factory=list)


def open_session(cwd, config, resume: bool) -> MemorySession:
    return MemorySession()


def scout(api) -> None:
    pass
