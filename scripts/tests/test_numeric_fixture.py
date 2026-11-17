"""Pure validation always runs; real Docker/Prometheus checks are opt-in."""
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from numeric_fixture import FixtureSession, render_openmetrics


def scene():
    return {"world": {"evaluation_time": "2026-08-15T00:00:00Z", "step_seconds": 60,
                      "series": [
                          {"metric": "node_cpu_seconds_total", "labels": {"instance": "node-a", "mode": "idle"},
                           "samples": [[-600, 100], [0, 220]]},
                          {"metric": "node_cpu_seconds_total", "labels": {"instance": "node-b", "mode": "idle"},
                           "samples": [[-600, 50], [0, 350]]},
                          {"metric": "fixture_temperature", "labels": {"instance": "node-a"},
                           "samples": [[-600, 10], [-300, 10], [0, 40]]}
                      ]}}


class ValidationTests(unittest.TestCase):
    def test_interpolation_exact_names_sorted_and_eof(self):
        text, when = render_openmetrics(scene())
        self.assertEqual("2026-08-15T00:00:00Z", when)
        self.assertTrue(text.endswith("# EOF\n"))
        self.assertIn('node_cpu_seconds_total{instance="node-a",mode="idle"} 112 ', text)
        self.assertEqual(33, len(text.splitlines()) - 1)

    def test_input_sample_order_does_not_change_output(self):
        other = scene()
        other["world"]["series"][0]["samples"].reverse()
        self.assertEqual(render_openmetrics(scene()), render_openmetrics(other))

    def test_bad_inputs_fail_before_docker(self):
        mutations = [
            lambda w: w.update(evaluation_time="yesterday"),
            lambda w: w.update(evaluation_time="2026-08-15T00:00:00"),
            lambda w: w.update(step_seconds=0),
            lambda w: w.update(step_seconds=True),
            lambda w: w.update(step_seconds=1e-309),
            lambda w: w["series"][0].update(metric="bad-metric"),
            lambda w: w["series"][0].update(labels={"bad-label": "x"}),
            lambda w: w["series"][0].update(labels={"__name__": "fake"}),
            lambda w: w["series"][0].update(samples=[[0, float("nan")]]),
            lambda w: w["series"][0].update(samples=[[0, float("inf")]]),
            lambda w: w["series"][0].update(samples=[[0, True]]),
            lambda w: w["series"][0].update(samples=[[0, 1], [0, 2]]),
            lambda w: w["series"].append(copy.deepcopy(w["series"][0])),
            lambda w: w["series"][0].update(samples=[[-604801, 1], [0, 2]]),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                candidate = scene()
                mutate(candidate["world"])
                with self.assertRaises(ValueError):
                    render_openmetrics(candidate)

    def test_label_escaping(self):
        candidate = scene()
        candidate["world"]["series"][0]["labels"]["extra"] = 'a"b\\c\nd'
        self.assertIn('extra="a\\"b\\\\c\\nd"', render_openmetrics(candidate)[0])

    def test_submillisecond_collisions_are_rejected(self):
        candidate = scene()
        candidate["world"]["series"][0]["samples"] = [[0, 1], [0.00001, 2]]
        with self.assertRaises(ValueError):
            render_openmetrics(candidate)

    def test_failed_import_cleans_owned_container_and_directory(self):
        session = FixtureSession(scene())
        with patch("numeric_fixture._docker", side_effect=[RuntimeError("import failed"), ""]) as docker:
            with self.assertRaisesRegex(RuntimeError, "import failed"):
                session.__enter__()
        self.assertEqual(("rm", "-f", session.container_name + "-import"), docker.call_args.args)
        self.assertIsNone(session._temporary)


@unittest.skipUnless(os.environ.get("RUN_NUMERIC_FIXTURE_TESTS") == "1", "set RUN_NUMERIC_FIXTURE_TESTS=1 for Docker integration")
class RealPrometheusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = FixtureSession(scene())
        cls.session.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.session.close()

    def query(self, expression):
        url = self.session.prometheus_url + "/api/v1/query?" + urlencode({
            "query": expression, "time": self.session.evaluation_time})
        with urlopen(url, timeout=10) as response:
            return json.load(response)["data"]["result"]

    def test_real_rates_arithmetic_regex_and_aggregate(self):
        value = self.query('100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))')
        self.assertAlmostEqual(65, float(value[0]["value"][1]))
        value = self.query('sum(rate(node_cpu_seconds_total{instance=~"node-[ab]"}[5m]))')
        self.assertAlmostEqual(0.7, float(value[0]["value"][1]))

    def test_missing_metric_and_wrong_labels_are_empty(self):
        self.assertEqual([], self.query("unknown_metric"))
        self.assertEqual([], self.query('node_cpu_seconds_total{instance="absent"}'))

    def test_time_windows_change_actual_results(self):
        short = float(self.query("avg_over_time(fixture_temperature[2m])")[0]["value"][1])
        long = float(self.query("avg_over_time(fixture_temperature[10m])")[0]["value"][1])
        self.assertGreater(short, long)

    def test_invalid_syntax_is_prometheus_error(self):
        with self.assertRaises(HTTPError) as caught:
            self.query("sum(")
        self.assertEqual(400, caught.exception.code)
        self.assertEqual("bad_data", json.load(caught.exception)["errorType"])

    def test_stdio_close_eof_and_sigterm_cleanup(self):
        script = str(Path(__file__).resolve().parents[1] / "numeric_fixture.py")
        for ending in ("close", "eof", "sigterm", "error"):
            with self.subTest(ending=ending), tempfile.TemporaryDirectory() as directory:
                process = subprocess.Popen([sys.executable, script, "--stdio"],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True,
                                           env={**os.environ, "TMPDIR": directory})
                try:
                    process.stdin.write(json.dumps({"action": "open", "scenario": scene()}) + "\n")
                    process.stdin.flush()
                    ready = json.loads(process.stdout.readline())
                    self.assertEqual("ready", ready["status"], ready)
                    self.assertTrue(list(Path(directory).iterdir()))
                    if ending == "close":
                        process.stdin.write('{"action":"close"}\n')
                        process.stdin.flush()
                    elif ending == "eof":
                        process.stdin.close()
                    elif ending == "error":
                        process.stdin.write('{"action":"invalid"}\n')
                        process.stdin.flush()
                    else:
                        process.send_signal(signal.SIGTERM)
                    process.wait(timeout=30)
                    expected_code = 143 if ending == "sigterm" else 1 if ending == "error" else 0
                    self.assertEqual(expected_code, process.returncode,
                                     process.stderr.read())
                    self.assertEqual([], list(Path(directory).iterdir()))
                    with self.assertRaises(OSError):
                        urlopen(ready["prometheus_url"] + "/-/ready", timeout=1)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=30)
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if not stream.closed:
                            stream.close()


if __name__ == "__main__":
    unittest.main()
