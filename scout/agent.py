"""The agent loop as a pure emitter.

    user message -> model -> tool calls? -> run tools -> emit results
                 ^                                          |
                 +---------------------------<              |

The loop never writes history and never touches the filesystem. It reads
session.messages (kept current by a session plugin on the bus) and emits
message.* / tool.* events.
"""


class Agent:
    def __init__(self, client, registry, system, session, ctx, bus):
        self.client = client          # llm client: complete(system, messages, tools, on_text)
        self.registry = registry      # tool registry
        self.system = system          # system prompt (built once, never mutated)
        self.session = session        # read-only view; session plugin keeps it current
        self.ctx = ctx                # cwd/config/skills, passed to tools
        self.bus = bus

    def run(self, user_text: str, on_text=None) -> str:
        """Run one user message to completion; returns the final text."""
        self.bus.emit(
            "message.user",
            message={"role": "user", "content": [{"type": "text", "text": user_text}]},
        )
        n = self.ctx.config["max_turns"]
        for turn in range(n):
            message = self.client.complete(
                self.system, self.session.messages, self.registry.schemas(), on_text
            )
            self.bus.emit("message.assistant", message=message, turn=turn + 1)

            calls = [b for b in message["content"] if b["type"] == "tool_use"]
            if not calls:
                return "".join(
                    b["text"] for b in message["content"] if b["type"] == "text"
                )

            results = []
            for call in calls:
                name, args = call["name"], call["input"]
                self.bus.emit("tool.start", name=name, args=args)
                output, is_error = self.registry.dispatch(name, args, self.ctx)
                self.bus.emit(
                    "tool.end", name=name, args=args, output=output, is_error=is_error
                )
                results.append({
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": output,
                    "is_error": is_error,
                })
            self.bus.emit("message.user", message={"role": "user", "content": results})

        return (
            f"stopped after {n} turns "
            "(raise max_turns if the task needs more)"
        )
