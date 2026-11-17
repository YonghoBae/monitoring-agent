"""Supplemental paired review of the same70 answers; never replaces official scores.

CLI: python3 scripts/compare_legacy_cross_review_v5.py
Requires completed automatic scoring and both review locks. Regenerates the
primary derived agreement-summary through its existing comparator, then writes
only cross-agreement-summary.json. Raw reviews, scoring and plans are read-only.
"""
import contextlib
import io
import json
from pathlib import Path
import statistics

import haiku_rejudge as api
import compare_legacy_answer_audit_v5 as primary
from analyze_legacy_eval_v5 import ARMS, family_scores
from score_legacy_eval_v55 import _verified_mapping

ROOT = Path(__file__).resolve().parents[1]


def index_rows(rows, label, count=None):
    if not isinstance(rows, list) or (count is not None and len(rows) != count):
        raise ValueError(label + ': wrong row count')
    if any(not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] for row in rows):
        raise ValueError(label + ': nonempty string IDs required')
    result = {row['id']: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(label + ': duplicate IDs')
    return result


def boolean_fields(fields, keys, label):
    if not isinstance(fields, dict) or set(fields) != keys or any(type(v) is not bool for v in fields.values()):
        raise ValueError(label + ': exhaustive Boolean fields required')


def automatic_state(auto, keys):
    """A missing/invalid judge is never counted as endpoint agreement."""
    components = auto['judge_components']
    if not isinstance(components, dict) or not set(components) <= {'0', '1'}:
        raise ValueError('Unexpected automatic judge repetition')
    if type(auto['complete']) is not bool or type(auto['scored_agreement']) is not bool:
        raise ValueError('Automatic completeness/agreement must be Boolean')
    errors = auto['integrity_errors']
    if not isinstance(errors, list) or any(not isinstance(error, str) for error in errors):
        raise ValueError('Automatic integrity errors must be a string array')
    for component in components.values():
        boolean_fields(component['combined_fields'], keys, 'Automatic component')
        if type(component['structured_pass']) is not bool:
            raise ValueError('Automatic strict pass must be Boolean')
    complete = set(components) == {'0', '1'} and not errors
    if auto['complete'] != complete:
        raise ValueError('Automatic completeness contradicts components/errors')
    agreement = bool(complete and components['0']['combined_fields'] == components['1']['combined_fields']
                     and components['0']['structured_pass'] == components['1']['structured_pass'])
    expected_fields = {key: bool(complete and all(c['combined_fields'][key] for c in components.values())) for key in keys}
    expected_pass = bool(agreement and all(c['structured_pass'] for c in components.values()))
    boolean_fields(auto['stable_fields'], keys, 'Automatic stable score')
    if (auto['scored_agreement'] != agreement or auto['stable_fields'] != expected_fields
            or type(auto['stable_structured_pass']) is not bool or auto['stable_structured_pass'] != expected_pass):
        raise ValueError('Automatic stable endpoints contradict judge components')
    return complete


def endpoint_differences(fields, strict, component):
    differences = ['finding:' + key for key, value in fields.items() if component['combined_fields'][key] != value]
    if component['structured_pass'] != strict:
        differences.append('structured_pass')
    return differences


def comparison_counts(rows):
    statuses = [row['automatic_vs_common_endpoints'] for row in rows]
    return {'answers': len(rows), 'field_denominator': sum(len(row['primary_combined_fields']) for row in rows),
            'common_endpoint_answers': sum(row['reviewers_share_endpoints'] for row in rows),
            'common_endpoint_field_denominator': sum(len(row['primary_combined_fields']) for row in rows if row['reviewers_share_endpoints']),
            'reviewers_disagree': statuses.count('reviewers_disagree'),
            'matches_common_endpoints': statuses.count('match'),
            'differs_from_common_endpoints': statuses.count('mismatch'),
            'invalid_for_common_endpoints': statuses.count('invalid'),
            'all_invalid_automatic': sum(not row['automatic_valid'] for row in rows)}


def summarize(rows):
    field_n = sum(len(row['primary_combined_fields']) for row in rows)
    if len(rows) != 70 or field_n != 162:
        raise ValueError('Supplemental comparison must retain70 answers and162 fields')
    clear = [row for row in rows if not row['any_reviewer_ambiguous']]
    ambiguous = [row for row in rows if row['any_reviewer_ambiguous']]
    result = {'answers': 70, 'field_denominator': field_n, 'any_reviewer_ambiguous': len(ambiguous),
        'reviewer_agreement': {
            'raw_semantic_fields': {'agreement': field_n - sum(len(r['differences']['raw_semantic_fields']) for r in rows), 'denominator': field_n},
            'combined_fields': {'agreement': field_n - sum(len(r['differences']['combined_fields']) for r in rows), 'denominator': field_n},
            'strict_pass': {'agreement': sum(not r['differences']['strict_pass'] for r in rows), 'denominator': len(rows)},
            'raw_semantic_pass': {'agreement': sum(not r['differences']['raw_semantic_pass'] for r in rows), 'denominator': len(rows)},
            'unsupported_claims_auxiliary': {'agreement': sum(not r['differences']['unsupported_claims'] for r in rows), 'denominator': len(rows)}},
        'automatic_comparison': {'all_answers': comparison_counts(rows),
                                 'nonambiguous_answers': comparison_counts(clear),
                                 'ambiguous_answers': comparison_counts(ambiguous)},
        'arms': {}, 'rows': rows}
    variants = ('primary', 'cross', 'both_reviewers_true', 'either_reviewer_true', 'automatic_rep0')
    all_families = {}
    for variant in variants:
        by_family = family_scores([{'case': r['case'], 'family': r['family'], 'arm': r['arm'], 'rep': 0,
                                     'stable_fields': r['metrics'][variant]['fields']} for r in rows])
        all_families[variant] = by_family
    if any(len(value) != 28 for value in all_families.values()):
        raise ValueError('Expected28 equally weighted families')
    for arm in ARMS:
        selected = [row for row in rows if row['arm'] == arm]
        denominator = sum(len(row['primary_combined_fields']) for row in selected)
        if len(selected) != 35 or denominator != 81:
            raise ValueError('Each arm must retain35 cases and81 requested fields')
        metrics = {}
        for variant in variants:
            correct = sum(sum(row['metrics'][variant]['fields'].values()) for row in selected)
            strict = sum(row['metrics'][variant]['strict_pass'] for row in selected)
            metrics[variant] = {'correct_fields': correct, 'field_micro_percent': 100 * correct / denominator,
                'strict_pass': strict, 'strict_pass_percent': 100 * strict / len(selected),
                'family_macro_percent': 100 * statistics.mean(scores[arm] for scores in all_families[variant].values())}
        result['arms'][arm] = {'answers': len(selected), 'field_denominator': denominator, 'metrics': metrics}
    result['family_count'] = 28
    result['family_field_percent'] = {variant: {family: {arm: 100 * value for arm, value in values.items()}
                                               for family, values in sorted(families.items())}
                                      for variant, families in all_families.items()}
    result['scope'] = ('Supplemental cross-review, not preregistered; added after invalid automatic judge outputs were observed. '
        'The original prospectively selected70 answers remain fixed. Two independent AI semantic reviews per answer, '
        'not human ground truth; numeric/schema composition is the same frozen code for both reviewers. '
        'Agreement can coexist with shared error or ambiguity. All70/162 denominators are retained, with clear and ambiguous subsets shown separately. '
        'Both-true/either-true ranges describe reviewer disagreement, not confidence intervals or truth bounds. '
        'Automatic comparisons use model repetition0 only; they do not replace the official three-repetition scores or original ordering rule. '
        'Family macro is descriptive with unchanged case/family weighting; no new ranking or inferential test is asserted. '
        'Unsupported-claim label agreement is unvalidated auxiliary information. Original notes and review reasons are preserved.')
    return result


def main():
    out = ROOT/'eval/v5/legacy-answer-audit'
    scoring = ROOT/'eval/v5/legacy-scoring-v55'
    inputs = {}

    def read_input(path):
        data = path.read_bytes()
        key = str(path.relative_to(ROOT))
        digest = api.sha(data)
        if key in inputs and inputs[key] != digest:
            raise ValueError('Input changed during comparison: ' + key)
        inputs[key] = digest
        return json.loads(data)

    manifest = read_input(out/'manifest.json')
    reviews = {}
    for kind, suffix in (('primary', 'review'), ('cross', 'crossreview')):
        lock = read_input(out/f'{kind}-review-lock.json')
        names = {f'batch-{batch}-{suffix}.json' for batch in (1, 2)}
        if not isinstance(lock.get('review_hashes'), dict) or set(lock['review_hashes']) != names:
            raise ValueError(kind + ' review lock must contain exactly the two expected filenames')
        reviews[kind] = {}
        for batch in (1, 2):
            path = out/f'batch-{batch}-{suffix}.json'
            reviews[kind][batch] = read_input(path)
            if inputs[str(path.relative_to(ROOT))] != lock['review_hashes'][path.name]:
                raise ValueError(kind + ' locked review hash changed')
    read_input(scoring/'mapping.json')
    if inputs[str((scoring/'mapping.json').relative_to(ROOT))] != manifest['source_mapping_sha256']:
        raise ValueError('Audit source mapping changed')
    verified = index_rows(_verified_mapping(scoring), 'Verified source mapping', 210)
    summary = read_input(scoring/'summary.json')
    automated = index_rows(summary['answers'], 'Automatic summary', 210)
    if summary['judgments'] != 420 or set(automated) != set(verified):
        raise ValueError('Complete automatic scoring of the verified210 source answers required')
    for ident, row in automated.items():
        if type(row['rep']) is not int or any(row.get(key) != value for key, value in verified[ident].items()):
            raise ValueError('Automatic summary differs from verified source mapping')
    dataset = read_input(ROOT/'eval/v5/legacy-migration/dataset.json')
    scenes = index_rows(dataset['scenarios'], 'Dataset', 35)
    scene_keys = {}
    for ident, scene in scenes.items():
        keys = [field['key'] for field in scene['answer_fields']]
        if (not keys or len(set(keys)) != len(keys) or any(not isinstance(k, str) or not k for k in keys)
                or not isinstance(scene['family'], str) or not scene['family']):
            raise ValueError('Dataset requires unique nonempty fields and named families')
        scene_keys[ident] = set(keys)
    if len({scene['family'] for scene in scenes.values()}) != 28 or sum(map(len, scene_keys.values())) != 81:
        raise ValueError('Expected35-case/28-family/81-field dataset')
    rows = []; public_ids = set(); selected_ids = set(); expected_primary = {}
    for batch in (1, 2):
        packet_path = out/f'batch-{batch}.json'
        packet = index_rows(read_input(packet_path), 'Blind packet', 35)
        packet_sha = inputs[str(packet_path.relative_to(ROOT))]
        if packet_sha != manifest['packet_sha256'][packet_path.name]:
            raise ValueError('Blind packet hash changed')
        mapping = index_rows(read_input(out/f'batch-{batch}-mapping-private.json'), 'Private mapping', 35)
        labels = {}
        for kind in ('primary', 'cross'):
            review = reviews[kind][batch]
            labels[kind] = index_rows(review['rows'], kind + ' review', 35)
            if review['source_batch_sha256'] != packet_sha or set(labels[kind]) != set(packet):
                raise ValueError('Both reviews must cover the same exact35-answer packet')
        if set(mapping) != set(packet) or public_ids & set(packet):
            raise ValueError('Packet/mapping identity mismatch or repeated public ID')
        public_ids.update(packet)
        for ident in packet:
            mapped = mapping[ident]
            scorer_id = mapped['scorer_id']
            if scorer_id in selected_ids or type(mapped['rep']) is not int or mapped['rep'] != 0:
                raise ValueError('Only unique prospectively selected repetition0 answers are eligible')
            selected_ids.add(scorer_id)
            auto = automated[scorer_id]
            if any(mapped[key] != auto[key] for key in ('case', 'arm', 'rep')):
                raise ValueError('Private mapping does not match scored source metadata')
            case = auto['case']; keys = scene_keys[case]
            if auto['family'] != scenes[case]['family']:
                raise ValueError('Source family differs from frozen dataset')
            payload = read_input(scoring/'payloads'/f'{scorer_id}.json')
            if api.sha(api.encode(payload)) != verified[scorer_id]['payload_sha256']:
                raise ValueError('Source payload hash changed')
            for key in ('question', 'requested_answer_fields', 'answer', 'reference', 'observations', 'requested_schema_policy'):
                if packet[ident]['payload'][key] != payload[key]:
                    raise ValueError('Blind packet differs from its verified source payload')
            if {f['key'] for f in payload['reference']['required_findings']} != keys:
                raise ValueError('Published dataset fields differ from source payload')
            valid = automatic_state(auto, keys)
            p = labels['primary'][ident]; c = labels['cross'][ident]
            p_fields, p_pass = primary.compose_review(p, payload, auto['runner_error'])
            c_fields, c_pass = primary.compose_review(c, payload, auto['runner_error'])
            p_differences = {rep: endpoint_differences(p_fields, p_pass, component) for rep, component in auto['judge_components'].items()}
            c_differences = {rep: endpoint_differences(c_fields, c_pass, component) for rep, component in auto['judge_components'].items()}
            common = p_fields == c_fields and p_pass == c_pass
            status = ('reviewers_disagree' if not common else 'invalid' if not valid else
                      'match' if all(not difference for difference in p_differences.values()) else 'mismatch')
            expected_primary[ident] = {'id': ident, 'scorer_id': scorer_id, 'case': case, 'arm': auto['arm'], 'rep': 0,
                'ambiguous': p['ambiguous'], 'independent_combined_fields': p_fields, 'independent_structured_pass': p_pass,
                'automated_stable_fields': auto['stable_fields'], 'automated_stable_structured_pass': auto['stable_structured_pass'],
                'automated_scored_agreement': auto['scored_agreement'], 'per_judge_disagreements': p_differences,
                'both_judges_match_independent_endpoints': set(p_differences) == {'0', '1'} and all(not d for d in p_differences.values()),
                'independent_notes': p['notes']}
            rows.append({'id': ident, 'scorer_id': scorer_id, 'case': case, 'family': auto['family'], 'arm': auto['arm'], 'rep': 0,
                'primary_review': p, 'cross_review': c, 'primary_combined_fields': p_fields, 'cross_combined_fields': c_fields,
                'primary_strict_pass': p_pass, 'cross_strict_pass': c_pass,
                'any_reviewer_ambiguous': p['ambiguous'] or c['ambiguous'], 'reviewers_share_endpoints': common,
                'differences': {'raw_semantic_fields': [k for k in p_fields if p['findings'][k] != c['findings'][k]],
                    'combined_fields': [k for k in p_fields if p_fields[k] != c_fields[k]], 'strict_pass': p_pass != c_pass,
                    'raw_semantic_pass': p['pass'] != c['pass'], 'unsupported_claims': p['unsupported_claims'] != c['unsupported_claims']},
                'automatic_valid': valid, 'automatic_integrity_errors': auto['integrity_errors'],
                'automatic_missing_judge_repetitions': sorted({'0', '1'} - set(auto['judge_components'])),
                'automatic_vs_common_endpoints': status,
                'per_judge_differences_from_primary': p_differences, 'per_judge_differences_from_cross': c_differences,
                'metrics': {'primary': {'fields': p_fields, 'strict_pass': p_pass},
                    'cross': {'fields': c_fields, 'strict_pass': c_pass},
                    'both_reviewers_true': {'fields': {k: p_fields[k] and c_fields[k] for k in p_fields}, 'strict_pass': p_pass and c_pass},
                    'either_reviewer_true': {'fields': {k: p_fields[k] or c_fields[k] for k in p_fields}, 'strict_pass': p_pass or c_pass},
                    'automatic_rep0': {'fields': auto['stable_fields'], 'strict_pass': auto['stable_structured_pass']}}})
    expected_grid = {(case, arm, 0) for case in scenes for arm in ARMS}
    if (selected_ids != {ident for ident, row in verified.items() if row['rep'] == 0}
            or len(rows) != 70 or {(row['case'], row['arm'], row['rep']) for row in rows} != expected_grid):
        raise ValueError('The fixed70-answer paired sample must remain complete')
    # This is the original comparator, unchanged. Only its derived summary is
    # refreshed; neither locked primary labels nor official automatic scores move.
    if primary.ROOT != ROOT:
        raise ValueError('Primary and supplemental comparators must share the same root')
    with contextlib.redirect_stdout(io.StringIO()):
        primary.main()
    official = read_input(out/'agreement-summary.json')
    official_rows = index_rows(official['rows'], 'Official primary comparison', 70)
    if official_rows != expected_primary:
        raise ValueError('Supplemental primary endpoints differ from official primary comparison')
    primary_clear = [row for row in expected_primary.values() if not row['ambiguous']]
    counts = {'answers': 70, 'ambiguous': 70 - len(primary_clear), 'nonambiguous': len(primary_clear),
              'all_both_judges_match': sum(row['both_judges_match_independent_endpoints'] for row in expected_primary.values()),
              'nonambiguous_both_judges_match': sum(row['both_judges_match_independent_endpoints'] for row in primary_clear),
              'automated_unresolved_in_sample': sum(not row['automated_scored_agreement'] for row in expected_primary.values())}
    if any(official[key] != value for key, value in counts.items()):
        raise ValueError('Official primary aggregate contradicts its bound rows')
    result = summarize(rows)
    result['input_sha256'] = inputs
    for relative, digest in inputs.items():
        if api.sha((ROOT/relative).read_bytes()) != digest:
            raise ValueError('Input changed during comparison: ' + relative)
    api.save(out/'cross-agreement-summary.json', result)
    print(api.encode({key: value for key, value in result.items() if key not in ('rows', 'family_field_percent', 'input_sha256')}))


if __name__ == '__main__':
    main()
