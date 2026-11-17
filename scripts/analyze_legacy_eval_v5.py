"""Prospectively specified, paired family analysis of the controlled benchmark."""
import argparse
import hashlib
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARMS = ('pi_plus', 'compact_plus')
REPEATS = (0, 1, 2)


def family_scores(rows, *, override_unresolved=None, rep=None):
    grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for row in rows:
        if rep is not None and row['rep'] != rep:
            continue
        values = row['stable_fields']
        if not values or any(type(value) is not bool for value in values.values()):
            raise ValueError('Nonempty boolean field scores required')
        score = sum(values.values()) / len(values)
        if override_unresolved is not None and not row['scored_agreement']:
            score = override_unresolved[row['arm']]
        grouped[row['family']][row['arm']][row['case']].append(score)
    result = {}
    for family, arms in grouped.items():
        if set(arms) != set(ARMS) or set(arms[ARMS[0]]) != set(arms[ARMS[1]]):
            raise ValueError('Every family must retain the same cases in both arms')
        result[family] = {arm: statistics.mean(statistics.mean(scores) for scores in cases.values())
                          for arm, cases in arms.items()}
    if not result:
        raise ValueError('No families')
    return result


def percentile(sorted_values, p):
    at = (len(sorted_values) - 1) * p
    lo = int(at); hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] * (hi - at) + sorted_values[hi] * (at - lo) if hi != lo else sorted_values[lo]


def analyze(summary, dataset, *, draws=20000, seed=20261117):
    source_scenes = dataset['scenarios']
    if not source_scenes or len({s['id'] for s in source_scenes}) != len(source_scenes):
        raise ValueError('Nonempty dataset with unique case IDs required')
    if type(draws) is not int or draws <= 0:
        raise ValueError('Positive integer bootstrap draw count required')
    scenes = {s['id']: s for s in source_scenes}
    for scene in source_scenes:
        keys = [f['key'] for f in scene['answer_fields']]
        if not keys or len(set(keys)) != len(keys):
            raise ValueError('Nonempty unique published finding keys required')
    rows = summary['answers']
    if any(type(r.get('rep')) is not int or type(r.get('scored_agreement')) is not bool for r in rows):
        raise ValueError('Integer repetitions and boolean agreement labels required')
    expected = {(case, arm, rep) for case in scenes for arm in ARMS for rep in REPEATS}
    actual = [(r['case'], r['arm'], r['rep']) for r in rows]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError('Exact full paired case/arm/repeat grid required')
    for row in rows:
        scene = scenes[row['case']]
        if row['family'] != scene['family'] or set(row['stable_fields']) != {f['key'] for f in scene['answer_fields']}:
            raise ValueError('Row family or published finding coverage changed')
    families = family_scores(rows)
    differences = [100 * (v['compact_plus'] - v['pi_plus']) for _, v in sorted(families.items())]
    rng = random.Random(seed)
    samples = sorted(statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(draws))
    interval = [percentile(samples, .025), percentile(samples, .975)]
    difference = statistics.mean(differences)
    repeats = {}
    for rep in REPEATS:
        by_family = family_scores(rows, rep=rep)
        repeats[str(rep)] = 100 * statistics.mean(v['compact_plus'] - v['pi_plus'] for v in by_family.values())
    worst_for_compact = family_scores(rows, override_unresolved={'compact_plus': 0, 'pi_plus': 1})
    worst_for_pi = family_scores(rows, override_unresolved={'compact_plus': 1, 'pi_plus': 0})
    bounds = [100 * statistics.mean(v['compact_plus'] - v['pi_plus'] for v in group.values())
              for group in (worst_for_compact, worst_for_pi)]
    clear_compact = interval[0] > 0 and all(v > 0 for v in repeats.values()) and bounds[0] > 0
    clear_pi = interval[1] < 0 and all(v < 0 for v in repeats.values()) and bounds[1] < 0
    return {'case_count': len(scenes), 'family_count': len(families), 'answers': len(rows),
        'primary_family_macro_percent': {arm: 100 * statistics.mean(v[arm] for v in families.values()) for arm in ARMS},
        'compact_minus_pi_percentage_points': difference,
        'paired_family_bootstrap_sensitivity_interval': interval, 'draws': draws, 'seed': seed,
        'interval_interpretation': 'Sensitivity to selected family mix; NOT a population confidence interval for home servers',
        'repeat_differences_percentage_points': repeats,
        'unresolved_sensitivity_difference_bounds': bounds,
        'within_benchmark_ordering': 'compact_plus_ahead' if clear_compact else 'pi_plus_ahead' if clear_pi else 'not_established',
        'general_harness_ranking': 'not_established_by_this_selected_benchmark',
        'family_direction_counts': {'compact_ahead': sum(v > 0 for v in differences),
                                    'pi_ahead': sum(v < 0 for v in differences), 'tied': sum(v == 0 for v in differences)},
        'families': {family: {**{arm: 100 * value[arm] for arm in ARMS},
                              'difference_percentage_points': 100 * (value['compact_plus'] - value['pi_plus'])}
                     for family, value in sorted(families.items())}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', type=Path, default=ROOT/'eval/v5/legacy-scoring-v55/summary.json')
    parser.add_argument('--dataset', type=Path, default=ROOT/'eval/v5/legacy-migration/dataset.json')
    parser.add_argument('--out', type=Path, default=ROOT/'eval/v5/legacy-scoring-v55/family-analysis.json')
    args = parser.parse_args()
    result = analyze(json.loads(args.summary.read_text()), json.loads(args.dataset.read_text()))
    result['input_sha256'] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in (args.summary, args.dataset, Path(__file__), ROOT/'docs/EVAL-V5-LEGACY-ANALYSIS-PLAN.md')}
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'families'}, ensure_ascii=False, indent=2))
