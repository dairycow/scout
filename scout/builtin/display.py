"""Print one line per tool call.

Default stream is stdout. The CLI emits `display.stderr` (no data) in `-p`
mode before running, flipping the stream one-way to stderr so the answer
stays alone on stdout.

Stream objects are resolved at print time (a flag, not a saved file
handle) so a stale sys.stdout snapshot cannot outlive pytest's capture
wrapper.
"""

import sys

_stderr = False


def _stream():
    return sys.stderr if _stderr else sys.stdout


def _set_stderr(value: bool) -> None:
    global _stderr
    _stderr = value


def scout(api) -> None:
    _set_stderr(False)

    def tool_start(name, args, **_):
        print(f"[{name}] {str(args)[:120]}", file=_stream())

    def tool_end(name, output, is_error, **_):
        first = output.splitlines()[0][:120] if output else "(no output)"
        mark = "!" if is_error else ""
        print(f"[{name}]{mark} {first}", file=_stream())

    def to_stderr(**_):
        _set_stderr(True)

    api.on("tool.start", tool_start)
    api.on("tool.end", tool_end)
    api.on("display.stderr", to_stderr)
