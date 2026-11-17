"""Freeze development material and collect an unscored, server-focused holdout."""
import datetime as dt
import hashlib
from html import unescape
import json
from pathlib import Path
import sys

import eval_real_vector_retrieval as old
from eval_recent_vector_control import body_text
import prepare_recent_vector_control as fetcher

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'eval/vector-v3-improvement'


def development():
    assert not (BASE / 'development-manifest.json').exists()
    docs, original_queries, gold, ko = old.load_data()
    full = {d['_id']: d for d in docs}
    recent = old.BASE / 'recent-control'
    targets = json.loads((recent / 'cache/target-questions.json').read_text())
    full.update({i: {'_id': i, 'title': unescape(q['title']), 'text': body_text(q['body'])} for i, q in targets.items()})
    source_queries = json.loads((recent / 'cache/selected-questions.json').read_text())
    manifest = json.loads((recent / 'dataset-manifest.json').read_text())
    current_gold = {q['query_id']: q['target_ids'] for q in manifest['queries']}
    queries = [{'id': 'recent:' + str(q['question_id']), 'source_id': str(q['question_id']), 'group': 'recent_en', 'text': unescape(q['title']), 'gold': current_gold[str(q['question_id'])]} for q in source_queries]
    by_id = {q['_id']: q for q in original_queries}
    for q in ko:
        queries.append({'id': 'hist-en:' + q['_id'], 'source_id': q['_id'], 'group': 'historical_en', 'text': by_id[q['_id']]['text'], 'gold': sorted(gold[q['_id']])})
        queries.append({'id': 'hist-ko:' + q['_id'], 'source_id': q['_id'], 'group': 'historical_ko', 'text': q['text'], 'gold': sorted(gold[q['_id']])})
    queries.sort(key=lambda q: q['id'])
    required = {d for q in queries for d in q['gold']}
    assert required <= full.keys()
    others = sorted(full.keys() - required, key=lambda i: hashlib.sha256(('v3-pool:' + i).encode()).hexdigest())
    pool = sorted(required | set(others[:5000 - len(required)]))
    assert len(pool) == 5000
    cache = BASE / 'cache'
    old.save(cache / 'development-documents.json', [full[i] for i in pool])
    old.save(cache / 'full-documents.json', [full[i] for i in sorted(full)])
    old.save(cache / 'development-queries.json', queries)
    # Existing native all-minilm vectors are reusable: identical source fields and order mapping.
    import numpy as np
    prior = np.load(old.BASE / 'cache/embeddings.npy')
    updates = np.load(recent / 'cache/embeddings.npy')
    updated_ids = sorted(targets)
    original_pos = {d['_id']: i for i, d in enumerate(docs)}
    update_pos = {i: j for j, i in enumerate(updated_ids)}
    document_vectors = np.array([updates[update_pos[i]] if i in update_pos else prior[original_pos[i]] for i in pool])
    old_qpos = {q['_id']: len(docs) + i for i, q in enumerate(original_queries)}
    ko_pos = {q['_id']: len(docs) + len(original_queries) + i for i, q in enumerate(ko)}
    recent_pos = {str(q['question_id']): len(updated_ids) + i for i, q in enumerate(sorted(source_queries, key=lambda q: str(q['question_id'])))}
    qvectors = []
    for q in queries:
        i = q['source_id']
        qvectors.append(updates[recent_pos[i]] if q['group'] == 'recent_en' else prior[ko_pos[i] if q['group'] == 'historical_ko' else old_qpos[i]])
    np.save(cache / 'baseline-documents.npy', document_vectors)
    np.save(cache / 'baseline-queries.npy', np.array(qvectors))
    old.save(BASE / 'development-manifest.json', {'frozen_at': old.now(), 'candidate_count': len(pool), 'full_candidate_count': len(full),
              'groups': {g: sum(q['group'] == g for q in queries) for g in sorted({q['group'] for q in queries})},
              'candidate_ids': pool, 'queries': [{k: v for k, v in q.items() if k != 'text'} for q in queries],
              'file_sha256': {p.name: old.sha(p) for p in sorted(cache.glob('*')) if p.is_file()}})
    print('DEVELOPMENT frozen', len(pool), len(queries), flush=True)


