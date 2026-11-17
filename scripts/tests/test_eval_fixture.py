import importlib.util
import pathlib
import unittest

PATH = pathlib.Path(__file__).resolve().parents[1] / "eval_fixture.py"
spec = importlib.util.spec_from_file_location("eval_fixture", PATH)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class FixtureContractTest(unittest.TestCase):
    def setUp(self):
        self.scene = {"alert": {"name": "HostHighCpuLoad", "labels": {"instance": "node-1"}},
                      "mocks": {"metrics": ["node_cpu_seconds_total"], "verify": {"status": "CONFIRMED"},
                                "prometheus": [{"keyword": "node_cpu", "response": "node_cpu_seconds_total{instance=node-1}: CPU observation: 92%"}]}}

    def query(self, query):
        return fixture.query(self.scene, query)

    def test_malformed_expression_is_invalid(self):
        self.assertEqual(self.query("sum(node_cpu_seconds_total) /")["status"], "invalid_argument")

    def test_nonexistent_metric_does_not_match_prefix(self):
        self.assertEqual(self.query("node_cpu_nonexistent_metric")["status"], "empty")

    def test_wrong_host_is_empty(self):
        self.assertEqual(self.query('node_cpu_seconds_total{instance="wrong-host"}')["status"], "empty")

    def test_unknown_label_is_not_invented(self):
        self.assertEqual(self.query('node_cpu_seconds_total{job="node"}')["status"], "unsupported_fixture")

    def test_alert_only_labels_are_not_metric_labels(self):
        self.scene["alert"]["labels"]["severity"] = "critical"
        self.assertEqual(self.query('node_cpu_seconds_total{severity="critical"}')["status"], "unsupported_fixture")

    def test_multiple_series_are_not_treated_as_only_the_first_target(self):
        self.scene["mocks"]["prometheus"][0]["response"] += '; node_cpu_seconds_total{instance=node-2}: 30%'
        self.assertEqual(self.query('node_cpu_seconds_total{instance="node-2"}')["status"], "unsupported_fixture")

    def test_equivalent_whitespace_and_quotes_are_accepted(self):
        for q in ["node_cpu_seconds_total", ' node_cpu_seconds_total { instance = "node-1" } ', "node_cpu_seconds_total{instance='node-1'}"]:
            self.assertEqual(self.query(q)["status"], "observation")

    def test_arithmetic_is_not_a_precomputed_summary(self):
        self.assertEqual(self.query("100 - node_cpu_seconds_total")["status"], "unsupported_fixture")

    def test_metric_name_regex_does_not_require_unselected_metric_data(self):
        self.scene["mocks"]["metrics"].append("up")
        self.assertEqual(self.query('{__name__=~"node_cpu.*",instance="node-1"}')["status"], "observation")
        self.assertEqual(self.query('{__name__="missing"}')["status"], "empty")

    def test_explicit_metric_identity_handles_numbered_families(self):
        self.scene["mocks"]["metrics"] = ["node_load1", "node_load5"]
        self.scene["mocks"]["prometheus"] = [{"keyword": "node_load", "response": "node_load5{instance=node-1}: 6.4"}]
        self.assertEqual(self.query('node_load5{instance="wrong-host"}')["status"], "empty")
        self.assertEqual(self.query('node_load5{instance="node-1"}')["status"], "observation")
        self.assertEqual(self.query("node_load1")["status"], "unsupported_fixture")

    def test_family_keyword_cannot_supply_another_defined_metric(self):
        self.scene["mocks"]["metrics"] = ["container_memory_usage_bytes", "container_cpu_usage_seconds_total"]
        self.scene["mocks"]["prometheus"] = [{"keyword": "container", "response": "container_memory_usage_bytes: 2GB"}]
        self.assertEqual(self.query("container_memory_usage_bytes")["status"], "observation")
        self.assertEqual(self.query("container_cpu_usage_seconds_total")["status"], "unsupported_fixture")

    def test_text_inside_string_is_not_a_metric_selector(self):
        self.assertNotEqual(self.query('label_replace(up, "x", "node_cpu", "y", ".*")')["status"], "observation")

    def test_wrong_alert_or_labels_do_not_confirm(self):
        self.assertEqual(fixture.verify(self.scene, "OtherAlert", {"instance": "node-1"})["status"], "UNKNOWN")
        self.assertEqual(fixture.verify(self.scene, "HostHighCpuLoad", {"instance": "wrong"})["status"], "UNKNOWN")
        self.assertEqual(fixture.verify(self.scene, "HostHighCpuLoad", {"instance": "node-1"})["status"], "CONFIRMED")


if __name__ == "__main__":
    unittest.main()
