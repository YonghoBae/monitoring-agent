"""Summarize completed, quote-reviewed runs without conflating format and truth."""
import argparse
import collections
import json
import statistics
from pathlib import Path


def completion(row):
    answer = row['answer'].strip()
    error = row.get('error', '')
    if 'timeout' in error.lower() or '조사 시간 한도 도달' in answer:
        return 'timeout'
    if error:
        return 'error'
    if not answer:
        return 'empty_answer'
    if answer.startswith('도구 호출 한도 도달'):
        return 'tool_budget_fallback'
    if answer.startswith('현재 상태 확인 불가'):
        return 'generic_fallback'
    if answer.startswith('거부됨:'):
        return 'tool_policy_denial'
    if answer.startswith('명령 실행 제안:'):
        return 'command_proposal'
    if answer.startswith('실행 승인 요청이 등록되지 않았습니다.'):
        return 'approval_filter_fallback'
    return 'returned_answer'


def summarize(rows, content, contract, scenes):
    keys = lambda row: (row['id'], row['arm'], row['rep'])
    reviewed = {keys(r): r for r in content['rows']}
    strict = {keys(r): r for r in contract['rows']}
    assert len(reviewed) == len(strict) == len(rows)
    groups = collections.defaultdict(list)
    details = []
    for row in rows:
        c = reviewed[keys(row)]
        done = completion(row)
        flags = bool(c['unsupported_claims'])
        observations = row['trace']['observations']
        detail = {
            'id': row['id'], 'arm': row['arm'], 'rep': row['rep'],
            'task_mode': scenes[row['id']]['task_mode'],
            'provenance': scenes[row['id']]['provenance']['kind'],
            'value_score': 100 * sum(x['correct_value'] for x in c['checks']) / len(c['checks']),
            'evidence_reviewed_field_score': c['score'],
            'output_contract_score': c.get('output_contract_score_after_exclusions', strict[keys(row)]['score']),
            'original_output_contract_score': strict[keys(row)]['score'],
            'schema_valid': c['schema_valid'], 'completion': done,
            'flagged_claims': c['unsupported_claims'],
            'all_requested_fields_grounded_no_flag_normal_return':
                c['score'] == 100 and not flags and done == 'returned_answer',
            'elapsed_seconds': row['elapsedMs'] / 1000,
            'observation_count': len(observations),
            'empty_observation_count': sum(o['status'] == 'empty' for o in observations),
        }
        details.append(detail)
        groups[row['arm']].append(detail)

    def aggregate(items):
        n = len(items)
        return {
            'n': n,
            **{k: statistics.mean(x[k] for x in items) for k in (
                'value_score', 'evidence_reviewed_field_score', 'output_contract_score', 'original_output_contract_score',
                'elapsed_seconds', 'observation_count', 'empty_observation_count')},
            'median_elapsed_seconds': statistics.median(x['elapsed_seconds'] for x in items),
            'schema_valid_count': sum(x['schema_valid'] for x in items),
            'answers_with_flagged_claims': sum(bool(x['flagged_claims']) for x in items),
            'all_requested_fields_grounded_no_flag_normal_return_count':
                sum(x['all_requested_fields_grounded_no_flag_normal_return'] for x in items),
            'completion_counts': dict(collections.Counter(x['completion'] for x in items)),
        }

    return {
        'scope': 'One run, macro-average over requested fields within each case. '
                 'Reviewed by an unblinded model, not independent human evaluation. '
                 'Normal return is a mechanical status, not proof of adequate reasoning. '
                 'Observation counts are backend observations, not model tool-call counts.',
        'summary': {arm: aggregate(items) for arm, items in groups.items()},
        'by_task_mode': {
            arm: {mode: aggregate([x for x in items if x['task_mode'] == mode])
                  for mode in sorted({x['task_mode'] for x in items})}
            for arm, items in groups.items()
        },
        'paired_content_outcomes': {
            f'{left}_vs_{right}': dict(collections.Counter(
                'left_higher' if l['evidence_reviewed_field_score'] > r['evidence_reviewed_field_score']
                else 'right_higher' if l['evidence_reviewed_field_score'] < r['evidence_reviewed_field_score']
                else 'tie'
                for l in groups[left] for r in groups[right]
                if (l['id'], l['rep']) == (r['id'], r['rep'])))
            for left, right in [('pi_plus', 'pi'), ('compact_plus', 'pi_plus'), ('compact_plus', 'production')]
            if left in groups and right in groups
        },
        'rows': details,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    read = lambda name: json.loads((args.run / name).read_text())
    rows = [json.loads(line) for line in (args.run / 'results.jsonl').read_text().splitlines()]
    scenes = {s['id']: s for s in read('dataset.json')['scenarios']}
    report = summarize(rows, read('content-scores.json'), read('scores.json'), scenes)
    (args.run / 'reviewed-summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
