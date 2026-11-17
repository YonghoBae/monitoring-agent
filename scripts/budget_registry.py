"""Shared $2 paid-campaign accounting. No model calls occur on import.

Each registered directory contributes its own completed-request costs exactly
once; manifest priors are never summed. A process lock covers both reservation
preflight and the request, so concurrent scoring processes cannot spend against
the same balance. Unknown outcomes in any campaign stop all subsequent calls.
Only paths explicitly listed in eval/paid-campaigns.json are authorized.
"""
from collections import Counter
from contextlib import contextmanager
from decimal import Decimal
import fcntl
import json
from pathlib import Path


def _read(path):
    return json.loads(path.read_text())


def _registered(root):
    root = Path(root).resolve()
    registry = _read(root / 'eval/paid-campaigns.json')
    if registry.get('version') != 1 or Decimal(str(registry.get('budget_usd'))) != Decimal('2'):
        raise ValueError('Invalid global budget registry')
    entries = registry.get('campaigns')
    if not isinstance(entries, list) or not entries:
        raise ValueError('Empty campaign registry')
    paths = []
    for entry in entries:
        if not isinstance(entry, str) or Path(entry).is_absolute():
            raise ValueError('Campaign paths must be relative')
        path = (root / entry).resolve()
        if not path.is_relative_to(root) or path == root or path in paths:
            raise ValueError('Duplicate or escaping campaign path')
        paths.append(path)
    return paths


def _ledger(path):
    ledger = path / 'requests.jsonl'
    events = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()] if ledger.exists() else []
    starts = Counter(e['request_id'] for e in events if e.get('event') == 'started')
    ends = Counter(e['request_id'] for e in events if e.get('event') in ('completed', 'http_error'))
    if any(n != 1 for n in starts.values()) or any(n != 1 for n in ends.values()) or set(ends) - set(starts):
        raise ValueError('Ambiguous or duplicated paid-request ledger: ' + str(path))
    total = Decimal('0')
    for event in events:
        if event.get('event') == 'completed':
            cost = Decimal(str(event['cost_usd']))
            if not cost.is_finite() or cost < 0:
                raise ValueError('Invalid completed-request cost')
            total += cost
    return total, sorted(set(starts) - set(ends))


def state(root, current):
    root, current = Path(root).resolve(), Path(current).resolve()
    campaigns = _registered(root)
    if current not in campaigns:
        raise ValueError('Unregistered paid campaign; arbitrary output paths are not authorized')
    amounts = {}
    for path in campaigns:
        amount, unresolved = _ledger(path)
        if unresolved:
            raise ValueError('Uncertain prior request outcome in ' + str(path.relative_to(root)))
        amounts[path] = amount
    total = sum(amounts.values(), Decimal('0'))
    if total > Decimal('2'):
        raise ValueError('Global paid budget already exceeded')
    return {
        'budget_usd': 2,
        'estimated_usd': float(amounts[current]),
        'prior_campaign_cost_usd': float(total - amounts[current]),
        'total_campaigns_estimated_usd': float(total),
        'campaign_costs_usd': {str(p.relative_to(root)): float(v) for p, v in amounts.items()},
        'unresolved_requests': 0,
    }


@contextmanager
def _lock(root):
    with (Path(root) / 'eval/.paid-campaigns.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def preflight(root, current):
    with _lock(root):
        return state(root, current)


def paid_call(api, root, out, ident, payload, key, phase, system):
    """Use the existing token-reserving API client with an atomic global prior."""
    with _lock(root):
        budget = state(root, out)
        manifest_path = Path(out) / 'manifest.json'
        manifest = _read(manifest_path)
        manifest['prior_campaign_cost_usd'] = budget['prior_campaign_cost_usd']
        manifest['budget_registry'] = 'eval/paid-campaigns.json'
        manifest['budget_usd_including_prior'] = 2
        api.save(manifest_path, manifest)
        # api.call reserves a conservative request maximum before transmitting.
        # It records started before HTTP and refuses uncertain previous outcomes.
        return api.call(out, ident, payload, key, phase, system=system)
