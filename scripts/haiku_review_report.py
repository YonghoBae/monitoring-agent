"""Compare independent Haiku field/evidence decisions to archived Codex review."""
import argparse
import collections
import json
from pathlib import Path
from haiku_rejudge import read, lines, save, cost_state


def build(out):
    manifest = read(out / 'manifest.json')
    archive = Path(manifest['archive'])
    mapping = read(out / 'mapping.json')
    old, completions = {}, {}
    for group in ['test', 'development-enhanced', 'development-baseline']:
        for r in read(archive / group / 'content-scores.json')['rows']:
            old[(r['id'], r['arm'], r['rep'])] = r
        for r in read(archive / group / 'reviewed-summary.json')['rows']:
            completions[(r['id'], r['arm'], r['rep'])] = r['completion']
    results = lines(out / 'main-results.jsonl')
    groups = collections.defaultdict(list)
    task_groups = collections.defaultdict(list)
    differences, records = [], []
    total_fields = agreement = 0
    for r in results:
        m = mapping[r['id']]
        identity = (m['id'], m['arm'], m['rep'])
        before = old[identity]
        previous = {c['key']: c for c in before['checks']}
        new = r['result']
        for f in new['fields']:
            total_fields += 1
            same = f['grounded_field'] == previous[f['key']]['grounded_field']
            agreement += same
            if not same:
                differences.append(m | {'request_id': r['id'], 'field': f['key'],
                    'old_grounded': previous[f['key']]['grounded_field'], 'haiku_grounded': f['grounded_field'],
                    'haiku_extracted_value': f['value'], 'haiku_answer_quote': f['quote'],
                    'haiku_reason': f['reason'], 'haiku_evidence': f['evidence']})
        record = m | {'request_id': r['id'], 'old_score': before['score'], 'haiku_score': new['score'],
            'old_flagged': bool(before['unsupported_claims']), 'haiku_flagged': bool(new['unsupported_claims']),
            'completion': completions[identity], 'gold_issue': new['gold_issue']}
        records.append(record)
        groups[(m['split'], m['arm'])].append(record)
        task_groups[(m['split'], m['task_mode'], m['arm'])].append(record)

    def stats(rs):
        n = len(rs)
        return {'n': n, 'old_score': sum(r['old_score'] for r in rs) / n,
            'haiku_score': sum(r['haiku_score'] for r in rs) / n,
            'haiku_score_nonreturned_zero': sum(r['haiku_score'] if r['completion'] == 'returned_answer' else 0 for r in rs) / n,
            'old_flagged_answers': sum(r['old_flagged'] for r in rs),
            'haiku_flagged_answers': sum(r['haiku_flagged'] for r in rs),
            'all_grounded_no_flag_normal_return': sum(r['haiku_score'] == 100 and not r['haiku_flagged'] and r['completion'] == 'returned_answer' for r in rs)}
    summary, by_task = {}, {}
    for (split, arm), rs in groups.items():
        summary.setdefault(split, {})[arm] = stats(rs)
    for (split, task, arm), rs in task_groups.items():
        by_task.setdefault(split, {}).setdefault(task, {})[arm] = stats(rs)
    report = {'complete': len(results) == len(mapping), 'reviewed_answers': len(results),
        'expected_answers': len(mapping), 'model': manifest['model'], 'summary': summary, 'by_task': by_task,
        'field_agreement': {'agreements': agreement, 'fields': total_fields,
                            'percent': 100 * agreement / total_fields if total_fields else None},
        'claim_flag_agreement_count': sum(r['old_flagged'] == r['haiku_flagged'] for r in records),
        'cost': cost_state(out), 'rows': records,
        'limitations': ['Agreement with Codex is not accuracy against independent human labels.',
                       'Calibration controls are authored by Codex, not an external human benchmark.',
                       'Same frozen scenarios; this review does not establish real-incident representativeness.',
                       'A single Haiku judgment per answer is not a repeatability study.']}
    save(out / 'comparison.json', report)
    save(out / 'disagreements.json', differences)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    result = build(args.out)
    print(json.dumps({k: v for k, v in result.items() if k not in ['rows', 'limitations']}, ensure_ascii=False, indent=2))
