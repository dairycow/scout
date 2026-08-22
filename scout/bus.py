"""Event bus: open-vocabulary, synchronous, error-isolated.

Any dotted lowercase name is legal. Subscribers run in subscription order
on the calling thread. A raising subscriber is reported to stderr and
skipped — never fatal, later subscribers still run.
"""

import sys


class Bus:
    def __init__(self):
        self._subs: dict[str, list] = {}

    def on(self, type: str, fn) -> None:
        self._subs.setdefault(type, []).append(fn)

    def emit(self, type: str, **data) -> None:
        for fn in self._subs.get(type, ()):
            try:
                fn(**data)
            except Exception as e:  # noqa: BLE001 — plugins must not kill the agent
                print(f"scout: {type} subscriber failed: {e}", file=sys.stderr)
        if type == "*":
            return
        for fn in self._subs.get("*", ()):
            try:
                fn(type=type, **data)
            except Exception as e:  # noqa: BLE001
                print(f"scout: {type} subscriber failed: {e}", file=sys.stderr)
