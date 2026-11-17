"""Compare saved independent labels with frozen automatic judgments; never overrides scores."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def main():
    base = ROOT/'eval/v5/canonical-core'
    summary = read(base/'scoring-1/summary.json')
    automated = {(r['case'], r['arm'], r['rep']): r for r in summary['answers']}
    archive = [json.loads(line) for line in (base/'comparison-1/raw-comparison/results.jsonl').read_text().splitlines()]
    archive = {(r['id'], r['arm'], r['rep']): r for r in archive}
    out = base/'independent-review'; rows = []; seen = set()
    for batch in (1, 2):
        packet_path = out/f'batch-{batch}.json'
        packet = {r['id']: r for r in read(packet_path)}
        mapping = {r['id']: r for r in read(out/f'batch-{batch}-mapping-private.json')}
        review = read(out/f'batch-{batch}-review.json')
        cross = read(out/f'batch-{batch}-crossreview.json')
        if review.get('source_batch_sha256') != hashlib.sha256(packet_path.read_bytes()).hexdigest():
            raise ValueError('Independent review is not bound to this exact blind packet')
        labels = {r['id']: r for r in review['rows']}
        cross_labels = {r['id']: r for r in cross['rows']}
        if len(labels) != len(review['rows']) or set(labels) != set(packet) or set(mapping) != set(packet):
            raise ValueError('Complete unique review and mapping required')
        if (cross.get('source_batch_sha256') != review['source_batch_sha256']
                or len(cross_labels) != len(cross['rows']) or set(cross_labels) != set(packet)):
            raise ValueError('Cross-review must independently cover the exact same packet')
        for ident, label in labels.items():
            m = mapping[ident]; key = (m['case'], m['arm'], m['rep'])
            if key in seen:
                raise ValueError('Duplicate reviewed answer')
            seen.add(key)
            raw_hash = hashlib.sha256(json.dumps(archive[key], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if raw_hash != m['source_row_sha256']:
                raise ValueError('Independent packet source differs from sealed model archive')
            auto = automated[key]
            expected_keys = set(auto['stable_findings'])
            if set(label['findings']) != expected_keys or any(type(v) is not bool for v in label['findings'].values()):
                raise ValueError('Independent finding labels must be complete booleans')
            if any(type(label[k]) is not bool for k in ('pass', 'unsupported_claims', 'ambiguous')):
                raise ValueError('Independent verdict labels must be booleans')
            if label['pass'] != (all(label['findings'].values()) and not label['unsupported_claims']):
                raise ValueError('Independent verdict contradicts its own findings')
            second = cross_labels[ident]
            if (set(second['findings']) != expected_keys or any(type(v) is not bool for v in second['findings'].values())
                    or any(type(second[k]) is not bool for k in ('pass', 'unsupported_claims', 'ambiguous'))
                    or second['pass'] != (all(second['findings'].values()) and not second['unsupported_claims'])):
                raise ValueError('Cross-review labels are incomplete or inconsistent')
            reviewers_agree = all(label[key] == second[key] for key in ('findings', 'pass', 'unsupported_claims'))
            comparisons = {}
            for rep, judgment in auto['judge_results'].items():
                differences = ['finding:' + k for k, value in label['findings'].items() if judgment['findings'][k] != value]
                differences += [k for k in ('pass', 'unsupported_claims') if judgment[k] != label[k]]
                comparisons[rep] = differences
            rows.append({'id': ident, 'case': m['case'], 'arm': m['arm'], 'rep': m['rep'],
                'ambiguous': label['ambiguous'], 'independent_pass': label['pass'],
                'cross_ambiguous': second['ambiguous'], 'independent_cross_pass': second['pass'],
                'independent_reviewers_agree': reviewers_agree,
                'independent_findings': label['findings'], 'independent_cross_findings': second['findings'],
                'automated_stable_pass': auto['stable_pass'], 'automated_agreement': auto['agreement'],
                'runner_error': auto['runner_error'], 'per_judge_disagreements': comparisons,
                'full_label_agreement_both_judges': set(comparisons) == {'0', '1'} and all(not v for v in comparisons.values()),
                'independent_notes': label['notes'], 'independent_cross_notes': second['notes']})
    if set(automated) != seen or len(rows) != 48:
        raise ValueError('All48 canonical answers must be independently reviewed')
    clear = [r for r in rows if not r['ambiguous']]
    consensus = [r for r in rows if not r['ambiguous'] and not r['cross_ambiguous'] and r['independent_reviewers_agree']]
    result = {'answers': len(rows), 'ambiguous': sum(r['ambiguous'] for r in rows),
        'nonambiguous_answers': len(clear),
        'nonambiguous_full_label_agreement_both_judges': sum(r['full_label_agreement_both_judges'] for r in clear),
        'independent_reviewers_full_label_agreement': sum(r['independent_reviewers_agree'] for r in rows),
        'independent_finding_labels': sum(len(r['independent_findings']) for r in rows),
        'independent_finding_label_agreement': sum(sum(value == r['independent_cross_findings'][key]
            for key, value in r['independent_findings'].items()) for r in rows),
        'ambiguity_union': sum(r['ambiguous'] or r['cross_ambiguous'] for r in rows),
        'consensus_nonambiguous_answers': len(consensus),
        'consensus_nonambiguous_auto_full_agreement': sum(r['full_label_agreement_both_judges'] for r in consensus),
        'automated_unresolved': sum(not r['automated_agreement'] for r in rows),
        'rows': rows, 'interpretation': 'Independent AI agreement audit, not human ground truth; ambiguous/disputed answers stay in official score denominators. No score replacement.'}
    result['audited_arms'] = {}
    for arm in ('pi_plus', 'compact_plus'):
        selected = [r for r in rows if r['arm'] == arm]
        denominator = sum(len(r['independent_findings']) for r in selected)
        correct = sum(sum(value and r['independent_cross_findings'][key]
            for key, value in r['independent_findings'].items()) for r in selected)
        result['audited_arms'][arm] = {'n': len(selected), 'field_denominator': denominator,
            'both_reviewers_correct_fields': correct, 'field_percent': 100*correct/denominator,
            'strict_pass_lower': sum(r['independent_pass'] and r['independent_cross_pass'] for r in selected),
            'strict_pass_upper': sum(r['independent_pass'] or r['independent_cross_pass'] for r in selected)}
    destination = out/'agreement-summary.json'
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
