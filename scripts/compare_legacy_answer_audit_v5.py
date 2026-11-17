"""Compare prospective independent70-answer audit with reported endpoints, without replacing scores."""
import json
from pathlib import Path

import haiku_rejudge as api
from score_legacy_eval_v55 import _verified_mapping, grade_components

ROOT = Path(__file__).resolve().parents[1]


def compose_review(review, payload, runner_error):
    keys = {f['key'] for f in payload['reference']['required_findings']}
    if set(review['findings']) != keys or any(type(v) is not bool for v in review['findings'].values()):
        raise ValueError('Independent findings must be exhaustive booleans')
    if any(type(review[k]) is not bool for k in ('unsupported_claims', 'pass', 'ambiguous')):
        raise ValueError('Independent verdict labels must be booleans')
    if review['pass'] != (all(review['findings'].values()) and not review['unsupported_claims']):
        raise ValueError('Independent semantic pass contradicts atomic judgments')
    ids = {o['id'] for o in payload['observations']}
    if not isinstance(review['notes'], list):
        raise ValueError('Independent notes must be an array')
    for note in review['notes']:
        if not isinstance(note, dict):
            raise ValueError('Independent note must be an object')
        quote = note.get('quote', '')
        if not isinstance(quote, str):
            raise ValueError('Independent quote must be text')
        if quote and quote not in payload['answer']:
            raise ValueError('Independent quote is not an exact answer substring')
        cited = note.get('observation_ids', [])
        if not isinstance(cited, list) or any(not isinstance(value, str) for value in cited):
            raise ValueError('Independent observation IDs must be a string array')
        if len(cited) != len(set(cited)) or any(value not in ids for value in cited):
            raise ValueError('Independent review cites an undelivered observation')
    for key, satisfied in review['findings'].items():
        if satisfied and not any(note.get('key') == key and isinstance(note.get('quote'), str)
                                 and note['quote'].strip() for note in review['notes']):
            raise ValueError('Every independently satisfied finding needs its own exact answer quote')
    # The independent reviewer uses exact substrings, while the frozen atomic
    # validator accepts whole lines/the entire answer. Use the whole answer only
    # as a native-schema carrier for already validated manual labels. Original
    # manual notes remain untouched in the result; no automated verdict is adapted.
    semantic = {'unsupported_claims': review['unsupported_claims'],
        'answer_status': 'answered' if payload['answer'].strip() else 'unanswered',
        'reason': 'Independent manual labels; exact source notes retained separately.',
        'findings': [{'key': key, 'satisfied': satisfied,
            'answer_quote': payload['answer'] if satisfied else '',
            'observation_ids': sorted({ident for note in review['notes'] if note.get('key') == key
                                       for ident in note.get('observation_ids', [])}),
            'reason': 'Independent manual label; whole-answer quote is a schema carrier.'}
            for key, satisfied in review['findings'].items()]}
    result = grade_components(payload, semantic, runner_error)
    return result['combined_fields'], result['structured_pass']


