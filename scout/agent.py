"""The agent loop as a pure emitter.

    user message -> model -> tool calls? -> run tools -> emit results
                 ^                                          |
                 +---------------------------<              |

The loop never writes history and never touches the filesystem. It reads
session.messages (kept current by a session plugin on the bus) and emits
message.* / tool.* events.

Multi-tool turns run in a thread pool when parallel_tools is on (the
default); worker threads only run registry.dispatch — every bus emit
stays on the main thread (the session store's sqlite connection is
check_same_thread=True). Results are reassembled in call order so the
API always sees the order it issued.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed


class Agent:
    def __init__(self, client, registry, system, session, ctx, bus):
        self.client = client          # llm client: complete(system, messages, tools,
                                      #                         on_text, on_usage)
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
        last_usage = None

        def on_usage(counts):
            nonlocal last_usage
            last_usage = counts

        for turn in range(n):
            last_usage = None
            message = self.client.complete(
                self.system, self.session.messages, self.registry.schemas(), on_text,
                on_usage=on_usage,
            )
            self.bus.emit("message.assistant", message=message, turn=turn + 1)
            if last_usage is not None:
                self.bus.emit(
                    "usage", model=self.ctx.config.get("model", ""), **last_usage
                )

            calls = [b for b in message["content"] if b["type"] == "tool_use"]
            if not calls:
                return "".join(
                    b["text"] for b in message["content"] if b["type"] == "text"
                )

            results = self._run_tools(calls)
            self.bus.emit("message.user", message={"role": "user", "content": results})

        return (
            f"stopped after {n} turns "
            "(raise max_turns if the task needs more)"
        )

    def _run_tools(self, calls: list) -> list:
        if len(calls) > 1 and self.ctx.config.get("parallel_tools"):
            return self._run_tools_parallel(calls)
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
        return results

    def _run_tools_parallel(self, calls: list) -> list:
        for call in calls:
            self.bus.emit("tool.start", name=call["name"], args=call["input"])
        executor = ThreadPoolExecutor(max_workers=min(len(calls), 8))
        try:
            futures = {
                executor.submit(
                    self.registry.dispatch, call["name"], call["input"], self.ctx
                ): i
                for i, call in enumerate(calls)
            }
            results = [None] * len(calls)
            for future in as_completed(futures):
                i = futures[future]
                call = calls[i]
                output, is_error = future.result()
                self.bus.emit(
                    "tool.end", name=call["name"], args=call["input"],
                    output=output, is_error=is_error,
                )
                results[i] = {
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": output,
                    "is_error": is_error,
                }
            executor.shutdown()
            return results
        except BaseException:
            # Ctrl-C mid-dispatch: abandon in-flight work, don't join it
            executor.shutdown(wait=False, cancel_futures=True)
            raise
