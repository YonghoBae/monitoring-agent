"""Read-only compact progress; never prints answers, prompts, or credentials."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rows(path):
    if not path.exists():
        return []
    result = []
    for line in path.read_text().splitlines():
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            break  # A concurrently written final line is not yet a completed row.
    return result


def snapshot():
    base = ROOT/'eval/v5'
    state = json.loads((base/'legacy-campaign-v55-state.json').read_text())
    source = base/'legacy-comparison-1/raw-comparison/results.jsonl'
    if not source.exists():
        data = (base/'legacy-migration/dataset.json').read_bytes()
        candidates = sorted((ROOT/'build/eval').glob('comparison-*'), key=lambda p: int(p.name.split('-')[-1]), reverse=True)
        for candidate in candidates:
            if (candidate/'dataset.json').exists() and (candidate/'dataset.json').read_bytes() == data:
                source = candidate/'results.jsonl'; break
    model = rows(source)
    judges = [rows(base/f'legacy-scoring-v55/judge-{rep}/results.jsonl') for rep in (0, 1)]
    return {'phase': state['phase'], 'model_answers': len(model), 'expected_model_answers': 210,
        'runner_errors': sum(bool(r.get('error')) for r in model),
        'judge_rows': [len(r) for r in judges], 'expected_judge_rows': [210, 210],
        'invalid_or_api_judgments': sum('error' in r for group in judges for r in group),
        'independent_audit_ready': (base/'legacy-answer-audit/manifest.json').exists(),
        'error': state.get('error')}


if __name__ == '__main__':
    print(json.dumps(snapshot(), ensure_ascii=False))
