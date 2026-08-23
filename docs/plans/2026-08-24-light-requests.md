# Scout perf PR — light tool outputs (2026-08-24)

Follow-up to the perf branch (retries, usage metering, parallel tools).
Decision 2026-08-24: ship **A only** (per-line caps). C (O(1)
`_with_cache_control`) deferred; B (request-side compaction) rejected
for now on the evidence below.

## Evidence — session `2028b0fc…` (this cwd, 2026-08-23T20:24, 40 turns)

The usage meter built earlier in this branch made it possible to read
real numbers off `~/.scout/store.db`:

| Metric | Value |
|---|---|
| Final history | 81 messages, 106,369 chars (~28k tokens) |
| Tool-result share of history | **74%** (bash: 49 calls / 42k chars; read: 8 / 37k; glob: 1 / 159) |
| Cache hit rate | ~695k of 725k input tokens read from cache (**95%**) |
| Per-turn uncached gap (`in − cache_r`) | tracks the previous turn's new tool output (msg 5's 15.8k-char read → next turn gap ≈ 4k tok) |
| Cumulative prefix re-upload | 4.63 MB over the session (O(n²), inherent to the protocol) |
| Largest single tool output | 8,957 chars — nothing ever reached the 30k `MAX_OUTPUT` cap |
| Longest single line in any tool result | 1,520 chars |

Readings:

- The moving `cache_control` breakpoint works; billing is already 95%
  mitigated. Compaction (B) has nothing to reclaim — deferred until the
  meter shows the uncached gap or `in=` drifting up.
- Tightening `MAX_OUTPUT` would have saved zero bytes this session —
  no result came near it. Not touched.
- The one real gap is **line length**: `truncate()` keeps head+tail of
  the whole output, so a minified/one-line file or a grep over one
  yields two ~15k-char half-lines of noise. Not observed yet (max
  1,520) — cheap insurance.

## Product decisions (locked 2026-08-24)

| Question | Decision |
|---|---|
| Scope | A only; C deferred to a later PR |
| Caps | read: 2,000 chars/line; grep: 500 chars/matched line; glob: none |
| Config knobs | None — fixed constants beside `MAX_OUTPUT` |

## Method

Two commits, each leaves `uv run pytest -q` and `uv run ruff check`
green. LOC budget: this is a fresh PR (~+10 over 1,771; the old ±20%
ceiling from 2026-08-23-perf.md is spent).

## Commit 2 — line caps

- `scout/tools.py`: `clip_line(text, limit)` beside `truncate` —
  single home for output-shaping policy. Returns the line unchanged if
  within `limit`, else `text[:limit] + f"… [+{n} chars]"`.
- `builtin/tools/read.py`: clip each line to 2,000 chars **after**
  numbering (number + marker both visible). Offset/limit/footer logic
  untouched.
- `builtin/tools/search.py`: `_grep` clips the matched line (already
  `.strip()`ed) to 500 chars. `_glob` untouched — file paths are short.
- Tests (`tests/test_tools.py`, beside `test_truncate`):
  - `read` on a file with a 10k-char line → clipped, marker present,
    numbering intact, total length bounded.
  - `grep` with a long matched line → clipped at 500.
  - `clip_line` unit: short line unchanged.

## Out of scope

- C — `_with_cache_control` deep-copies full history per request
  (`builtin/providers/anthropic.py:23`); O(history) client CPU per
  turn. Value-test pinned by two existing tests; deferred.
- B — request-side compaction of old `tool_result` bodies.
- `MAX_OUTPUT` tightening.

## Invariants

- Kernel purity gate green: `clip_line` is a pure helper in
  `scout/tools.py`, no new kernel→builtin imports.
- Store untouched; `messages` stays a pure projection of the log.
- Existing `test_truncate` and all read/grep tests stay green
  unchanged (caps only fire on pathological lines).

## Final status

(to fill at merge)
