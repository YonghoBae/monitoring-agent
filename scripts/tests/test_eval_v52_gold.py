"""Source-only v5.2 rubric checks; never read collected answers or judge outputs."""
import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / "eval/v5/comparison-2/frozen-inputs"
ORIGINAL_GOLD_SHA256 = "a6a56d3200881b7eef7836c35739699f0c6a5b28b827c27e195a7cc91088e3fc"
DATASET_SHA256 = "2f10a21b02a617c12fe009671b6e0c2cf54b673b9fd09889869f553066905447"


def load(path):
    return json.loads(path.read_text())


@unittest.skipUnless((FROZEN / 'eval/v5/dataset.json').is_file(), 'Requires the private historical evaluation archive')
class V52GoldIndependentChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load(FROZEN / "eval/v5/dataset.json")
        cls.scenes = {scene["id"]: scene for scene in cls.dataset["scenarios"]}
        cls.original = load(FROZEN / "eval/v5/gold.json")
        cls.gold = load(ROOT / "eval/v5/gold-v52.json")
        cls.manifest = load(ROOT / "eval/v5/comparison-2/manifest.json")

    def source(self, identifier):
        lines = [entry["line"] for log in self.scenes[identifier]["world"]["logs"]
                 for entry in log["entries"]]
        records = []
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return lines, records

    def findings(self, identifier):
        return {field["key"]: field["statement"]
                for field in self.gold[identifier]["reference"]["required_findings"]}

    def test_original_gold_and_collected_question_world_identity_preserved(self):
        for relative, expected in (("eval/v5/gold.json", ORIGINAL_GOLD_SHA256),
                                   ("eval/v5/dataset.json", DATASET_SHA256)):
            with self.subTest(path=relative):
                current = (ROOT / relative).read_bytes()
                frozen = (FROZEN / relative).read_bytes()
                self.assertEqual(current, frozen)
                self.assertEqual(hashlib.sha256(current).hexdigest(), expected)
                self.assertEqual(self.manifest["frozen_hashes"][relative], expected)

    def test_all_eight_questions_have_three_explicit_result_findings(self):
        self.assertEqual(len(self.scenes), 8)
        self.assertEqual(set(self.gold), set(self.scenes))
        for identifier, scene in self.scenes.items():
            with self.subTest(case=identifier):
                fields = self.gold[identifier]["reference"]["required_findings"]
                self.assertEqual([field["key"] for field in fields],
                                 ["operation_status", "secondary_check", "direct_cause"])
                self.assertTrue(all(field["statement"].strip() for field in fields))
                question = scene["question"]
                self.assertIn("실패했다면 기록으로 확인되는 직접 원인", question)
                self.assertIn("성공 여부나 원인을 알 수 없으면 구분", question)
                if "백업 작업" in question:
                    self.assertIn("제한적인 복원 검사", question)
                    self.assertIn("restor", self.findings(identifier)["secondary_check"].lower())
                else:
                    self.assertIn("PostgreSQL 초기화", question)
                    self.assertIn("초기 데이터 조회", question)
                    self.assertIn("query", self.findings(identifier)["secondary_check"].lower())

    def test_no_new_output_key_or_required_numeric_value(self):
        for identifier, scene in self.scenes.items():
            with self.subTest(case=identifier):
                self.assertEqual({field["key"] for field in scene["answer_fields"]},
                                 {"operation_status", "direct_cause"})
                reference = self.gold[identifier]["reference"]
                policy = reference["coverage_policy"]
                self.assertIn("ordinary prose or an explicit unknowns statement", policy)
                self.assertIn("no new agent JSON key is required", policy)
                self.assertIn("Numeric values are optional and unscored", policy)
                for finding in reference["required_findings"]:
                    # The optional marker count/sum must not become mandatory
                    # semantic answers merely because the fixture records them.
                    self.assertNotRegex(finding["statement"], r"\b(?:3|60)\b")

    def test_original_numeric_metadata_and_nonreference_fields_preserved(self):
        for identifier in self.scenes:
            with self.subTest(case=identifier):
                self.assertEqual(self.gold[identifier]["optional_numeric_facts_not_scored"],
                                 self.original[identifier]["optional_numeric_facts_not_scored"])
                before = {key: value for key, value in self.original[identifier].items() if key != "reference"}
                after = {key: value for key, value in self.gold[identifier].items() if key != "reference"}
                if identifier == "case-208":
                    self.assertEqual(before["expected_status"], "failed")
                    self.assertEqual(after["expected_status"], "unknown")
                    before["expected_status"] = "unknown"
                self.assertEqual(before, after)

    def test_secondary_success_has_its_own_observed_successful_query(self):
        for identifier in ("case-201", "case-204", "case-206", "case-207"):
            with self.subTest(case=identifier):
                lines, records = self.source(identifier)
                queries = [record for record in records if record.get("operation", "").startswith("SELECT count(*)")]
                self.assertEqual(len(queries), 1)
                self.assertEqual(queries[0]["exit_code"], 0)
                self.assertIn("succeeded", self.findings(identifier)["secondary_check"])
                if "restored" in queries[0]["operation"]:
                    self.assertIn("limited", self.findings(identifier)["secondary_check"])
                    self.assertIn("not proof of full backup integrity", self.findings(identifier)["secondary_check"])
                    self.assertTrue(any(record.get("operation") == "pg_dump" and record.get("exit_code") == 0 for record in records))
                else:
                    self.assertTrue(any("PostgreSQL init process complete" in line for line in lines))
                    self.assertIn("does not establish whole-service health", self.findings(identifier)["secondary_check"])

    def test_unobserved_secondary_execution_is_unknown_not_inferred_not_run(self):
        for identifier in ("case-202", "case-203", "case-205", "case-208"):
            with self.subTest(case=identifier):
                _, records = self.source(identifier)
                self.assertFalse(any(record.get("operation", "").startswith("SELECT count(*)") for record in records))
                statement = self.findings(identifier)["secondary_check"]
                self.assertTrue(statement.startswith("Unknown:"))
                if identifier != "case-208":
                    self.assertIn("do not infer", statement)
                else:
                    self.assertIn("does not establish whether the initial-data query ran", statement)

    def test_explicit_immediate_errors_support_only_their_recorded_mechanisms(self):
        lines, _ = self.source("case-202")
        self.assertTrue(any("psql: error:" in line and "/docker-entrypoint-initdb.d/00-eval.sql: Permission denied" in line for line in lines))
        self.assertFalse(any("PostgreSQL init process complete" in line for line in lines))
        self.assertEqual(self.gold["case-202"]["expected_status"], "failed")
        permission = self.findings("case-202")["direct_cause"]
        self.assertIn("Generic permission/access-denial wording is acceptable", permission)
        self.assertIn("not established", permission)
        lines, records = self.source("case-205")
        self.assertTrue(any("aborting because of server version mismatch" in line for line in lines))
        self.assertTrue(any(record.get("operation") == "pg_dump" and record.get("exit_code") == 1 for record in records))
        self.assertIn("Why that client was chosen is unobservable", self.findings("case-205")["direct_cause"])

    def test_named_backup_failure_is_distinct_from_generic_container_exit(self):
        _, backup_records = self.source("case-203")
        self.assertEqual(len(backup_records), 1)
        self.assertEqual(backup_records[0]["operation"], "pg_dump")
        self.assertEqual(backup_records[0]["exit_code"], 1)
        self.assertEqual(self.gold["case-203"]["expected_status"], "failed")
        self.assertTrue(self.findings("case-203")["direct_cause"].startswith("Unknown:"))
        lines, container_records = self.source("case-208")
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(container_records), 1)
        self.assertEqual(container_records[0]["operation"], "container state")
        self.assertEqual(container_records[0]["exit_code"], 1)
        self.assertEqual(self.gold["case-208"]["expected_status"], "unknown")
        self.assertTrue(all(statement.startswith("Unknown:") for statement in self.findings("case-208").values()))
        self.assertIn("not container exit", self.gold["case-208"]["reference"]["scope"])

    def test_scope_never_supplies_hidden_actor_or_production_recovery_evidence(self):
        for identifier in self.scenes:
            with self.subTest(case=identifier):
                reference = self.gold[identifier]["reference"]
                self.assertIn("No production recovery or universal health claim", reference["scope"])
                self.assertIn("No operational change is requested or established", reference["scope"])
                self.assertIn("No evidence of who changed permissions", reference["unobservable"])
                self.assertIn("reference is not observational evidence", reference["coverage_policy"])


if __name__ == "__main__":
    unittest.main()
