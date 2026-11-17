"""Structural gold-contract checks; actual PromQL probes run against replay Prometheus."""
import math
from datetime import datetime
from pathlib import Path
import unittest
import sys

import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from numeric_fixture import render_openmetrics


class NumericDatasetContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v2 = yaml.safe_load((ROOT / 'src/test/resources/eval-dataset-v2.yml').read_text())
        cls.v3 = yaml.safe_load((ROOT / 'src/test/resources/eval-dataset-v3.yml').read_text())

    def test_preserves_all_original_alerts_and_playbooks(self):
        self.assertEqual(self.v3['version'], 3)
        self.assertEqual(self.v3['provenance']['kind'], 'synthetic')
        self.assertEqual(self.v3['provenance']['measurement_status'], 'not measured')
        self.assertEqual(len(self.v3['scenarios']), 38)
        for old, new in zip(self.v2['scenarios'], self.v3['scenarios']):
            for key in ('id', 'alert', 'playbook'):
                self.assertEqual(old[key], new[key], (new['id'], key))
            self.assertTrue(set(old['mocks'].get('metrics', [])) <= set(new['world']['declared_metrics']))

    def test_numeric_series_and_log_clock(self):
        for scene in self.v3['scenarios']:
            with self.subTest(scene=scene['id']):
                world = scene['world']
                now = datetime.fromisoformat(world['evaluation_time'].replace('Z', '+00:00'))
                active = datetime.fromisoformat(world['verify']['activeAt'].replace('Z', '+00:00'))
                self.assertLessEqual(active, now)
                self.assertEqual(world['step_seconds'], 60)
                identities = set()
                for series in world['series']:
                    identity = (series['metric'], tuple(sorted(series['labels'].items())))
                    self.assertNotIn(identity, identities)
                    identities.add(identity)
                    points = series['samples']
                    self.assertGreaterEqual(len(points), 2)
                    offsets = [p[0] for p in points]
                    self.assertEqual(offsets, sorted(set(offsets)))
                    self.assertLessEqual(max(offsets), 0)
                    for offset, value in points:
                        self.assertIsInstance(offset, int)
                        self.assertIsInstance(value, (int, float))
                        self.assertNotIsInstance(value, bool)
                        self.assertTrue(math.isfinite(value))
                    if series['metric'].endswith('_total'):
                        values = [p[1] for p in points]
                        self.assertEqual(values, sorted(values), identity)
                    if series['metric'] == 'up':
                        self.assertTrue({p[1] for p in points} <= {0, 1})
                        for left, right in zip(points, points[1:]):
                            if left[1] != right[1]:
                                # Linear interpolation must not create fractional up samples.
                                self.assertEqual(right[0] - left[0], world['step_seconds'])
                for target in world['logs']:
                    self.assertIn(target['source'], ('docker', 'host'))
                    self.assertTrue(target['name'])
                    for entry in target['entries']:
                        self.assertLessEqual(entry['offset_seconds'], 0)
                        self.assertIsInstance(entry['line'], str)
                self.assertEqual(sorted({s['metric'] for s in world['series']}), world['declared_metrics'])

    def test_gold_evidence_is_present_and_observable(self):
        for scene in self.v3['scenarios']:
            with self.subTest(scene=scene['id']):
                world, expected = scene['world'], scene['expected']
                refs = {'metric:' + s['metric'] for s in world['series']}
                refs.update('log:docker:' + l['name'] for l in world['logs'] if l['source'] == 'docker')
                refs.update('rag:' + str(i) for i in range(len(world['rag'])))
                refs.add('verify:status')  # STALE permits stopping before any metric query.
                for log in world['logs']:
                    if log['source'] == 'docker' and log['entries']:
                        self.assertTrue(any(-1800 <= e['offset_seconds'] <= 0 and log['name'] in e['line']
                                            for e in log['entries']), (scene['id'], log['name']))
                ids = set()
                for fact in expected['required_facts']:
                    self.assertNotIn(fact['id'], ids)
                    ids.add(fact['id'])
                    self.assertTrue(fact['description'])
                    self.assertTrue(fact['evidence'])
                    self.assertTrue(set(fact['evidence']) <= refs, fact)
                self.assertTrue(expected['acceptable_conclusions'])
                self.assertTrue(expected['allowed_unknowns'])
                self.assertIn('read_only_violation', expected['forbidden_events'])
                self.assertIn('unapproved_execution', expected['forbidden_events'])
                probes = scene['validation_probes']
                self.assertTrue(probes)
                for probe in probes:
                    self.assertIn(probe['expect'], ('nonempty', 'empty', 'error'))
                    self.assertTrue(probe['expr'])
                self.assertTrue(set(world['declared_metrics']) <= {p['expr'] for p in probes})

    def test_every_scenario_can_be_rendered_by_replay_engine(self):
        for scene in self.v3['scenarios']:
            with self.subTest(scene=scene['id']):
                rendered, when = render_openmetrics(scene)
                self.assertTrue(rendered.endswith('# EOF\n'))
                self.assertEqual(when, scene['world']['evaluation_time'])

    def test_stale_gold_allows_verification_only_and_numeric_worlds_agree(self):
        scenes = {s['id']: s for s in self.v3['scenarios']}
        for scene in scenes.values():
            if scene['world']['verify']['status'] == 'STALE':
                for fact in scene['expected']['required_facts']:
                    self.assertIn('verify:status', fact['evidence'])
        world = scenes['host_memory_leak']['world']
        latest = {s['metric']: s['samples'][-1][1] for s in world['series']}
        self.assertAlmostEqual(world['verify']['value'],
                               1 - latest['node_memory_MemAvailable_bytes'] / latest['node_memory_MemTotal_bytes'])
        series = {s['metric']: dict(s['samples']) for s in scenes['network_probe_latency']['world']['series']}
        total = series['probe_duration_seconds']
        for offset, dns in series['probe_dns_lookup_time_seconds'].items():
            self.assertLessEqual(dns, total[offset])

    def test_inventory_matches_explicit_down_cases(self):
        scenes = {s['id']: s for s in self.v3['scenarios']}
        self.assertNotIn('monitoring-agent-app', scenes['container_down_bind_error']['world']['containers'])
        self.assertNotIn('dcgm-exporter', scenes['prometheus_target_missing']['world']['containers'])
        self.assertNotIn('ollama', scenes['host_oom_killer']['world']['containers'])
        self.assertEqual(scenes['multi_container_down_daemon']['world']['containers'], [])


if __name__ == '__main__':
    unittest.main()
