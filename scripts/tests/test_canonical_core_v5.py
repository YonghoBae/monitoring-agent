"""Offline canonical request, model-identity and pre-collection gate checks."""
import copy
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_canonical_core_v5 as build
import run_canonical_core_v5 as driver

class CanonicalCoreTest(unittest.TestCase):
    def setUp(self):
        self.source = build.read(build.ROOT/build.SOURCE_REL)
        self.gold = build.read(build.ROOT/build.GOLD_REL)
        self.dataset = build.transform(self.source, self.gold)
    def test_only_neutral_request_fields_change(self):
        actual = build.read(build.ROOT/build.BASE_REL/'dataset.json')
        self.assertEqual(actual, self.dataset); self.assertTrue(build.verify(actual))
        for original, scene in zip(self.source['scenarios'], actual['scenarios']):
            self.assertEqual({k:v for k,v in original.items() if k != 'answer_fields'},
                             {k:v for k,v in scene.items() if k != 'answer_fields'})
            self.assertEqual([f['key'] for f in scene['answer_fields']], list(build.KEYS))
            self.assertTrue(all(set(f) == {'key', 'question'} for f in scene['answer_fields']))
        for family in {s['family'] for s in actual['scenarios']}:
            fields = [s['answer_fields'] for s in actual['scenarios'] if s['family'] == family]
            self.assertTrue(all(f == fields[0] for f in fields))
        self.assertEqual(build.sha(build.ROOT/build.SOURCE_REL), build.SOURCE_SHA)
        self.assertEqual(build.sha(build.ROOT/build.GOLD_REL), build.GOLD_SHA)
    def test_canonical_mutation_and_overwrite_rejected(self):
        for field in ('question', 'world', 'family', 'answer_fields'):
            bad = copy.deepcopy(self.dataset); bad['scenarios'][0][field] = 'changed'
            with self.subTest(field=field), self.assertRaises(ValueError): build.verify(bad)
        with tempfile.TemporaryDirectory() as folder:
            build.build(folder)
            with self.assertRaises(ValueError): build.build(folder)
    def test_exact_order_and_delivery_required(self):
        plan = driver.order_plan(self.dataset)
        self.assertEqual(plan['first_positions'], {'pi_plus': 12, 'compact_plus': 12})
        rows = [{k:v for k,v in cell.items() if k in ('id', 'family', 'arm', 'rep')} |
                {'answer': '', 'error': 'explicit failure retained',
                 'trace': {'kind': 'delivered_tool_results', 'captureSupported': True}}
                for cell in plan['order']]
        self.assertTrue(driver.validate_grid(rows, self.dataset))
        for bad in (rows[:-1], rows[::-1], [rows[0]]*48):
            with self.assertRaises(ValueError): driver.validate_grid(bad, self.dataset)
        rows[0]['trace']['captureSupported'] = False
        with self.assertRaises(ValueError): driver.validate_grid(rows, self.dataset)
    def test_exact_loaded_digest_required_without_inference(self):
        model = {'name': 'qwen3.5:9b-pi32k', 'digest': driver.MODEL_DIGEST}
        exact = {'models': [model]}
        self.assertEqual(driver.loaded_identity(exact, exact, model), model)
        for tags, loaded in ((exact, {'models': []}), ({'models': [model | {'digest': 'wrong'}]}, exact),
                             (exact, {'models': [model | {'digest': 'wrong'}]})):
            with self.assertRaises(ValueError): driver.loaded_identity(tags, loaded, model)
    def test_run_without_execute_never_contacts_model(self):
        with patch.object(driver.urllib.request, 'urlopen', side_effect=AssertionError('Network forbidden')), \
             patch.object(driver, 'preflight', side_effect=AssertionError('Should stop before preflight')):
            with self.assertRaisesRegex(ValueError, 'execute'): driver.run()

class CanonicalGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); real = build.ROOT
        paths = set(driver.scorer.SCORING_INPUTS) | {
            build.SOURCE_REL, 'eval/v5/gold.json', build.PROVENANCE_REL,
            'scripts/build_canonical_core_v5.py', 'scripts/run_canonical_core_v5.py',
            driver.DATASET_REL, build.BASE_REL+'/build-manifest.json'}
        for rel in paths:
            dest = self.root/rel; dest.parent.mkdir(parents=True, exist_ok=True)
            if rel == 'eval/paid-campaigns.json':
                dest.write_text(json.dumps({'version': 1, 'budget_usd': 2, 'campaigns': []}))
            else:
                shutil.copyfile(real/rel, dest)
        for module in (build, driver):
            p = patch.object(module, 'ROOT', self.root); p.start(); self.addCleanup(p.stop)
        self.validation = {'manifest.json': 'validated-manifest', 'summary.json': 'validated-summary'}
        p = patch.object(driver.scorer, 'validation_gate', return_value=self.validation); p.start(); self.addCleanup(p.stop)
        p = patch.object(driver.scorer.budget, 'preflight', return_value={'registered': True}); p.start(); self.addCleanup(p.stop)
        p = patch.object(driver.urllib.request, 'urlopen', side_effect=AssertionError('Check must stay offline')); p.start(); self.addCleanup(p.stop)
        dataset = build.read(self.root/driver.DATASET_REL)
        self.base = self.root/build.BASE_REL
        self.gate = {'status': 'frozen', 'validation_hashes': self.validation,
            'frozen_hashes': {rel: build.sha(self.root/rel) for rel in paths}}
        build.save(self.base/'scoring-gate.json', self.gate)
        self.protocol = {'status': 'approved', 'benchmark_kind': 'confirmatory_canonical_core',
            'arms': list(driver.ARMS), 'repeats': 3, 'expected_answers': 48,
            'case_ids': [s['id'] for s in dataset['scenarios']], 'dataset_path': driver.DATASET_REL,
            'dataset_sha256': build.sha(self.root/driver.DATASET_REL), 'gold_path': build.GOLD_REL,
            'gold_sha256': build.GOLD_SHA, 'order_policy': driver.ORDER_POLICY,
            'generation': {'temperature': 0, 'max_output_tokens': 1536, 'reasoning_effort': 'none'},
            'limits': {'uncached_tool_calls': 12, 'timeout_seconds': 90},
            'model': {'name': 'qwen3.5:9b-pi32k', 'digest': driver.MODEL_DIGEST, 'base_url': 'http://no-network.invalid'},
            'scoring_manifest': {'path': build.BASE_REL+'/scoring-gate.json', 'sha256': build.sha(self.base/'scoring-gate.json')}}
        build.save(self.base/'protocol.json', self.protocol)
    def test_approved_check_is_offline_and_does_not_create_campaign(self):
        check = driver.preflight()
        self.assertEqual(len(check['order_plan']['order']), 48)
        self.assertFalse((self.base/'comparison-1').exists())
    def test_unapproved_protocol_and_model_identity_fail_closed(self):
        for key, value in (('status', 'draft'), ('expected_answers', 47), ('dataset_path', build.SOURCE_REL),
                           ('model', self.protocol['model'] | {'digest': 'different'})):
            build.save(self.base/'protocol.json', self.protocol | {key: value})
            with self.subTest(key=key), self.assertRaises(ValueError): driver.preflight()
    def test_changed_or_incomplete_scoring_freeze_fails_closed(self):
        for mutation in ('artifact', 'missing', 'gate'):
            with self.subTest(mutation=mutation):
                gate = copy.deepcopy(self.gate)
                if mutation == 'artifact': gate['frozen_hashes']['scripts/semantic_judge_v5.py'] = 'wrong'
                if mutation == 'missing': gate['frozen_hashes'].pop('scripts/score_canonical_core_v5.py')
                if mutation == 'gate': gate['validation_hashes'] = {}
                build.save(self.base/'scoring-gate.json', gate)
                protocol = copy.deepcopy(self.protocol); protocol['scoring_manifest']['sha256'] = build.sha(self.base/'scoring-gate.json')
                build.save(self.base/'protocol.json', protocol)
                with self.assertRaises(ValueError): driver.preflight()
    def simulated_run(self, complete):
        model = self.protocol['model']; metadata = json.dumps({'models': [model]})
        def fake_process(command, **kwargs):
            self.assertEqual(kwargs['env']['EVAL_DATASET'], driver.DATASET_REL)
            raw = self.root/'build/eval/comparison-offline'; raw.mkdir(parents=True)
            shutil.copyfile(self.root/driver.DATASET_REL, raw/'dataset.json')
            build.save(raw/'conditions.json', {'armOrderPolicy': driver.ORDER_POLICY})
            cells = driver.order_plan(build.read(self.root/driver.DATASET_REL))['order']
            rows = [{k:v for k,v in c.items() if k in ('id', 'family', 'arm', 'rep')} |
                    {'answer': 'synthetic', 'error': '', 'trace': {'kind': 'delivered_tool_results', 'captureSupported': True}}
                    for c in (cells if complete else cells[:1])]
            (raw/'results.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            if complete: kwargs['stdout'].write('COMPARISON_COMPLETE '+str(raw)+'\n'); kwargs['stdout'].flush()
            return driver.subprocess.CompletedProcess(command, 0 if complete else 1)
        with patch.object(driver.urllib.request, 'urlopen', side_effect=lambda *a, **kw: io.StringIO(metadata)), \
             patch.object(driver.subprocess, 'check_output', return_value='offline'), \
             patch.object(driver.subprocess, 'run', side_effect=fake_process):
            return driver.run(execute=True)
    def test_simulated_collection_records_actual_dataset_path_and_grid(self):
        result = self.simulated_run(True)
        self.assertEqual(result['status'], 'completed'); self.assertEqual(result['answers'], 48)
        self.assertEqual(result['dataset_path'], driver.DATASET_REL)
        self.assertIn(driver.DATASET_REL, result['frozen_hashes'])
        self.assertEqual(result['changed_inputs'], [])
    def test_simulated_incomplete_collection_preserves_partial_evidence(self):
        with self.assertRaises(RuntimeError): self.simulated_run(False)
        out = self.base/'comparison-1'
        self.assertEqual(build.read(out/'manifest.json')['status'], 'invalid_or_incomplete')
        self.assertEqual(len((out/'raw-comparison/results.jsonl').read_text().splitlines()), 1)
if __name__ == '__main__': unittest.main()
