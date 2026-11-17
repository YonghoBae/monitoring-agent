"""Paired uncertainty grouped by shared source questions or known relevant records."""
import numpy as np


def relevance_clusters(queries):
    parent = {q['id']: q['id'] for q in queries}
    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    owners = {}
    for q in queries:
        for key in ['question:' + q['source_id'], *['document:' + d for d in q['gold']]]:
            if key in owners:
                a, b = root(q['id']), root(owners[key])
                parent[max(a, b)] = min(a, b)
            else:
                owners[key] = q['id']
    return {q['id']: root(q['id']) for q in queries}


def paired_cluster_interval(deltas, clusters, seed=20261118, resamples=2000):
    grouped = {}
    for q, delta in deltas.items():
        grouped.setdefault(clusters[q], []).append(delta)
    values = [grouped[k] for k in sorted(grouped)]
    sums = np.array([sum(v) for v in values], dtype=np.float64)
    sizes = np.array([len(v) for v in values], dtype=np.float64)
    rng = np.random.default_rng(seed)
    selected = rng.integers(0, len(values), (resamples, len(values)))
    boot = sums[selected].sum(axis=1) / sizes[selected].sum(axis=1)
    return {'mean': float(sums.sum() / sizes.sum()), 'ci95': np.quantile(boot, [.025, .975]).tolist(),
            'clusters': len(values), 'queries': len(deltas), 'resamples': resamples, 'seed': seed,
            'small_cluster_count': len(values) < 20}
