"""Session: the message list, plus JSONL persistence under .scout/sessions/.

One line per message; the whole session history is therefore both the
transcript on disk and the context sent to the model.
"""

import json
import os
import time
from pathlib import Path


class Session:
    def __init__(self, messages: list | None = None, path: Path | None = None):
        self.messages: list[dict] = messages or []
        self.path = path  # None until saved

    def append(self, message: dict) -> None:
        self.messages.append(message)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(message, ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, path: Path) -> "Session":
        messages = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return cls(messages, path)

    @classmethod
    def latest(cls, cwd: Path = Path.cwd()) -> "Session | None":
        """Most recently created session in cwd, or None."""
        sessions = cwd / ".scout" / "sessions"
        files = sorted(sessions.glob("*.jsonl")) if sessions.is_dir() else []
        return cls.load(files[-1]) if files else None


def new_session(cwd: Path = Path.cwd()) -> Session:
    sessions = cwd / ".scout" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Session([], sessions / f"{stamp}-{os.getpid()}.jsonl")
