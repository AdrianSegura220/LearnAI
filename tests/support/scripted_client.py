"""Real SDK over a strict, in-memory HTTP transport; never reaches a network."""
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any

import anthropic
import httpx2


class FakeMonotonic:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(seconds)


@dataclass
class Reply:
    content: list[dict[str, Any]]
    output_tokens: int = 40
    elapsed: float = 0.0
    status: int = 200
    stop_reason: str | None = None
    stream_elapsed: float = 0.0
    stream_error: bool = False
    initial_output_tokens: int = 2
    stream_truncated: bool = False


def tool(name: str, arguments: Any = None, *, id: str | None = None) -> dict:
    result = {"type": "tool_use", "name": name, "input": {} if arguments is None else arguments}
    if id is not None:
        result["id"] = id
    return result


def final(message: str = "Compare your two lines.", rung: str = "NUDGE", *, submit: bool = True,
          output_tokens: int = 40, elapsed: float = 0.0) -> Reply:
    value = {"message": message, "rung_used": rung}
    return Reply([tool("submit_turn", value)] if submit else [
        {"type": "text", "text": json.dumps(value)}], output_tokens, elapsed)


class ScriptedAnthropic:
    """Validate each conversation prefix and tool pairing before returning a reply."""
    def __init__(self, replies: Sequence[Reply], *, clock: FakeMonotonic | None = None) -> None:
        self.replies = list(replies)
        self.clock = clock or FakeMonotonic()
        self.requests: list[dict[str, Any]] = []
        self.timeouts: list[dict[str, float]] = []
        self.responses: list[dict[str, Any]] = []
        self._prefixes: dict[str, list[dict]] = {}
        self._static: dict[str, tuple[list, list]] = {}
        self.client = anthropic.Anthropic(api_key="scripted-key", max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self._handle)))

    def _validate(self, request: dict) -> str:
        messages = request["messages"]
        assert messages and messages[0]["role"] == "user", "missing original context"
        key = json.dumps(messages[0], sort_keys=True)
        previous = self._prefixes.get(key)
        if previous is not None:
            assert messages[:len(previous)] == previous, "continuation rewrote/lost original history"
        static = request["system"], request["tools"]
        if key in self._static:
            assert static == self._static[key], "continuation rewrote policy or tool schemas"
        self._static[key] = deepcopy(static)
        pending: list[str] = []
        call_ids: set[str] = set()
        for message in messages:
            blocks = message["content"] if isinstance(message["content"], list) else []
            results = [b["tool_use_id"] for b in blocks if b["type"] == "tool_result"]
            if pending:
                assert message["role"] == "user" and results == pending, "missing/reordered tool results"
                assert all(b["type"] == "tool_result" for b in blocks[:len(pending)]), "results must precede text"
                pending = []
            else:
                assert not results, "unexpected tool results"
            calls = [b["id"] for b in blocks if b["type"] == "tool_use"]
            if calls:
                assert message["role"] == "assistant"
                assert len(set(calls)) == len(calls) and not call_ids.intersection(calls)
                call_ids.update(calls)
                pending = calls
        assert not pending, "orphan tool calls"
        assert request["tool_choice"]["type"] in {"auto", "none"}
        return key

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        key = self._validate(payload)
        self.requests.append(payload)
        self.timeouts.append(dict(request.extensions.get("timeout", {})))
        assert self.replies, "unexpected provider attempt"
        reply = self.replies.pop(0)
        self.clock.advance(reply.elapsed)
        if reply.status != 200:
            return httpx2.Response(reply.status, json={"type": "error", "error": {
                "type": "api_error", "message": "scripted failure"}}, headers={"request-id": f"req-{len(self.requests)}"})
        content = deepcopy(reply.content)
        if payload["tool_choice"]["type"] == "none":
            assert not any(b["type"] == "tool_use" for b in content), "script violates disabled tool choice"
        for index, block in enumerate(content):
            if block["type"] == "tool_use":
                block.setdefault("id", f"tool-{len(self.requests)}-{index}")
        response = {"id": f"msg-{len(self.requests)}", "type": "message", "role": "assistant",
            "model": payload["model"], "content": content,
            "stop_reason": reply.stop_reason or ("tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"),
            "stop_sequence": None, "usage": {"input_tokens": 100, "output_tokens": reply.output_tokens,
                "cache_creation_input_tokens": 20, "cache_read_input_tokens": 80}}
        self.responses.append(response)
        self._prefixes[key] = deepcopy(payload["messages"]) + [{"role": "assistant", "content": content}]
        if payload.get("stream"):
            events = [{"type": "message_start", "message": {**response, "content": [],
                "stop_reason": None, "usage": {**response["usage"], "output_tokens": reply.initial_output_tokens}}}]
            for index, block in enumerate(content):
                start = deepcopy(block)
                if block["type"] == "tool_use":
                    start["input"] = {}
                    deltas = [{"type": "input_json_delta", "partial_json": json.dumps(block["input"])}]
                elif block["type"] == "thinking":
                    start.update(thinking="", signature="")
                    deltas = [{"type": "thinking_delta", "thinking": block["thinking"]},
                              {"type": "signature_delta", "signature": block["signature"]}]
                elif block["type"] == "text":
                    start["text"] = ""
                    deltas = [{"type": "text_delta", "text": block["text"]}]
                else:
                    deltas = []
                events.append({"type": "content_block_start", "index": index, "content_block": start})
                events.extend({"type": "content_block_delta", "index": index, "delta": delta} for delta in deltas)
                events.append({"type": "content_block_stop", "index": index})
            events.extend([{"type": "message_delta", "delta": {"stop_reason": response["stop_reason"],
                "stop_sequence": None}, "usage": {"output_tokens": reply.output_tokens}}, {"type": "message_stop"}])
            clock = self.clock
            class EventStream(httpx2.SyncByteStream):
                def __iter__(self):
                    for index, event in enumerate(events):
                        if index == 1:
                            if reply.stream_truncated:
                                return
                            clock.advance(reply.stream_elapsed)
                            if reply.stream_error:
                                raise httpx2.ReadError("scripted stream disconnect")
                        yield ("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode()
            return httpx2.Response(200, stream=EventStream(), headers={"content-type": "text/event-stream"})
        return httpx2.Response(200, json=response, headers={"request-id": f"req-{len(self.requests)}"})
