"""Independent synthetic probes; no evaluation answers, logs or model calls.

Originally exercised frozen v1.1 and exposed six failing subtests, preserved in
EVAL-V5-NUMERIC-INDEPENDENT-REVIEW.md. The explicit import now tests only the
separate authorized draft; it does not select the active comparison scorer.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from numeric_contract_v12 import grade_numeric


class IndependentNumericContractTests(unittest.TestCase):
    def grade(self, text, value, unit, **metadata):
        return grade_numeric(text, text, {"value": value, "unit": unit, **metadata})

    def test_decimal_binary_labels_are_not_repaired(self):
        for text, value, unit, status in (
            ("0.5 GiB", "536870912", "B", "pass"),
            ("0.5 GB", "500000000", "B", "pass"),
            ("0.5 GB", "536870912", "B", "fail"),
            ("0.5 GiB", "500000000", "B", "fail"),
        ):
            with self.subTest(text=text, value=value):
                result = self.grade(text, value, unit)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["matched_unit"], text.split()[1])

    def test_unit_conversion_has_an_exact_boundary_in_expected_units(self):
        for text, status in (("1000.5 ms", "pass"),
                             ("999.5 ms", "pass"),
                             ("1000.5001 ms", "fail"),
                             ("999.4999 ms", "fail")):
            with self.subTest(text=text):
                result = self.grade(text, "1", "s", tolerance={"absolute": "0.0005"})
                self.assertEqual(result["status"], status)
                self.assertEqual(result["allowed_error"], "0.0005")

    def test_absolute_and_relative_allowances_use_max_not_sum(self):
        for text, status in (("102 B", "pass"), ("98 B", "pass"),
                             ("102.1 B", "fail"), ("97.9 B", "fail")):
            with self.subTest(text=text):
                result = self.grade(text, "100", "B", tolerance={"absolute": "1", "relative": "0.02"})
                self.assertEqual(result["allowed_error"], "2")
                self.assertEqual(result["status"], status)

    def test_negative_and_zero_targets_do_not_invert_tolerance(self):
        self.assertEqual(self.grade("-198 counts", "-200", "count", tolerance={"relative": "0.01"})["status"], "pass")
        self.assertEqual(self.grade("-197.99 counts", "-200", "count", tolerance={"relative": "0.01"})["status"], "fail")
        self.assertEqual(self.grade("0.001 B", "0", "B", tolerance={"relative": "100"})["status"], "fail")

    def test_rounded_binary_quantity_requires_declared_tolerance(self):
        text = "0.931323 GiB"
        self.assertEqual(self.grade(text, "1", "GB")["status"], "fail")
        accepted = self.grade(text, "1", "GB", tolerance={"absolute": "0.000001"})
        self.assertEqual(accepted["status"], "pass")
        self.assertEqual(accepted["allowed_error"], "1000")

    def test_rates_never_become_counts_or_stored_amounts(self):
        cases = (("2 MB/s", 2, "MB"), ("2 MB", 2, "MB/s"),
                 ("7 count/s", 7, "count"), ("7 counts", 7, "count/s"),
                 ("25 %", 25, "count"))
        for text, value, unit in cases:
            with self.subTest(text=text, unit=unit):
                result = self.grade(text, value, unit, window="one second", observed_window="one second")
                self.assertEqual(result["status"], "fail")
                self.assertEqual(result["reason"], "incompatible_unit_dimension")

    def test_equivalent_rate_scaling_is_allowed_within_its_dimension(self):
        result = self.grade("0.125 MiB/s", "131072", "B/s")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["normalized_value"], "131072")
        self.assertEqual(result["normalized_unit"], "B/s")

    def test_equivalent_restatements_are_distinguished_from_conflicting_values(self):
        self.assertEqual(self.grade("0.5 GiB (536870912 B)", "536870912", "B")["status"], "pass")
        self.assertEqual(self.grade("1000 ms and 1 s", "1", "s")["status"], "pass")
        self.assertEqual(self.grade("1 GB (1 GiB)", "1", "GB")["status"], "ungradable")

    def test_unknown_unit_notation_is_not_a_supported_scalar(self):
        for text in ("8 Gb", "8 GBps", "8 GB/hr", "8 counts/min", "8 liters"):
            with self.subTest(text=text):
                self.assertEqual(self.grade(text, "8", "GB")["status"], "ungradable")

    def test_compound_products_with_other_unit_spellings_are_not_bare_bytes(self):
        # Space-separated products and hyphenated unit names must not be
        # silently reduced to their recognized GB prefix.
        for text in ("8 GB h", "8 GB min", "8 GB-second"):
            with self.subTest(text=text):
                self.assertEqual(self.grade(text, "8", "GB")["status"], "ungradable")

    def test_draft_suffix_rejection_preserves_ordinary_prose(self):
        for text in ("8 GB available.", "8 GB free", "8 GB입니다."):
            with self.subTest(text=text):
                self.assertEqual(self.grade(text, "8", "GB")["status"], "pass")
        for text in ("8 GB hours", "8 GB kg", "8 GB-second", "8 GB–second"):
            with self.subTest(text=text):
                self.assertEqual(self.grade(text, "8", "GB")["status"], "ungradable")

    def test_scientific_and_grouped_numbers_normalize_without_float_rounding(self):
        self.assertEqual(self.grade("4.096e3 B", "4", "KiB")["status"], "pass")
        self.assertEqual(self.grade("1,000 MB", "1", "GB")["status"], "pass")
        self.assertEqual(self.grade("1.0000000000000000000000001 B", "1", "B")["status"], "fail")

    def test_schema_binding_selects_only_the_named_root_scalar(self):
        binding = {"kind": "json", "key": "free", "unit": "GiB"}
        text = '{"used": 999, "free": 0.5}'
        self.assertEqual(self.grade(text, "536870912", "B", binding=binding)["status"], "pass")
        wrong = {"kind": "json", "key": "used", "unit": "GiB"}
        self.assertEqual(self.grade(text, "536870912", "B", binding=wrong)["status"], "fail")
        for invalid in ('{"facts":{"free":0.5}}', '{"free":"0.5"}', '{"free":false}', '{"free":[0.5]}'):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.grade(invalid, "536870912", "B", binding=binding)["status"], "ungradable")

    def test_schema_binding_cannot_change_dimension(self):
        binding = {"kind": "json", "key": "rate", "unit": "count/s"}
        result = self.grade('{"rate":7}', "7", "count", binding=binding)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["reason"], "incompatible_unit_dimension")

    def test_bound_document_must_be_valid_json_even_outside_selected_field(self):
        # NaN and infinities are not JSON values. An unrelated invalid token
        # must not be repaired into null to make the complete object parseable.
        binding = {"kind": "json", "key": "free", "unit": "GB"}
        for constant in ("NaN", "Infinity", "-Infinity"):
            text = '{"free":8,"unrelated":' + constant + '}'
            with self.subTest(constant=constant):
                self.assertEqual(self.grade(text, "8", "GB", binding=binding)["status"], "ungradable")

    def test_window_metadata_never_claims_unperformed_temporal_conversion(self):
        result = self.grade("9 count", 9, "count", window="1h", observed_window="60min")
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["reason"], "window_mismatch")
        result = self.grade("9 count", 9, "count", window="1h")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["window_association"], "not_assessed")

    def test_numeric_pass_does_not_claim_quantity_or_observation_support(self):
        result = self.grade("3 counts", 3, "count", quantity="failed backups")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["semantic_association"], "not_assessed")
        self.assertEqual(result["evidence_grounding"], "not_assessed")


if __name__ == "__main__":
    unittest.main()
