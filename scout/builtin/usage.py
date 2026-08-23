"""Usage meter: per-turn token counts and session totals.

The agent emits `usage` right after each `message.assistant`; this prints
one line per turn (delta + running session total) on the display stream,
so `-p` mode flips it to stderr with everything else. Cache fields are
what verify the cache_control markup actually hits. /usage prints the
session totals on demand.
"""

from .display import _stream

FIELDS = (
    "input_tokens", "output_tokens",
    "cache_read_input_tokens", "cache_creation_input_tokens",
)
SHORT = {
    "input_tokens": "in", "output_tokens": "out",
    "cache_read_input_tokens": "cache_r", "cache_creation_input_tokens": "cache_w",
}


def scout(api) -> None:
    totals = dict.fromkeys(FIELDS, 0)

    def on_session_start(**_):
        for key in totals:
            totals[key] = 0

    def on_usage(**counts):
        parts = []
        for key in FIELDS:
            delta = counts.get(key, 0)
            totals[key] += delta
            parts.append(f"{SHORT[key]}={delta:,}")
        parts.append(f"session in={totals['input_tokens']:,} "
                     f"out={totals['output_tokens']:,}")
        print("tok " + " ".join(parts), file=_stream())

    def usage_cmd(agent, rest):
        print(
            f"session tokens: in={totals['input_tokens']:,} "
            f"out={totals['output_tokens']:,} "
            f"cache read={totals['cache_read_input_tokens']:,} "
            f"cache write={totals['cache_creation_input_tokens']:,}"
        )

    api.on("session.start", on_session_start)
    api.on("usage", on_usage)
    api.command("/usage", usage_cmd)
