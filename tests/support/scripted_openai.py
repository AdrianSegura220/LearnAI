"""Pinned official OpenAI SDK over its verified native httpx2 memory transport."""
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field
import json
from typing import Any

import httpx2
from openai import OpenAI

from tests.support.scripted_client import FakeMonotonic


def usage(input_tokens=100, cached_tokens=20, output_tokens=40, reasoning_tokens=10):
    return {'input_tokens': input_tokens, 'input_tokens_details': {'cached_tokens': cached_tokens},
            'output_tokens': output_tokens, 'output_tokens_details': {'reasoning_tokens': reasoning_tokens},
            'total_tokens': input_tokens + output_tokens}


def mixed_cache_usage():
    return {'input_tokens': 12000, 'input_tokens_details': {'cached_tokens': 4000,
        'cache_write_tokens': 7000, 'cache_write_tokens_details': {
            'ttl_30m_tokens': 3000, 'ttl_12h_tokens': 4000}},
        'output_tokens': 200, 'output_tokens_details': {'reasoning_tokens': 80}, 'total_tokens': 12200}


@dataclass
class ResponseReply:
    output: list[dict[str, Any]] = field(default_factory=list)
    status: str = 'completed'
    usage: dict | None = field(default_factory=usage)
    metadata: dict = field(default_factory=lambda: {'service_tier': 'default'})
    elapsed: float = 0
    http_status: int = 200
    connection_error: bool = False
    events: list[dict] | None = None
    disconnect: bool = False
    stream_elapsed: float = 0


def call(name, arguments=None, *, call_id='call-a', id='fc-a'):
    return {'type': 'function_call', 'id': id, 'call_id': call_id, 'name': name,
            'arguments': json.dumps({} if arguments is None else arguments), 'status': 'completed'}


def message(text):
    return {'type': 'message', 'id': 'msg-a', 'role': 'assistant', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': text, 'annotations': [], 'logprobs': []}]}


def final(text='Compare your two lines.', rung='NUDGE', **kwargs):
    return ResponseReply([message(json.dumps({'message': text, 'rung_used': rung,
        'diagnosis': None, 'proposals': []}))], **kwargs)


class _EventStream(httpx2.SyncByteStream):
    def __init__(self, events, reply, clock):
        self.events, self.reply, self.clock = events, reply, clock
        self.closed = False

    def __iter__(self):
        for event in self.events:
            self.clock.advance(self.reply.stream_elapsed)
            yield ('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n').encode()
        if self.reply.disconnect:
            raise httpx2.ReadError('scripted partial stream disconnect')

    def close(self):
        self.closed = True


class ScriptedOpenAI:
    def __init__(self, replies: Sequence[ResponseReply], *, clock=None):
        self.replies = list(replies)
        self.clock = clock or FakeMonotonic()
        self.requests, self.responses, self.streams, self.timeouts = [], [], [], []
        self.client = OpenAI(api_key='scripted-key', max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self._handle)))
        self._prefixes = {}

    def _validate(self, data):
        assert data['store'] is False
        assert 'previous_response_id' not in data
        assert data['instructions']
        assert data['input'][0]['role'] == 'user'
        key = json.dumps(data['input'][0], sort_keys=True)
        old = self._prefixes.get(key)
        if old is not None:
            assert data['input'][:len(old)] == old, 'lost or reordered continuation'
        pending = []
        for item in data['input']:
            if item.get('type') == 'function_call':
                pending.append(item['call_id'])
            elif item.get('type') == 'function_call_output':
                assert pending and item['call_id'] == pending.pop(0), 'unmatched/reordered call_id'
            elif pending:
                assert item.get('type') in ('reasoning', 'message'), 'unsettled tool calls'
        assert not pending, 'missing tool results'
        self._prefixes[key] = deepcopy(data['input'])

    def _handle(self, request):
        assert request.url.path == '/v1/responses'
        data = json.loads(request.content)
        self._validate(data)
        self.requests.append(deepcopy(data))
        self.timeouts.append(request.extensions.get('timeout'))
        assert self.replies, 'unexpected extra API request'
        reply = self.replies.pop(0)
        self.clock.advance(reply.elapsed)
        if reply.connection_error:
            raise httpx2.ConnectError('scripted pre-response failure')
        headers = {'x-request-id': f'req-{len(self.requests)}'}
        if reply.http_status != 200:
            return httpx2.Response(reply.http_status, headers=headers,
                json={'error': {'message': 'scripted failure', 'type': 'api_error'}})
        raw = {'id': f'resp-{len(self.requests)}', 'object': 'response', 'created_at': 0,
            'model': data['model'], 'status': reply.status, 'error': None,
            'incomplete_details': {'reason': 'max_output_tokens'} if reply.status == 'incomplete' else None,
            'output': deepcopy(reply.output), 'usage': deepcopy(reply.usage), **reply.metadata}
        self.responses.append(deepcopy(raw))
        if data['stream']:
            events = reply.events if reply.events is not None else [
                {'type': 'response.created', 'sequence_number': 0,
                 'response': {**raw, 'status': 'in_progress', 'output': [], 'usage': None}},
                {'type': 'response.completed' if reply.status == 'completed' else 'response.incomplete',
                 'sequence_number': 1, 'response': raw}]
            stream = _EventStream(events, reply, self.clock)
            self.streams.append(stream)
            return httpx2.Response(200, headers={**headers, 'content-type': 'text/event-stream'}, stream=stream)
        return httpx2.Response(200, headers=headers, json=raw)
