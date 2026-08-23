# scout

A minimal terminal coding agent, small enough to read end-to-end.

scout exists to be understood. If you want to build your own agents, the
whole thing is ~1,800 lines of dependency-free Python — no SDKs, no
frameworks, no personality. Read every file in an afternoon, then hack on it.

    pip install scout-harness            # or: pip install git+https://github.com/dairycow/scout

- **Python 3.11+**, stdlib only (zero runtime dependencies)
- Anthropic and any OpenAI-compatible API (OpenAI, OpenRouter, Groq, Ollama, vLLM, ...)
- Tools: `bash`, `read`, `write`, `edit`, `grep`, `glob`, `skill`
- Skills and plugins discovered from the cross-tool `.agents/` directories
- Sessions persisted in `~/.scout/store.db`, resumable

```bash
export ANTHROPIC_API_KEY=sk-...   # or OPENAI_API_KEY
scout                             # interactive REPL
scout -p "explain this repo"      # headless: one prompt, print answer, exit
scout -c                          # resume the latest session
```

## Read the source in this order

Kernel first, then builtins, then the store. The afternoon ends at
`builtin/` — each plugin is one file you can read, replace, or delete.

| Order | File | ~LOC | What you'll learn |
|---|---|---|---|
| 1 | `scout/bus.py` | 30 | event bus — `emit` / `on`, open vocabulary |
| 2 | `scout/host.py` | 150 | boot, PluginApi, registries, three seams |
| 3 | `scout/agent.py` | 115 | the loop as a pure emitter; parallel tool dispatch |
| 4 | `scout/cli.py` | 115 | args, REPL shell, `-p` / `-c` |
| 5 | `scout/builtin/` | ~1,200 | 11 internal plugins, one file each, deletable |
| 6 | `scout/builtin/session.py` | 210 | append-only events + projection; fork/resume as queries |

The rest of the kernel is `tools.py` (Tool / Registry / Ctx), `http.py`
(the entire network layer), and `errors.py`.

## Architecture

The kernel is ~570 lines and knows nothing: no sqlite, no toml, no
builtins except three one-line seams. Everything else is a plugin on one
API — scout's own features use the same `PluginApi` user plugins do.

```
        cli.py  ── REPL / -p headless / -c resume
           │
           ▼  host.boot()
      ┌──────────────────────────────────────────┐
      │  host.py  (registries + PluginApi)       │
      │    builtin manifest, then .agents/       │
      └──────────────┬───────────────────────────┘
                     │
                     ▼
              agent.py  (pure emitter)
                     │  message.* / tool.*
                     ▼
                  bus.py
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
     session.py  display.py  user plugins
     (events +                (.agents/)
      messages)
          │
          ▼
     ~/.scout/store.db
```

The whole game is still `agent.py` (~115 lines):

```
user message → model → tool calls? → run tools → emit results → model → ...
          (repeat until the model replies with plain text)
```

The loop holds no file handle and no database. Even persistence is a bus
subscription. Messages are normalized to Anthropic's format everywhere
inside scout; `builtin/providers/openai.py` is the only place that
translates to a different wire format.

A turn with several tool calls runs them concurrently (`parallel_tools`,
default on; `--no-parallel-tools` to disable) — the API still sees
results in the order it issued the calls. Right after every
`message.assistant` the agent emits `usage` with that turn's token
counts (including Anthropic cache hit/creation); `builtin/usage.py`
prints the `tok=` line and backs `/usage`. Transient HTTP failures
(429/5xx) are retried with backoff before the stream starts —
`retries` (default 2), `Retry-After` honored.

### PluginApi

| Method | What it does |
|---|---|
| `tool(tool)` | register or replace a tool by name (later wins) |
| `on(event, fn)` | subscribe to any event (open vocabulary) |
| `prompt(text)` | append a paragraph to the system prompt |
| `command(name, fn)` | REPL command; `fn(agent, rest_of_line)` |
| `provider(name, factory)` | `factory(config) → client`; selectable via config. Clients implement `complete(system, messages, tools, on_text=None, on_usage=None)` and call `on_usage(dict)` once at stream end |
| `config(defaults)` | declare config keys + defaults |
| `emit(type, **data)` | emit any event on the bus |

```python
# ~/.agents/plugins/deploy.py
from scout.tools import Tool

def deploy_now(agent, rest): ...

def scout(api):
    api.provider("groq", lambda cfg: openai_compat(
        base_url="https://api.groq.com/openai/v1", cfg))
    api.command("/deploy", deploy_now)
    api.tool(Tool(name="deploy", description="Deploy the current branch.",
                  parameters={"type": "object", "properties": {}}, run=deploy))
    api.on("tool.end", lambda name, **_: print(f"done: {name}"))
    api.prompt("Deploy only when explicitly asked.")
```

