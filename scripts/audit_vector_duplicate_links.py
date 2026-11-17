"""Freeze known community duplicate links for a supplementary label-gap audit.

Never changes the locked qrels. A graph connection is not proof that every
linked question is interchangeable: multi-target closures can join broad topics.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / 'eval/vector-v3-improvement'


def components(edges):
    parent = {node: node for edge in edges for node in edge}
    def root(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node
    for a, b in edges:
        a, b = root(a), root(b)
        parent[max(a, b)] = min(a, b)
    return {node: root(node) for node in sorted(parent)}


def same_component(a, b, mapping):
    return a in mapping and b in mapping and mapping[a] == mapping[b]


def main():
    assert not (BASE / 'final/summary.json').exists(), 'Freeze this diagnostic before final scores'
    destination = BASE / 'known-duplicate-links.json'
    assert not destination.exists(), 'Preserve the first graph'
    edges, sources = set(), {}
    for prefix, directory in [('sf', 'holdout/cache'), ('au', 'holdout-extension/askubuntu/cache'), ('su', 'holdout-extension/superuser/cache')]:
        for path in sorted((BASE / directory).glob('closed-*.json')):
            sources[str(path.relative_to(BASE))] = hashlib.sha256(path.read_bytes()).hexdigest()
            for row in json.loads(path.read_text())['items']:
                for target in row.get('closed_details', {}).get('original_questions', []):
                    edges.add((prefix + ':' + str(row['question_id']), prefix + ':' + str(target['question_id'])))
    edges = sorted(edges)
    mapping = components(edges)
    queries = json.loads((BASE / 'holdout-extension/dataset-manifest.json').read_text())['queries']
    assert all(same_component(q['source_id'], target, mapping) for q in queries for target in q['gold'])
    result = {'frozen_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'final_scores_seen': False,
              'purpose': 'Supplementary possible-label-gap audit only; locked qrels and primary scores remain unchanged.',
              'caution': 'Transitive duplicate links, especially multi-target closures, are not independent relevance judgments for every pair.',
              'edges': edges, 'nodes': len(mapping), 'components': len(set(mapping.values())), 'source_sha256': sources}
    destination.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ['edges', 'source_sha256']}, indent=2))


if __name__ == '__main__':
    main()
