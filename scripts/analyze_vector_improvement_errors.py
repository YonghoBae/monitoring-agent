"""Describe retrieval/reranking bottlenecks using frozen IDs and community labels.

No model calls, raw question text, or post-test parameter selection.
"""
import gzip
import json
from pathlib import Path
from audit_vector_duplicate_links import components, same_component

BASE = Path(__file__).resolve().parents[1] / 'eval/vector-v3-improvement'


def read(path):
    return json.loads(path.read_text())


def diagnose(query, rankings, lock):
    gold = set(query['gold'])
    original = rankings['selected_encoder'][query['id']]
    if lock['reranker']:
        depth = lock['candidate_depth']
        if lock['candidate_mode'] == 'union':
            candidates = list(dict.fromkeys(original[:depth // 2] + rankings['bm25'][query['id']][:depth // 2]))
        else:
            candidates = original[:depth]
    else:
        candidates = original
    final = rankings['selected_pipeline'][query['id']]
    baseline = rankings['baseline'][query['id']]
    candidate_hit = bool(gold.intersection(candidates))
    return {
        'query_id': query['id'], 'group': query['group'], 'source_id': query['source_id'],
        'gold_count': len(gold), 'candidate_count': len(candidates),
        'candidate_gold_count': len(gold.intersection(candidates)),
        'candidate_hit': candidate_hit,
        'baseline_hit1': baseline[0] in gold,
        'baseline_hit100': bool(gold.intersection(baseline)),
        'encoder_hit100': bool(gold.intersection(original)),
        'pipeline_hit1': final[0] in gold,
        'pipeline_hit5': bool(gold.intersection(final[:5])),
        'bottleneck_for_hit1': 'correct_first' if final[0] in gold else ('ranking_miss' if candidate_hit else 'candidate_miss'),
        'first_known_relevant_rank': next((i + 1 for i, d in enumerate(final) if d in gold), None),
    }


def main():
    lock = read(BASE / 'final-selection-lock.json')
    dataset = read(BASE / 'final/numeric-dataset.json')
    rankings = {}
    for method in ['baseline', 'bm25', 'selected_encoder', 'selected_pipeline']:
        with gzip.open(BASE / 'final' / (method + '-rankings.jsonl.gz'), 'rt') as f:
            rankings[method] = {r['query_id']: r['document_ids'] for r in map(json.loads, f)}
    queries = [q for q in dataset['queries'] if q['group'] not in ['recent_en', 'historical_en', 'historical_ko']]
    rows = [diagnose(q, rankings, lock) for q in queries]
    graph = components(read(BASE / 'known-duplicate-links.json')['edges'])
    by_id = {q['id']: q for q in queries}
    for row in rows:
        q = by_id[row['query_id']]
        for method in ['baseline', 'selected_encoder', 'selected_pipeline']:
            first = rankings[method][q['id']][0]
            row[method + '_unjudged_same_duplicate_component_hit1'] = first not in q['gold'] and same_component(q['source_id'], first, graph)
    groups = []
    for group in sorted({q['group'] for q in queries}) + ['holdout_en', 'holdout_ko']:
        part = [r for r in rows if (r['group'].endswith('_en' if group == 'holdout_en' else '_ko') if group.startswith('holdout_') else r['group'] == group)]
        groups.append({'group': group, 'queries': len(part),
                       **{key: sum(r[key] for r in part) for key in ['candidate_hit', 'baseline_hit1', 'baseline_hit100', 'encoder_hit100', 'pipeline_hit1', 'pipeline_hit5']},
                       **{method + '_unjudged_same_duplicate_component_hit1': sum(r[method + '_unjudged_same_duplicate_component_hit1'] for r in part) for method in ['baseline', 'selected_encoder', 'selected_pipeline']},
                       **{kind: sum(r['bottleneck_for_hit1'] == kind for r in part) for kind in ['correct_first', 'ranking_miss', 'candidate_miss']}})
    result = {'scope': 'Post-test diagnostic only; known community duplicate labels may omit other valid results. Does not diagnose generated answers or root-cause accuracy.',
              'label_gap_audit': 'Unjudged first results in the same known duplicate-link component are flagged as possible label gaps, not relabeled or counted as correct. A transitive path is not a full relevance adjudication.',
              'candidate_definition': 'Actual locked reranker input; top100 encoder ranking when reranking is absent.',
              'groups': groups, 'queries': rows}
    (BASE / 'final/error-analysis.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'groups': groups}, indent=2))


if __name__ == '__main__':
    main()