### Events are the only memory

`~/.scout/store.db` has two tables: `events` (the truth — append-only,
never updated or deleted) and `messages` (a projection). The projector
is one rule set: `message.user` / `message.assistant` append a row;
`session.fork` copies the parent's prefix (`n <= at_n`) into the new
session; everything else is events-only. Fork is a projector rule, not a
copy job, which is what makes the projection a pure function of the log.
`scout -c` is a query (newest `session.start` / `session.fork` for this
directory). `rebuild()` drops `messages` and replays `events`.

### Three declared seams

The host imports three factories from `builtin/` — the only
kernel→builtin coupling:

| Seam | Provided by |
|---|---|
| `open_session(cwd, config, resume)` | `builtin/session.py` |
| `build_prompt(registry, skills, cwd, paragraphs, config)` | `builtin/prompt.py` |
| `load_skills(cwd)` | `builtin/skills.py` |

Everything else flows through PluginApi.

## Configuration

Precedence: plugin defaults `<` `~/.config/scout/scout.toml` `<` `./scout.toml`
`<` `SCOUT_*` environment `<` CLI flags.

| Key | Default | CLI / env | Meaning |
|---|---|---|---|
| `provider` | `anthropic` | `--provider` / `SCOUT_PROVIDER` | `anthropic` or `openai` (any compatible API) |
| `model` | `claude-sonnet-4-5` | `--model` / `SCOUT_MODEL` | model name |
| `base_url` | *(provider default)* | `--base-url` / `SCOUT_BASE_URL` | e.g. `https://openrouter.ai/api/v1`, `http://localhost:11434/v1` |
| `api_key` | env | `--api-key` / `SCOUT_API_KEY` | else `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` |
| `max_tokens` | `16384` | `--max-tokens` | per response |
| `max_turns` | `40` | `--max-turns` | tool-loop guard per user message |
| `timeout` | `300` | — | seconds per HTTP request |
| `retries` | `2` | `--retries` / `SCOUT_RETRIES` | retry attempts for transient HTTP 429/5xx/URLError, pre-stream only; `Retry-After` honored |
| `parallel_tools` | `true` | `--no-parallel-tools` / `SCOUT_PARALLEL_TOOLS` | run a turn's tool calls concurrently (bool envs: true/false/1/0) |

Any OpenAI-compatible endpoint works by pointing `base_url` at it.
Plugins declare extra keys with `api.config({...})`; those join the same
layering.

## Skills

A skill is a markdown file of instructions. Only its name and description
enter the system prompt; the model loads the full body on demand with the
`skill` tool, so skills cost almost nothing until used.

```
~/.agents/skills/commit/SKILL.md      user-level
./.agents/skills/commit/SKILL.md      project-level (wins on name clash)
./.agents/skills/notes.md             flat files work too
```

```markdown
---
name: commit
description: How to prepare and create git commits in this repo.
---

# Committing
1. Run git status and git diff --stat first.
...
```

## Plugins

A plugin is a Python file exposing `scout(api)`. Internal plugins and
`~/.agents/plugins/*.py` get the same PluginApi (table above). Loaded
from `~/.agents/plugins/` then `./.agents/plugins/`; later registration
wins by name, so a user plugin can replace a built-in tool or command. A
broken plugin is skipped with a warning, never fatal. See
`examples/plugins/`.

The statusline is the pattern in miniature: `builtin/statusline.py` keeps
a bag of named slots, updates them on `session.start` and
`message.assistant`, and prints one dim line (`model=… turns=…`) when a
turn completes. Any plugin can extend it by emitting slots onto
`session.start` — the renderer is just `print()`.

## Project instructions

`./AGENTS.md` is injected into the system prompt if present (truncated at
8,000 chars), falling back to `~/.agents/AGENTS.md`.

## Development

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[dev]'
uv run pytest -q
```

The suite is offline (fake clients, no network). CI runs it on Python
3.11, 3.12, and 3.13. Kernel purity (`tests/test_kernel_purity.py` —
no sqlite/toml in the kernel, builtin imports only at the three seams)
and projector determinism (`tests/test_session_store.py` — incremental
projection equals `rebuild()`, row for row) are release gates.

## Layout recap

```
scout/            the kernel (start in bus.py)
scout/builtin/    11 internal plugins, same API as user plugins
tests/            offline test suite (fake clients, no network)
examples/plugins/ hello tool, tool logger (Plugin API v2)
examples/skills/  commit skill
```

## Not in v2 (on purpose)

context compaction · MCP · permission prompts · TUI ·
pip entry-point plugins. Each is a plugin-sized change to one file —
good first patches.

## License

MIT
