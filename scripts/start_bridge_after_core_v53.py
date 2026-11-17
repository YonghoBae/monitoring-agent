"""One-shot sequencing: finish frozen core grading, register new ledgers, validate v53."""
import json
import subprocess
import time
from pathlib import Path

import budget_registry as budget
import haiku_rejudge as api

ROOT = Path(__file__).resolve().parents[1]
NEW = ['eval/v5/legacy-bridge-validation-v53', 'eval/v5/legacy-scoring-v53/judge-0',
       'eval/v5/legacy-scoring-v53/judge-1']


def main():
    summary_path = ROOT/'eval/v5/canonical-core/scoring-1/summary.json'
    deadline = time.monotonic() + 3600
    while True:
        try:
            summary = api.read(summary_path)
        except (OSError, json.JSONDecodeError):
            summary = None
        if summary is not None:
            if summary.get('judgments') != 96 or len(summary.get('answers', [])) != 48:
                raise ValueError('Core stopped with an incomplete summary; no new paid validation')
            break
        if time.monotonic() > deadline:
            raise TimeoutError('Core grading did not complete; no new paid validation')
        time.sleep(5)
    registry = ROOT/'eval/paid-campaigns.json'
    history = ROOT/'eval/v5/registry-history/before-v53-registration.json'
    with budget._lock(ROOT):
        state = budget.state(ROOT, ROOT/'eval/v5/canonical-core/scoring-1')
        if state['unresolved_requests']:
            raise ValueError('Unresolved paid request prevents registration')
        value = api.read(registry)
        if any(path in value['campaigns'] for path in NEW) or history.exists():
            raise ValueError('One-shot registration already occurred; no implicit continuation')
        history.parent.mkdir(exist_ok=True)
        history.write_bytes(registry.read_bytes())
        before = api.sha(registry.read_bytes())
        value['campaigns'].extend(NEW)
        api.save(registry, value)
        api.save(history.with_name('v53-registration.json'), {
            'prior_registry_sha256': before, 'new_registry_sha256': api.sha(registry.read_bytes()),
            'added': NEW, 'core_summary_sha256': api.sha(summary_path.read_bytes()),
            'reason': 'New independent version after failed bridge; previous core grading fully completed before registry mutation',
            'global_budget_usd': 2, 'cost_before': state['total_campaigns_estimated_usd']})
    print('Core96 judgments complete; new v53 ledgers registered under unchanged global$2cap', flush=True)
    log = ROOT/'eval/v5/legacy-bridge-validation-v53-console.log'
    with log.open('x') as output:
        result = subprocess.run(['rtk', 'proxy', 'python3', 'scripts/validate_legacy_bridge_v53.py', '--execute'],
                                cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        raise SystemExit(f'Fresh bridge validation stopped with exit{result.returncode}; preserved log:{log}')
    result = api.read(ROOT/NEW[0]/'summary.json')
    print(json.dumps({k: result[k] for k in ('gate_passed', 'cases', 'judgments', 'failed')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
