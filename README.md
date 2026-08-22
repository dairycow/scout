# scout

A minimal terminal coding agent, small enough to read end-to-end.

scout exists to be understood. If you want to build your own agents, the
whole thing is ~1,200 lines of dependency-free Python — no SDKs, no
frameworks, no personality. Read every file in an afternoon, then hack on it.

    pip install git+https://github.com/dairycow/scout

- **Python 3.11+**, stdlib only (zero runtime dependencies)
- Anthropic and any OpenAI-compatible API (OpenAI, OpenRouter, Groq, Ollama, vLLM, ...)
- Tools: `bash`, `read`, `write`, `edit`, `grep`, `glob`, `skill`
- Skills and plugins discovered from the cross-tool `.agents/` directories
- Sessions persisted as JSONL, resumable

```bash
export ANTHROPIC_API_KEY=sk-...   # or OPENAI_API_KEY
scout                             # interactive REPL
scout -p "explain this repo"      # headless: one prompt, print answer, exit
scout -c                          # resume the latest session
```

## How it works

```
        cli.py  ── REPL / -p headless / -c resume
           │
           ▼        builds once at startup
      ┌──────────────────────────────────────────┐
      │  config ─ agent ─ session (JSONL on disk) │
      │            │    ▲                         │
      │            │    │ normalized messages     │
      │            ▼    │                         │
      │  llm/anthropic · llm/openai ── http.py    │
      │            │        (SSE over urllib)     │
      │            ▼ tool calls                   │
      │  tools/ (registry) ◄── plugins.py         │
      │  bash read write edit grep glob skill     │
      └──────────────────────────────────────────┘
           ▲                              ▲
      context.py (system prompt)     skills.py (.agents/skills/)
```

The whole game is `agent.py` (~50 lines):

```
user message → model → tool calls? → run tools → append results → model → ...
          (repeat until the model replies with plain text)
```

Messages are normalized to Anthropic's format everywhere inside scout:

```json
[{"role": "user",
  "content": [
    {"type": "text", "text": "..."},
    {"type": "tool_use", "id": "...", "name": "bash", "input": {"command": "ls"}},
    {"type": "tool_result", "tool_use_id": "...", "content": "exit code: 0", "is_error": false}
  ]}]
```

`llm/openai.py` is the only place that translates to a different wire format,
which keeps everything else symmetric and simple.

## Read the source in this order

| Order | File | ~LOC | What you'll learn |
|---|---|---|---|
| 1 | `scout/cli.py` | 165 | entry point, REPL, headless mode |
| 2 | `scout/agent.py` | 70 | the loop — the heart of any agent |
| 3 | `scout/llm/__init__.py` | 40 | the one-method client contract |
| 4 | `scout/llm/anthropic.py` | 80 | streaming SSE → assembled messages |
| 5 | `scout/llm/openai.py` | 125 | same thing for Chat Completions |
| 6 | `scout/tools/__init__.py` | 80 | tools, registry, error feedback |
| 7 | `scout/tools/*.py` | 315 | the seven built-ins |
| 8 | `scout/session.py` | 45 | JSONL persistence = resume for free |
| 9 | `scout/context.py` | 85 | system prompt assembly |
| 10 | `scout/skills.py` | 60 | SKILL.md discovery + frontmatter |
| 11 | `scout/plugins.py` | 70 | the three-method plugin API |
| 12 | `scout/config.py` | 65 | layered configuration |
| 13 | `scout/http.py` | 40 | the entire network layer |

## Configuration

Precedence: defaults `<` `~/.config/scout/scout.toml` `<` `./scout.toml`
`<` `SCOUT_*` environment `<` CLI flags.

| Key | Default | CLI / env | Meaning |
|---|---|---|---|
| `provider` | `anthropic` | `--provider` / `SCOUT_PROVIDER` | `anthropic` or `openai` (any compatible API) |
| `model` | `claude-sonnet-4-5` | `--model` / `SCOUT_MODEL` | model name |
| `base_url` | *(provider default)* | `--base-url` / `SCOUT_BASE_URL` | e.g. `https://openrouter.ai/api/v1`, `http://localhost:11434/v1` |
| `api_key` | env | `--api-key` / `SCOUT_API_KEY` | else `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` |
| `max_tokens` | `4096` | `--max-tokens` | per response |
| `max_turns` | `40` | `--max-turns` | tool-loop guard per user message |
| `timeout` | `300` | — | seconds per HTTP request |

Any OpenAI-compatible endpoint works by pointing `base_url` at it.

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

A plugin is a Python file exposing `scout(api)` with three methods:

```python
from scout.tools import Tool

def scout(api):
    api.register_tool(Tool(           # 1. add or replace a tool
        name="deploy",
        description="Deploy the current branch.",
        parameters={"type": "object", "properties": {}},
        run=deploy,
    ))
    api.on("tool_end", logger)        # 2. subscribe to hooks:
                                      #    session_start(cwd, model)
                                      #    tool_start(name, args)
                                      #    tool_end(name, args, output, is_error)
                                      #    message_end(message, turn)
    api.prompt("Deploy only on request.")  # 3. append to the system prompt
```

Loaded from `~/.agents/plugins/` then `./.agents/plugins/`. A broken plugin
is skipped with a warning, never fatal. See `examples/plugins/`.

## Project instructions

`./AGENTS.md` is injected into the system prompt if present (truncated at
8,000 chars), falling back to `~/.agents/AGENTS.md`.

## Layout recap

```
scout/            the package (start in cli.py)
tests/            offline test suite (fake clients, no network)
examples/plugins/ hello tool, tool logger
examples/skills/  commit skill
```

## Not in v1 (on purpose)

context compaction · MCP · permission prompts · TUI · token accounting ·
pip entry-point plugins. Each is a small, well-scoped change to one file —
good first patches.

## License

MIT
