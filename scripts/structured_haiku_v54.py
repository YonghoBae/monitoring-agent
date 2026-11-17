"""Versioned official Messages transport with structured JSON output, no retries.

The frozen base helper provides unchanged utility, pricing, and cost-ledger
functions. This module owns request construction and transport: the reservation
includes the entire dynamic schema, each request ID is single-use, and uncertain
outcomes remain unresolved. Call through budget_registry.paid_call for the global
$2 cap. A local lock also prevents concurrent direct calls on one ledger.

Provider schema is syntax assistance, not a semantic guarantee. Local v54
validation still rejects enum capitalization changes, duplicate/missing findings,
and any observation ID when no observations were delivered. No repair/fallback.
Docs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
"""
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
from haiku_rejudge import (MODEL, MAX_OUTPUT, API, encode, sha, save, read, lines,
                          append, key_from_env, usage_cost, cost_state)
from semantic_judge_v54 import SYSTEM, response_schema


def request_body(payload, system=SYSTEM):
    return {'model': MODEL, 'max_tokens': MAX_OUTPUT, 'system': system,
            'output_config': {'effort': 'medium',
                              'format': {'type': 'json_schema', 'schema': response_schema(payload)}},
            'messages': [{'role': 'user', 'content': encode(payload)}]}


@contextmanager
def _call_lock(out):
    with (Path(out)/'.structured-call.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('A structured call is already using this ledger') from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def call(out, ident, payload, key, phase, system=SYSTEM):
    out = Path(out)
    with _call_lock(out):
        state = cost_state(out)
        if state['unresolved_requests']:
            raise ValueError('Uncertain previous request outcome; refusing duplicate paid call')
        req_id = f'{phase}-{ident}'
        if Path(req_id).name != req_id or req_id in ('.', '..'):
            raise ValueError('Request ID must be a safe filename')
        if any(event.get('request_id') == req_id for event in lines(out/'requests.jsonl')):
            raise ValueError('Request ID already used; no retry or duplicate paid call')
        body = request_body(payload, system)
        raw = encode(body).encode()
        # Same conservative reservation as the original helper, including schema.
        reserved_input = len(raw) + 4096
        if reserved_input > 100000:
            raise ValueError('Payload exceeds conservative short-context ceiling')
        reservation = (reserved_input * .10 + MAX_OUTPUT * .50) / 1e6
        if state['total_campaigns_estimated_usd'] + reservation > 2 or state['attempts'] >= 240:
            raise ValueError('Cost/call cap reached')
        append(out/'requests.jsonl', {'event': 'started', 'request_id': req_id,
               'payload_sha256': sha(raw), 'reserved_usd': reservation,
               'response_schema_sha256': sha(encode(body['output_config']['format']['schema'])),
               'time': time.time()})
        request = urllib.request.Request(API+'messages', data=raw, headers={
            'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = json.load(response)
                server_request_id = response.headers.get('request-id')
        except urllib.error.HTTPError as error:
            append(out/'requests.jsonl', {'event': 'http_error', 'request_id': req_id,
                                        'http_status': error.code})
            raise RuntimeError(f'Anthropic HTTP {error.code}; stopped without automatic retry') from None
        save(out/'raw'/(req_id+'.json'), data)
        cost = usage_cost(data['usage'])
        append(out/'requests.jsonl', {'event': 'completed', 'request_id': req_id,
               'server_request_id': server_request_id, 'model': data.get('model'),
               'usage': data['usage'], 'cost_usd': cost, 'time': time.time()})
        save(out/'cost.json', cost_state(out))
        return data


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate response JSON key')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('Invalid nonfinite JSON response constant: '+value)


def response_json(data):
    if data.get('model') != MODEL or data.get('stop_reason') != 'end_turn':
        raise ValueError('Wrong model or incomplete/refused output')
    blocks = data.get('content', [])
    texts = [block['text'] for block in blocks if block.get('type') == 'text']
    if len(texts) != 1 or not isinstance(texts[0], str):
        raise ValueError('Expected one structured JSON text block')
    # Unlike the older helper, no Markdown fence stripping or normalization.
    return json.loads(texts[0], object_pairs_hook=_pairs, parse_constant=_constant)