def main():
    out = ROOT/'eval/v5/legacy-answer-audit'
    scoring = ROOT/'eval/v5/legacy-scoring-v55'
    manifest = api.read(out/'manifest.json')
    if manifest['source_mapping_sha256'] != api.sha((scoring/'mapping.json').read_bytes()):
        raise ValueError('Audit source mapping changed')
    verified = {row['id']: row for row in _verified_mapping(scoring)}
    summary = api.read(scoring/'summary.json')
    if summary['judgments'] != 420 or len(summary['answers']) != 210:
        raise ValueError('Complete automatic scoring required')
    automated = {r['id']: r for r in summary['answers']}
    if len(automated) != len(summary['answers']) or set(automated) != set(verified):
        raise ValueError('Automatic summary differs from verified source identities')
    for ident, row in automated.items():
        if any(row[key] != verified[ident][key] for key in ('case', 'arm', 'rep', 'payload_sha256')):
            raise ValueError('Automatic summary differs from verified source mapping')
    rows = []; seen = set()
    for batch in (1, 2):
        packet_path = out/f'batch-{batch}.json'; packet_sha = api.sha(packet_path.read_bytes())
        if manifest['packet_sha256'][packet_path.name] != packet_sha:
            raise ValueError('Blind packet changed')
        packet_rows = api.read(packet_path)
        mapping_rows = api.read(out/f'batch-{batch}-mapping-private.json')
        packet = {r['id']: r for r in packet_rows}
        mapping = {r['id']: r for r in mapping_rows}
        review = api.read(out/f'batch-{batch}-review.json')
        labels = {r['id']: r for r in review['rows']}
        if (review['source_batch_sha256'] != packet_sha or len(labels) != len(review['rows'])
                or len(packet) != len(packet_rows) or len(mapping) != len(mapping_rows)
                or len(labels) != 35 or set(labels) != set(packet) or set(mapping) != set(packet)):
            raise ValueError('Complete independent review of the exact35-answer packet required')
        for ident, label in labels.items():
            m = mapping[ident]; auto = automated[m['scorer_id']]
            if m['scorer_id'] in seen or m['rep'] != 0:
                raise ValueError('Duplicate or incorrectly selected audit answer')
            seen.add(m['scorer_id'])
            if any(m[k] != auto[k] for k in ('case', 'arm', 'rep')):
                raise ValueError('Private audit mapping differs from scored source')
            payload = api.read(scoring/'payloads'/f"{m['scorer_id']}.json")
            if api.sha(api.encode(payload)) != auto['payload_sha256']:
                raise ValueError('Prepared source payload changed')
            for key in ('question', 'requested_answer_fields', 'answer', 'reference', 'observations', 'requested_schema_policy'):
                if packet[ident]['payload'][key] != payload[key]:
                    raise ValueError('Private mapping does not identify the reviewed source content')
            fields, strict = compose_review(label, payload, auto['runner_error'])
            comparisons = {}
            for rep, component in auto['judge_components'].items():
                differences = ['finding:'+key for key, value in fields.items() if component['combined_fields'][key] != value]
                if strict != component['structured_pass']:
                    differences.append('structured_pass')
                comparisons[rep] = differences
            rows.append({'id': ident, 'scorer_id': m['scorer_id'], 'case': m['case'], 'arm': m['arm'], 'rep': 0,
                'ambiguous': label['ambiguous'], 'independent_combined_fields': fields,
                'independent_structured_pass': strict, 'automated_stable_fields': auto['stable_fields'],
                'automated_stable_structured_pass': auto['stable_structured_pass'],
                'automated_scored_agreement': auto['scored_agreement'],
                'per_judge_disagreements': comparisons,
                'both_judges_match_independent_endpoints': set(comparisons) == {'0', '1'} and all(not v for v in comparisons.values()),
                'independent_notes': label['notes']})
    expected = {r['id'] for r in summary['answers'] if r['rep'] == 0}
    if seen != expected or len(rows) != 70:
        raise ValueError('All70 prospectively selected answers must remain in the audit')
    clear = [r for r in rows if not r['ambiguous']]
    result = {'answers': 70, 'ambiguous': sum(r['ambiguous'] for r in rows),
        'nonambiguous': len(clear),
        'nonambiguous_both_judges_match': sum(r['both_judges_match_independent_endpoints'] for r in clear),
        'all_both_judges_match': sum(r['both_judges_match_independent_endpoints'] for r in rows),
        'automated_unresolved_in_sample': sum(not r['automated_scored_agreement'] for r in rows),
        'rows': rows,
        'scope': 'One independent AI semantic reviewer per sampled answer; same fixed deterministic numeric/schema composition applied. Not human ground truth or an inter-rater estimate. Official scores remain unchanged.'}
    api.save(out/'agreement-summary.json', result)
    print(api.encode({k: v for k, v in result.items() if k != 'rows'}))


if __name__ == '__main__':
    main()