def holdout():
    base = BASE / 'holdout'
    fetcher.BASE = base
    plan_path = base / 'acquisition-plan.json'
    tags = ['linux', 'ubuntu', 'debian', 'centos', 'redhat', 'docker', 'nginx', 'apache-2.4', 'networking', 'dns', 'ssh', 'iptables', 'ssl', 'linux-networking', 'tls', 'systemd', 'backup', 'storage', 'nfs', 'raid', 'proxmox', 'virtualization', 'kvm', 'containers']
    if not plan_path.exists():
        old.save(plan_path, {'frozen_at': old.now(), 'site': 'serverfault', 'fromdate': 1751328000, 'todate': int(dt.datetime.now(dt.timezone.utc).timestamp()),
                           'pages': 5, 'page_size': 100, 'maximum_queries': 80, 'eligible_tags_any': tags,
                           'selection': 'Collect first 500 closed questions created from 2025-07-01, creation descending. Keep duplicate questions with authoritative original targets and eligible tag. Select SHA256(v3-holdout:ID) first 80. Exclude missing targets before any score.',
                           'translation_control': 'First 20 eligible query IDs by SHA256(v3-holdout-ko:ID), translated before final scores without consulting answers.',
                           'final_use': 'Only after locking pipeline on development; no tuning on holdout outcomes.'})
    plan = json.loads(plan_path.read_text())
    assert not (base / 'dataset-manifest.json').exists()
    custom = fetcher.api('filters/create', {'base': 'withbody', 'include': 'question.closed_details;closed_details.original_questions;original_question.question_id'}, 'filter.json')['items'][0]['filter']
    items = {}
    for page in range(1, plan['pages'] + 1):
        data = fetcher.api('search/advanced', {'site': 'serverfault', 'fromdate': plan['fromdate'], 'todate': plan['todate'], 'closed': 'true', 'sort': 'creation', 'order': 'desc', 'pagesize': 100, 'page': page, 'filter': custom}, f'closed-{page}.json')
        items.update({str(q['question_id']): q for q in data['items']})
        print('HOLDOUT page', page, 'items', len(data['items']), flush=True)
        if not data.get('has_more'):
            break
    eligible = [q for q in items.values() if str(q.get('closed_reason', '')).lower() == 'duplicate' and q.get('closed_details', {}).get('original_questions') and set(q.get('tags', [])) & set(tags)]
    selected = sorted(eligible, key=lambda q: hashlib.sha256(('v3-holdout:' + str(q['question_id'])).encode()).hexdigest())[:80]
    targets = sorted({str(t['question_id']) for q in selected for t in q['closed_details']['original_questions']})
    target_items = {}
    for offset in range(0, len(targets), 100):
        data = fetcher.api('questions/' + ';'.join(targets[offset:offset + 100]), {'site': 'serverfault', 'pagesize': 100, 'filter': 'withbody'}, f'targets-{offset}.json')
        target_items.update({str(q['question_id']): q for q in data['items']})
    excluded, queries = [], []
    for q in selected:
        qid = str(q['question_id'])
        gold = sorted({str(t['question_id']) for t in q['closed_details']['original_questions']})
        if not set(gold) <= target_items.keys():
            excluded.append(qid)
            continue
        queries.append({'id': 'sf-en:' + qid, 'source_id': 'sf:' + qid, 'group': 'serverfault_en', 'text': unescape(q['title']),
                        'gold': ['sf:' + i for i in gold], 'creation_date': q['creation_date'], 'tags': q['tags'], 'source_url': 'https://serverfault.com/questions/' + qid})
    assert queries, 'No eligible recent source cases; do not manufacture a holdout'
    full = json.loads((BASE / 'cache/full-documents.json').read_text())
    source = {**items, **target_items}
    full.extend({'_id': 'sf:' + i, 'title': unescape(q['title']), 'text': body_text(q['body'])} for i, q in source.items())
    full.sort(key=lambda d: d['_id'])
    queries.sort(key=lambda q: q['id'])
    ko_ids = [q['id'] for q in sorted(queries, key=lambda q: hashlib.sha256(('v3-holdout-ko:' + q['id']).encode()).hexdigest())[:20]]
    old.save(base / 'cache/documents.json', full)
    old.save(base / 'cache/queries.json', queries)
    old.save(base / 'dataset-manifest.json', {'frozen_at': old.now(), 'plan_sha256': old.sha(plan_path), 'questions_collected': len(items),
                  'eligible_duplicate_questions': len(eligible), 'selected_queries': len(queries), 'excluded_missing_targets': excluded,
                  'candidate_count': len(full), 'gold_pairs': sum(len(q['gold']) for q in queries), 'korean_control_source_ids': ko_ids,
                  'queries': [{k: v for k, v in q.items() if k != 'text'} for q in queries],
                  'file_sha256': {p.name: old.sha(p) for p in sorted((base / 'cache').glob('*.json'))},
                  'limitations': 'Real community duplicate labels; later creation dates reduce specific older-source overlap but do not prove all-model training independence.'})
    print('HOLDOUT frozen', len(queries), 'queries;', len(full), 'documents', flush=True)
    print('TRANSLATION SOURCE TITLES (no answers):', flush=True)
    by = {q['id']: q for q in queries}
    for qid in ko_ids:
        print(qid, by[qid]['text'], flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'development':
        development()
    else:
        holdout()
