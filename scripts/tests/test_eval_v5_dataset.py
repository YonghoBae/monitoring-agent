"""Independent checks of frozen capture views; never run Docker or paid APIs."""
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / 'eval/v5'
CAPTURE = EVAL / 'capture-20261117'


def read_json(path):
    return json.loads(path.read_text())


@unittest.skipUnless((CAPTURE / 'events.json').is_file(), 'Requires the private historical evaluation archive')
class EvalV5DatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenes = {s['id']: s for s in read_json(EVAL / 'dataset.json')['scenarios']}
        cls.gold = read_json(EVAL / 'gold.json')
        cls.provenance = read_json(EVAL / 'provenance.json')
        cls.events = {e['id']: e for e in read_json(CAPTURE / 'events.json')}
        cls.phases = read_json(CAPTURE / 'phases.json')

    def lines(self, ident):
        return [e['line'] for stream in self.scenes[ident]['world']['logs']
                for e in stream['entries']]

    def test_capture_manifest_covers_every_json_and_preserves_bytes(self):
        checked = set()
        for line in (CAPTURE / 'SHA256SUMS').read_text().splitlines():
            digest, name = line.split('  ', 1)
            with self.subTest(file=name):
                self.assertNotIn(name, checked)
                self.assertEqual(hashlib.sha256((CAPTURE / name).read_bytes()).hexdigest(), digest)
            checked.add(name)
        self.assertEqual(checked, {p.name for p in CAPTURE.glob('*.json')})
        self.assertEqual(checked, {'events.json', 'phases.json', 'environment.json',
                                   'validation.json', 'cleanup.json'})

    def test_source_manifest_covers_saved_sources_and_capture_urls(self):
        manifest = read_json(EVAL / 'sources/manifest.json')
        self.assertTrue(manifest['frozen_at'])
        names, urls = set(), set()
        for source in manifest['sources']:
            data = (EVAL / 'sources' / source['path']).read_bytes()
            with self.subTest(source=source['path']):
                self.assertNotIn(source['path'], names)
                self.assertEqual(len(data), source['bytes'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), source['sha256'])
                self.assertTrue(source['claim_scope'])
                self.assertTrue(source['url'].startswith('https://'))
            names.add(source['path'])
            urls.add(source['url'])
        self.assertEqual(names, {p.name for p in (EVAL / 'sources').iterdir()
                                 if p.is_file() and p.name != 'manifest.json'})
        self.assertTrue({p['source'] for p in self.phases.values()} <= urls)

    def test_independent_case_mapping_and_partial_reachability(self):
        # These IDs are reviewed against raw commands, not derived from builder logic.
        expected = {
            'case-201': ('pg_dump_version', 'normal', ['event-19', 'event-22']),
            'case-202': ('pg_init_permissions', 'fault', ['event-51', 'event-52']),
            'case-203': ('pg_dump_version', 'partial', ['event-24']),
            'case-204': ('pg_init_permissions', 'recovered', ['event-66', 'event-67']),
            'case-205': ('pg_dump_version', 'fault', ['event-23', 'event-18', 'event-24']),
            'case-206': ('pg_init_permissions', 'normal', ['event-42', 'event-43']),
            'case-207': ('pg_dump_version', 'recovered', ['event-25', 'event-28']),
            'case-208': ('pg_init_permissions', 'partial', ['event-51']),
        }
        self.assertEqual(set(self.scenes), set(expected))
        self.assertEqual(set(self.gold), set(expected))
        self.assertEqual(set(self.provenance), set(expected))
        for ident, (family, phase, visible) in expected.items():
            with self.subTest(case=ident):
                p = self.provenance[ident]
                self.assertEqual((p['family'], p['phase']), (family, phase))
                self.assertEqual(p['visible_event_ids'], visible)
                raw_phase = self.phases[family]['fault' if phase == 'partial' else phase]
                self.assertEqual(p['source_phase_event_ids'], raw_phase)
                self.assertTrue(set(visible) <= set(raw_phase))
                self.assertEqual(p['source'], self.phases[family]['source'])
                if phase == 'partial':
                    self.assertNotEqual(visible, raw_phase)

    def test_full_views_preserve_original_outputs_without_manufactured_lines(self):
        for ident, p in self.provenance.items():
            if p['phase'] == 'partial':
                continue
            with self.subTest(case=ident):
                remaining = list(self.lines(ident))
                for eid in p['visible_event_ids']:
                    event = self.events[eid]
                    if event['argv'][1] == 'logs':
                        # Preserve every line and its order within the timestamp merge.
                        original = (event['stdout'] + event['stderr']).splitlines()
                        self.assertEqual(remaining[:len(original)], sorted(original))
                        del remaining[:len(original)]
                    else:
                        wrapper = json.loads(remaining.pop(0))
                        self.assertEqual(set(wrapper), {'operation', 'exit_code', 'stdout', 'stderr'})
                        for field in ('stdout', 'stderr', 'exit_code'):
                            self.assertEqual(wrapper[field], event[field])
                self.assertEqual(remaining, [])

    def test_partial_views_retain_failure_but_no_cause_evidence(self):
        for ident, eid, operation in [('case-203', 'event-24', 'pg_dump'),
                                      ('case-208', 'event-51', 'container state')]:
            with self.subTest(case=ident):
                event = self.events[eid]
                status = (json.loads(event['stdout'])['ExitCode']
                          if operation == 'container state' else event['exit_code'])
                self.assertNotEqual(status, 0)
                self.assertEqual(len(self.lines(ident)), 1)
                self.assertEqual(json.loads(self.lines(ident)[0]), {
                    'operation': operation, 'exit_code': status,
                    'detail': 'Detailed output is unavailable in this view.'})
                self.assertEqual(self.gold[ident]['expected_status'], 'failed')
                self.assertEqual(self.gold[ident]['direct_cause'], 'unknown')

    def test_agent_content_excludes_collector_and_injection_metadata(self):
        forbidden = ['monitoring-v5-', 'init-fault', 'init-recovered', 'client-mismatch',
                     'pg_dump_version', 'pg_init_permissions', 'fault_file_metadata',
                     '0o600', '0o644', 'github.com', 'about.gitlab.com', 'chown']
        for ident, scene in self.scenes.items():
            # The separate runner must enforce this boundary; family metadata is private.
            visible = json.dumps({k: scene[k] for k in ('question', 'answer_fields', 'world')})
            with self.subTest(case=ident):
                for token in forbidden:
                    self.assertNotIn(token, visible)
                self.assertEqual(scene['world']['rag'], [])
                self.assertEqual(scene['world']['series'], [])
                self.assertEqual(scene['world']['containers'], ['service-db'])

    def test_fault_gold_is_backed_by_discriminating_capture_evidence(self):
        mismatch = self.events['event-24']
        self.assertNotEqual(mismatch['exit_code'], 0)
        self.assertIn('server version mismatch', mismatch['stderr'])
        self.assertIn('server version: 17.12', mismatch['stderr'])
        self.assertIn('pg_dump version: 16.16', mismatch['stderr'])
        self.assertIn('16.16', self.gold['case-205']['direct_cause'])
        self.assertIn('17.12', self.gold['case-205']['direct_cause'])
        state = json.loads(self.events['event-51']['stdout'])
        self.assertFalse(state['Running'])
        self.assertFalse(state['OOMKilled'])
        self.assertNotEqual(state['ExitCode'], 0)
        direct = '/docker-entrypoint-initdb.d/00-eval.sql: Permission denied'
        self.assertIn(direct, self.events['event-52']['stderr'])
        self.assertIn(direct, self.gold['case-202']['direct_cause'])
        for ident in ('case-202', 'case-205'):
            self.assertEqual(self.gold[ident]['expected_status'], 'failed')
        for eid in ('event-43', 'event-52', 'event-67'):
            self.assertIn('chmod: /var/run/postgresql: Operation not permitted',
                          self.events[eid]['stderr'])
        self.assertNotIn('/var/run/postgresql', self.gold['case-202']['direct_cause'])

    def test_success_gold_and_optional_facts_have_capture_support(self):
        for ident, eid in [('case-201', 'event-22'), ('case-207', 'event-28'),
                           ('case-204', 'event-66'), ('case-206', 'event-42')]:
            with self.subTest(case=ident):
                event = self.events[eid]
                self.assertEqual(event['exit_code'], 0)
                backup = ident in ('case-201', 'case-207')
                self.assertEqual(event['stdout'].strip(), '3:60' if backup else '3')
                gold = self.gold[ident]
                self.assertEqual(gold['expected_status'], 'succeeded')
                self.assertEqual(gold['direct_cause'], 'not_applicable')
                self.assertNotIn('numeric_contracts', gold)
                facts = gold['optional_numeric_facts_not_scored']
                self.assertEqual(len(facts), 1)
                self.assertEqual((facts[0]['value'], facts[0]['unit']), (3, 'count'))
                self.assertEqual({f['key'] for f in gold['reference']['required_findings']},
                                 {'operation_status', 'direct_cause'})
                self.assertIn('row count 3', gold['reference']['scope'])
                self.assertIn('sum 60' if backup else 'Fresh PGDATA', gold['reference']['scope'])
        for ident in ('case-202', 'case-203', 'case-205', 'case-208'):
            self.assertNotIn('numeric_contracts', self.gold[ident])
            self.assertEqual(self.gold[ident]['optional_numeric_facts_not_scored'], [])

    def test_questions_and_requested_fields_are_identical_across_each_family(self):
        for family in ('pg_dump_version', 'pg_init_permissions'):
            scenes = [s for s in self.scenes.values() if s['family'] == family]
            self.assertEqual(len(scenes), 4)
            first = scenes[0]
            for scene in scenes:
                self.assertEqual(scene['question'], first['question'])
                self.assertEqual(scene['answer_fields'], first['answer_fields'])
                self.assertEqual([f['key'] for f in scene['answer_fields']],
                                 ['operation_status', 'direct_cause'])


if __name__ == '__main__':
    unittest.main()
