"""Broaden the small ServerFault holdout before any new-model accuracy scores."""
import datetime as dt
import hashlib
from html import unescape
import json

import eval_real_vector_retrieval as ev
from eval_recent_vector_control import body_text
import prepare_recent_vector_control as fetcher
from vector_model_candidates import BASE


def main():
    root = BASE / 'holdout-extension'
    plan_path = root / 'acquisition-plan.json'
    tags = ['server', 'linux', 'ubuntu', 'networking', 'permissions', 'apt', 'boot', 'ssh', 'nginx', 'docker', 'systemd', 'hard-drive', 'partitioning', 'mount', 'raid', 'lvm', 'backup', 'cron', 'iptables', 'ufw', 'dns', 'package-management', 'network-manager', 'filesystems', 'disk-space', 'rsync', 'ssl', 'tls', 'router', 'nas']
    if not plan_path.exists():
        assert not (BASE / 'runs').exists(), 'Freeze source extension before new candidate accuracy runs'
        ev.save(plan_path, {'frozen_at': ev.now(), 'reason': 'ServerFault source returned only 9 eligible cases; expand source coverage before new-model scoring',
                            'sites': ['askubuntu', 'superuser'], 'fromdate': 1751328000, 'todate': int(dt.datetime.now(dt.timezone.utc).timestamp()),
                            'pages_per_site': 3, 'page_size': 100, 'max_queries_per_site': 60, 'eligible_tags_any': tags,
                            'selection': 'Authoritative duplicate targets; hash v3-extra:<site>:<ID>; all missing-target exclusions recorded',
                            'limits': 'Source expansion is a recorded acquisition amendment, not response to retrieval results. Tags approximate home-server relevance; not incident-only data.'})
    plan = json.loads(plan_path.read_text())
    full = json.loads((BASE / 'holdout/cache/documents.json').read_text())
    queries = json.loads((BASE / 'holdout/cache/queries.json').read_text())
    source_manifests = []
    for site, prefix in [('askubuntu', 'au:'), ('superuser', 'su:')]:
        fetcher.BASE = root / site
        custom = fetcher.api('filters/create', {'base': 'withbody', 'include': 'question.closed_details;closed_details.original_questions;original_question.question_id'}, 'filter.json')['items'][0]['filter']
        items = {}
        for page in range(1, plan['pages_per_site'] + 1):
            data = fetcher.api('search/advanced', {'site': site, 'fromdate': plan['fromdate'], 'todate': plan['todate'], 'closed': 'true', 'sort': 'creation', 'order': 'desc', 'pagesize': 100, 'page': page, 'filter': custom}, f'closed-{page}.json')
            items.update({str(q['question_id']): q for q in data['items']})
            if not data.get('has_more'):
                break
        eligible = [q for q in items.values() if str(q.get('closed_reason', '')).lower() == 'duplicate' and q.get('closed_details', {}).get('original_questions') and set(q['tags']) & set(tags)]
        selected = sorted(eligible, key=lambda q: hashlib.sha256(('v3-extra:' + site + ':' + str(q['question_id'])).encode()).hexdigest())[:60]
        tids = sorted({str(t['question_id']) for q in selected for t in q['closed_details']['original_questions']})
        targets = {}
        for offset in range(0, len(tids), 100):
            data = fetcher.api('questions/' + ';'.join(tids[offset:offset + 100]), {'site': site, 'pagesize': 100, 'filter': 'withbody'}, f'targets-{offset}.json')
            targets.update({str(q['question_id']): q for q in data['items']})
        accepted, excluded = [], []
        for q in selected:
            qid = str(q['question_id'])
            gold = sorted({str(t['question_id']) for t in q['closed_details']['original_questions']})
            if not set(gold) <= targets.keys():
                excluded.append(qid)
                continue
            accepted.append({'id': prefix.replace(':', '-en:') + qid, 'source_id': prefix + qid, 'group': site + '_en', 'text': unescape(q['title']),
                             'gold': [prefix + i for i in gold], 'creation_date': q['creation_date'], 'tags': q['tags'],
                             'source_url': 'https://' + site + '.com/questions/' + qid})
        source = {**items, **targets}
        full.extend({'_id': prefix + i, 'title': unescape(q['title']), 'text': body_text(q['body'])} for i, q in source.items())
        queries.extend(accepted)
        source_manifests.append({'site': site, 'collected': len(items), 'eligible': len(eligible), 'accepted': len(accepted), 'excluded_missing_targets': excluded,
                                 'file_sha256': {str(p.relative_to(root)): ev.sha(p) for p in sorted((root / site / 'cache').glob('*.json'))}})
        print(site, 'queries', len(accepted), flush=True)
    full.sort(key=lambda d: d['_id'])
    queries.sort(key=lambda q: q['id'])
    ko_ids = [q['id'] for q in sorted(queries, key=lambda q: hashlib.sha256(('v3-combined-ko:' + q['id']).encode()).hexdigest())[:20]]
    ev.save(root / 'cache/documents.json', full)
    ev.save(root / 'cache/queries.json', queries)
    ev.save(root / 'dataset-manifest.json', {'frozen_at': ev.now(), 'plan_sha256': ev.sha(plan_path), 'serverfault_manifest_sha256': ev.sha(BASE / 'holdout/dataset-manifest.json'),
             'candidate_count': len(full), 'query_count': len(queries), 'source_manifests': source_manifests, 'korean_control_source_ids': ko_ids,
             'queries': [{k: v for k, v in q.items() if k != 'text'} for q in queries], 'file_sha256': {p.name: ev.sha(p) for p in sorted((root / 'cache').glob('*.json'))}})
    print('COMBINED', len(queries), len(full), flush=True)
    by = {q['id']: q for q in queries}
    for i in ko_ids:
        print(i, by[i]['text'], flush=True)


if __name__ == '__main__':
    main()
