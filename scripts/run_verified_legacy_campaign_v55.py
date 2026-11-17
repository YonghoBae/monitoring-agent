"""One-shot reviewed campaign, gated on fresh independent validation. No retries."""
import datetime
import fcntl
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import budget_registry as budget
import haiku_rejudge as api
import run_legacy_eval_v5 as runner
import score_legacy_eval_v55 as scorer
import structured_haiku_v54 as transport

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'eval/v5/legacy-migration'
STATE = ROOT/'eval/v5/legacy-campaign-v55-state.json'
CAMPAIGN = ROOT/'eval/v5/legacy-comparison-1'
MODEL = {'name': 'qwen3.5:9b-pi32k',
         'digest': '2872f35f2b99c438d19beb6cfaf7002a3150f04c0d850542ca52a554414c233f',
         'base_url': 'http://127.0.0.1:11434'}


def status(phase, **extra):
    value = {'phase': phase, 'at': datetime.datetime.now(datetime.timezone.utc).isoformat(), **extra}
    api.save(STATE, value)
    print(api.encode(value), flush=True)


def command(script, *args):
    subprocess.run(['rtk', 'proxy', sys.executable, 'scripts/'+script, *map(str, args)], cwd=ROOT, check=True)


def main():
    with (ROOT/'eval/v5/.verified-legacy-v55.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if STATE.exists() or CAMPAIGN.exists() or (BASE/'protocol.json').exists():
            raise ValueError('One-shot launch already started; inspect state, never silently repeat')
        try:
            status('waiting_for_independent_bridge_gate')
            gate = ROOT/'eval/v5/legacy-bridge-validation-v55/summary.json'
            deadline = time.monotonic()+1800
            while not gate.exists():
                if time.monotonic() > deadline:
                    raise TimeoutError('No completed independent gate; no model collection')
                time.sleep(5)
            value = api.read(gate)
            if value.get('gate_passed') is not True or value.get('judgments') != 60 or value.get('cases') != 20:
                raise ValueError('Fresh independent gate failed; no model collection')
            status('freezing_reviewed_protocol')
            scorer.freeze_plan(BASE)
            plan = BASE/'scoring-plan-v55.json'
            dataset = api.read(BASE/'dataset.json')
            api.save(BASE/'protocol.json', {
                'status': 'approved', 'benchmark_kind': 'controlled_regression',
                'case_ids': [scene['id'] for scene in dataset['scenarios']],
                'arms': ['pi_plus', 'compact_plus'], 'repeats': 3, 'expected_answers': 210,
                'model': MODEL, 'generation': {'temperature': 0, 'max_output_tokens': 1536, 'reasoning_effort': 'none'},
                'limits': {'uncached_tool_calls': 12, 'timeout_seconds': 90},
                'scoring_manifest': {'path': str(plan.relative_to(ROOT)), 'sha256': api.sha(plan.read_bytes())},
                'approval_basis': 'Root authorized after independent source/tool/code gates and fresh60-judgment gate; original user authorized autonomous comparison and independent AI review',
                'scope': '35 controlled cases/28 families; no population accuracy or forced general ranking',
                'analysis_plan_sha256': api.sha((ROOT/'docs/EVAL-V5-LEGACY-ANALYSIS-PLAN.md').read_bytes()),
                'global_budget_usd': 2})
            runner.preflight(BASE)
            status('warming_exact_model')
            request = urllib.request.Request(MODEL['base_url']+'/api/generate',
                data=api.encode({'model': MODEL['name'], 'prompt': 'Warmup.', 'stream': False,
                    'think': False, 'keep_alive': '30m',
                    'options': {'temperature': 0, 'num_predict': 1, 'num_ctx': 32768}}).encode(),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=180) as response:
                warmup = json.load(response)
            api.save(BASE/'model-warmup-v55.json', warmup)
            status('collecting_210_model_answers')
            runner.run(BASE, CAMPAIGN, execute=True)
            status('preparing_blind_scoring_and_audit')
            scorer.prepare(CAMPAIGN, scorer.OUT, plan)
            # Validate every serialized request before paying for any actual answer.
            mapping = scorer._verified_mapping(scorer.OUT)
            sizes = [len(api.encode(transport.request_body(api.read(scorer.OUT/'payloads'/f"{row['id']}.json"))).encode())+4096 for row in mapping]
            if max(sizes) > 100000:
                raise ValueError('An actual answer exceeds the conservative transport ceiling; no answer grading started')
            api.save(scorer.OUT/'request-size-preflight.json', {'answers': len(sizes), 'maximum_reserved_input': max(sizes),
                'all_under_transport_ceiling': True, 'global_budget': budget.preflight(ROOT, ROOT/scorer.LEDGERS[0])})
            command('prepare_legacy_answer_audit_v5.py')
            status('grading_two_passes', expected_judgments=420)
            scorer.run(scorer.OUT)
            status('analyzing_scoped_results')
            command('analyze_legacy_eval_v5.py')
            command('describe_eval_workflows_v5.py', CAMPAIGN)
            status('automated_complete_independent_answer_audit_pending',
                   summary=str(scorer.OUT/'summary.json'),
                   cost=budget.preflight(ROOT, ROOT/scorer.LEDGERS[0])['total_campaigns_estimated_usd'])
        except Exception as error:
            status('stopped', error_type=type(error).__name__, error=str(error),
                   policy='Artifacts retained; no automatic retry or altered gate')
            raise


if __name__ == '__main__':
    main()
