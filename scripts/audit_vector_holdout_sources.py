"""Audit source labels and answer metadata without consulting model scores."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import argparse
import time
import urllib.parse
import urllib.request

from retrieval_uncertainty import relevance_clusters

BASE = Path(__file__).resolve().parents[1] / 'eval/vector-v3-improvement'


def read(path):
    return json.loads(path.read_text())


def normalize(text):
    return re.sub(r'\W+', ' ', unicodedata.normalize('NFKC', text).casefold()).strip()


def main(fetch_attribution=False):
    queries = read(BASE / 'holdout-extension/cache/queries.json')
    docs = {d['_id']: d for d in read(BASE / 'holdout-extension/cache/documents.json')}
    gold = {d for q in queries for d in q['gold']}
    targets = {}
    sources = {}
    paths = {'sf': BASE / 'holdout/cache', 'au': BASE / 'holdout-extension/askubuntu/cache', 'su': BASE / 'holdout-extension/superuser/cache'}
    if fetch_attribution:
        for prefix, site in [('sf', 'serverfault'), ('au', 'askubuntu'), ('su', 'superuser')]:
            destination = paths[prefix] / 'attribution.json'
            if destination.exists():
                continue
            ids = sorted({q['source_id'].split(':', 1)[1] for q in queries if q['source_id'].startswith(prefix + ':')})
            url = 'https://api.stackexchange.com/2.3/questions/' + ';'.join(ids) + '?' + urllib.parse.urlencode({'site': site, 'filter': 'withbody', 'pagesize': 100})
            with urllib.request.urlopen(url, timeout=60) as response:
                data = json.load(response)
            assert not data.get('error_id') and {str(x['question_id']) for x in data['items']} == set(ids)
            metadata = [{k: row.get(k) for k in ['question_id', 'content_license', 'link']} for row in data['items']]
            destination.write_text(json.dumps({'source_url': url, 'items': metadata}, indent=2) + '\n')
            time.sleep(min(60, data.get('backoff', 0)))
    for prefix, path in paths.items():
        for p in path.glob('closed-*.json'):
            for row in read(p)['items']:
                sources[prefix + ':' + str(row['question_id'])] = row
        for p in path.glob('targets-*.json'):
            for row in read(p)['items']:
                targets[prefix + ':' + str(row['question_id'])] = row
        if (path / 'attribution.json').exists():
            for row in read(path / 'attribution.json')['items']:
                sources[prefix + ':' + str(row['question_id'])]['content_license'] = row['content_license']
    assert gold <= targets.keys()
    clusters = relevance_clusters(queries)
    rows = []
    for q in queries:
        source = sources[q['source_id']]
        rows.append({'query_id': q['id'], 'source_url': q['source_url'], 'group': q['group'],
                     'source_author': source.get('owner', {}).get('display_name'),
                     'source_author_url': source.get('owner', {}).get('link'),
                     'source_content_license': source.get('content_license'),
                     'creation_date_utc': dt.datetime.fromtimestamp(q['creation_date'], dt.timezone.utc).isoformat(),
                     'known_relevant_documents': len(q['gold']),
                     'targets_with_accepted_answer': sum('accepted_answer_id' in targets[d] for d in q['gold']),
                     'normalized_exact_title_match': any(normalize(q['text']) == normalize(docs[d]['title']) for d in q['gold']),
                     'query_title_characters': len(q['text']), 'cluster': clusters[q['id']]})
    result = {'recorded_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'model_scores_used': False,
              'source_queries': len(queries), 'known_relevance_pairs': sum(len(q['gold']) for q in queries),
              'unique_relevant_documents': len(gold), 'targets_with_accepted_answer': sum('accepted_answer_id' in targets[d] for d in gold),
              'targets_with_any_answer': sum(targets[d].get('answer_count', 0) > 0 for d in gold),
              'queries_with_any_accepted_target': sum(r['targets_with_accepted_answer'] > 0 for r in rows),
              'queries_with_normalized_exact_title_target': sum(r['normalized_exact_title_match'] for r in rows),
              'queries_without_api_license_metadata': sum(r['source_content_license'] is None for r in rows),
              'shared_gold_components': len(set(clusters.values())), 'queries': rows,
              'input_sha256': {name: hashlib.sha256((BASE / name).read_bytes()).hexdigest() for name in ['holdout-extension/cache/queries.json', 'holdout-extension/cache/documents.json']},
              'interpretation': 'Duplicate labels establish known similar-question links. An accepted answer is metadata, not independent proof of a verified server recovery. Answer bodies are not retrieval inputs.'}
    (BASE / 'holdout-source-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ['queries', 'input_sha256']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fetch-attribution', action='store_true')
    main(parser.parse_args().fetch_attribution)
