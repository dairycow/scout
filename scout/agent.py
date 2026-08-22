"""The agent loop. This is the heart of scout — the whole game is here:

    user message -> model -> tool calls? -> run tools -> append results
                 ^                                           |
                 +---------------------------<               |
        (repeat until the model replies with plain text) <---+

Everything else in the repo exists to feed this loop: llm/ turns the model
into a function, tools/ turns code into things the model can call, and
session.py remembers what happened.
"""

from .plugins import emit
from .tools import Ctx, Registry


class Agent:
    def __init__(self, client, registry: Registry, system: str, session,
                 ctx: Ctx, hooks: dict):
        self.client = client          # llm client: complete(system, messages, tools, on_text)
        self.registry = registry      # tool registry
        self.system = system          # system prompt (built once, never mutated)
        self.session = session        # message history + JSONL persistence
        self.ctx = ctx                # cwd/config/skills, passed to tools
        self.hooks = hooks            # plugin hooks

    def run(self, user_text: str, on_text=None) -> str:
        """Run one user message to completion; returns the final text."""
        self.session.append(
            {"role": "user", "content": [{"type": "text", "text": user_text}]}
        )
        for turn in range(self.ctx.config.max_turns):
            message = self.client.complete(
                self.system, self.session.messages, self.registry.schemas(), on_text
            )
            self.session.append(message)
            emit(self.hooks, "message_end", message=message, turn=turn + 1)

            calls = [b for b in message["content"] if b["type"] == "tool_use"]
            if not calls:
                return "".join(
                    b["text"] for b in message["content"] if b["type"] == "text"
                )

            results = []
            for call in calls:
                emit(self.hooks, "tool_start", name=call["name"], args=call["input"])
                output, is_error = self.registry.dispatch(
                    call["name"], call["input"], self.ctx
                )
                emit(
                    self.hooks,
                    "tool_end",
                    name=call["name"],
                    args=call["input"],
                    output=output,
                    is_error=is_error,
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "content": output,
                        "is_error": is_error,
                    }
                )
            self.session.append({"role": "user", "content": results})

        return (
            f"stopped after {self.ctx.config.max_turns} turns "
            "(raise max_turns if the task needs more)"
        )
