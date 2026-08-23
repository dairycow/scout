"""One dim status line per completed user turn.

The footer is a bag of named slots any plugin can write — the pi-mono
model, minus the tick loop. Slots update on `session.start` and
`message.assistant`; the line prints once per user turn (on the
assistant message with no tool calls, so long tool loops stay quiet).
Same stream flip as `display.py`: one-way to stderr in `-p` mode.
"""

from .display import _stream, _set_stderr

_DIM = "\x1b[2m"
_RESET = "\x1b[0m"


def _paint(line: str) -> str:
    return f"{_DIM}{line}{_RESET}" if _is_tty() else line


def _is_tty() -> bool:
    try:
        return _stream().isatty()
    except Exception:  # noqa: BLE001 — capture wrappers may not proxy isatty
        return False


_slots: dict[str, str] = {}


def scout(api) -> None:
    _set_stderr(False)
    _slots.clear()

    def on_start(**data):
        for key in ("model", "branch", "cwd", "session"):
            value = data.get(key, "")
            if value:
                _slots[key] = value
        _slots.pop("turns", None)
        _slots.pop("msg", None)

    def on_assistant(message, turn, **_):
        _slots["turns"] = str(turn)
        _slots["msg"] = str(len(message.get("content", [])))
        if any(b.get("type") == "tool_use" for b in message.get("content", [])):
            return  # mid-loop; print on the final (no-tool) message
        text = "".join(
            b.get("text", "") for b in message.get("content", [])
            if b.get("type") == "text"
        )
        # streamed answers leave the cursor mid-line; start our own line
        lead = "" if not text or text.endswith("\n") else "\n"
        print(lead + _paint(_render()), file=_stream())

    def to_stderr(**_):
        _set_stderr(True)

    api.on("session.start", on_start)
    api.on("message.assistant", on_assistant)
    api.on("display.stderr", to_stderr)


def _render() -> str:
    order = ("model", "branch", "session", "turns", "msg")
    known = [f"{k}={_slots[k]}" for k in order if k in _slots]
    extra = [f"{k}={v}" for k, v in _slots.items() if k not in order]
    return " ".join(known + extra)
