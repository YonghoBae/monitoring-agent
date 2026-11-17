"""Synthetic contract checks: no frozen evaluation data and no model calls."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from numeric_contract import grade_numeric


class NumericContractTest(unittest.TestCase):
    def grade(self, text, value, unit, **extra):
        return grade_numeric(text, text, {"value": value, "unit": unit, **extra})

    def test_exact_cross_unit_parameterized(self):
        cases = [
            ("8 GB", "8000000000", "B"),
            ("7.450580596923828125 GiB", "8", "GB"),
            ("1.953125 MiB/s", "2048000", "B/s"),
            ("여유 공간 3,072 KiB입니다.", "3", "MiB"),
            ("0.037 s", "37", "ms"),
            ("응답시간 437 밀리초입니다.", ".437", "s"),
            ("-2.75 %", "-2.75", "%"),
            ("1.234e3 B", "1234", "B"),
            ("오류 137건입니다.", "137", "count"),
            ("재시도 29회", "29", "counts"),
            ("13 count/s", "13", "회/s"),
            ("0 B", "0", "GiB"),
        ]
        for text, value, unit in cases:
            with self.subTest(text=text):
                result = self.grade(text, value, unit)
                self.assertEqual(result["status"], "pass", result)
                self.assertIsInstance(result["normalized_value"], str)
                json.dumps(result)

    def test_original_label_is_preserved(self):
        expected = {"value": "8", "unit": "GB", "tolerance": {"absolute": ".00001"}}
        text = "여유 공간은 약 7.45058 GiB입니다."
        result = grade_numeric(text, text, expected)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["matched_unit"], "GiB")
        self.assertEqual(result["matched_span"], "7.45058 GiB")
        bad = text.replace("GiB", "GB")
        self.assertEqual(grade_numeric(bad, bad, expected)["status"], "fail")
        for _ in range(50):
            self.assertEqual(grade_numeric(text, text, expected), result)

    def test_unit_label_mutations_fail(self):
        for unit in ("GB", "MB", "B", "GiB/s", "%", "s", "count"):
            with self.subTest(unit=unit):
                self.assertEqual(self.grade("3.125 " + unit, "3.125", "GiB")["status"], "fail")

    def test_unseen_shaped_values_and_scaling_metamorphism(self):
        # Independent synthetic values, not examples from a judge or holdout file.
        for value in (17, 683, 1597, 104729):
            for scale in (1, 7, 31):
                with self.subTest(value=value, scale=scale):
                    target = value * scale
                    self.assertEqual(self.grade(f"{target * 1024} B", target, "KiB")["status"], "pass")
                    self.assertEqual(self.grade(f"{target * 1024 + 1} B", target, "KiB")["status"], "fail")

    def test_tolerance_boundary_and_decimal_exactness(self):
        cases = [("1.01 GB", "pass"), (".99 GB", "pass"),
                 ("1.010000000000000000001 GB", "fail")]
        for text, status in cases:
            with self.subTest(text=text):
                self.assertEqual(self.grade(text, "1", "GB", tolerance={"absolute": ".01"})["status"], status)
        self.assertEqual(self.grade("101 B", "100", "B", tolerance={"relative": ".01"})["status"], "pass")
        self.assertEqual(self.grade("102 B", "100", "B", tolerance={"relative": ".01"})["status"], "fail")
        self.assertEqual(self.grade(".1 B", "0", "B", tolerance={"relative": "100"})["status"], "fail")

    def test_missing_unknown_ambiguous_units(self):
        for text in ("8", "8 GB and 9 GB", "8 GB/s and 8 GB", "8 GB and 3",
                     "8 gb", "8 Gb", "8 GiBs", "8 GB/min", "true", "8 widgets",
                     "8 GB / s", "8 GB per second", "12,34 and 8 GB", "field2: 8 GB"):
            with self.subTest(text=text):
                self.assertEqual(self.grade(text, "8", "GB")["status"], "ungradable")
        self.assertEqual(self.grade("1 KiB (1024 B)", "1024", "B")["status"], "pass")

    def test_rate_is_not_interval_count(self):
        result = self.grade("6 회/s", "360", "count", window="60 seconds")
        self.assertEqual(result["reason"], "incompatible_unit_dimension")
        self.assertEqual(result["status"], "fail")

    def test_quotes_are_verbatim_and_semantics_separate(self):
        expected = {"value": "5", "unit": "GB", "quantity": "available"}
        result = grade_numeric("used: 5 GB", "5 GB", expected)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["semantic_association"], "not_assessed")
        self.assertEqual(result["evidence_grounding"], "not_assessed")
        for quote in ("5 GiB", "5GB", "", None):
            with self.subTest(quote=quote):
                self.assertEqual(grade_numeric("used: 5 GB", quote, expected)["status"], "ungradable")

    def test_schema_binding_requires_explicit_key_and_unit(self):
        binding = {"kind": "json", "key": "free_gib", "unit": "GiB"}
        text = '{"free_gib": 3.125, "other": 999}'
        result = self.grade(text, "3355443200", "B", binding=binding)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["matched_span"], text)
        self.assertEqual(result["schema_key"], "free_gib")
        self.assertEqual(self.grade(text, "3355443200", "B")["status"], "ungradable")
        for bad in ({"kind": "json", "key": "free_gib"},
                    {"kind": "json", "unit": "GiB"},
                    {"kind": "guess", "key": "free_gib", "unit": "GiB"}):
            with self.subTest(binding=bad):
                self.assertEqual(self.grade(text, 1, "B", binding=bad)["status"], "ungradable")

    def test_schema_field_types_duplicates_and_key_substitution(self):
        binding = {"kind": "json", "key": "total", "unit": "count"}
        cases = ['{"total": true}', '{"total": "17"}', '{"total": null}',
                 '{"total": [17]}', '{"total": {"value": 17}}',
                 '{"total": 17, "total": 18}', '{"other": 17}',
                 '{"total": NaN}', 'prefix {"total": 17}']
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(self.grade(text, 17, "count", binding=binding)["status"], "ungradable")

    def test_invalid_expected_and_tolerance_fail_closed(self):
        cases = [{"value": True, "unit": "count"}, {"value": "NaN", "unit": "B"},
                 {"value": "Infinity", "unit": "B"}, {"value": 1, "unit": "watts"},
                 {"value": 1, "unit": "B", "dimension": "energy"},
                 {"value": 1, "unit": "B", "dimension": "duration"},
                 {"value": 1, "unit": "B", "tolerance": {"absolute": -1}},
                 {"value": 1, "unit": "B", "tolerance": {"relative": True}},
                 {"value": 1, "unit": "B", "tolerance": {"percent": 1}}, {}, None]
        for expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(grade_numeric("1 B", "1 B", expected)["status"], "ungradable")

    def test_window_mismatch_not_silently_ignored(self):
        self.assertEqual(self.grade("17 건", 17, "count", window="1h", observed_window="24h")["status"], "fail")
        self.assertEqual(self.grade("17 건", 17, "count", window="1h")["window_association"], "not_assessed")
        self.assertEqual(self.grade("17 건", 17, "count", window="1h", observed_window="1h")["window_association"], "caller_metadata_equal")

    def test_compound_unit_continuations_fail_closed(self):
        # Added after the v1.0 freeze, using synthetic review probes only.
        for tail in ("·s", "*second", "\\s", "⋅s", "∙s", "×second", "÷s",
                     "^2", "²", " s", " seconds", "毎秒", "당", "Ω", " / s",
                     " per minute"):
            with self.subTest(tail=tail):
                self.assertEqual(self.grade("8 GB" + tail, 8, "GB")["status"], "ungradable")
        for tail in ("입니다.", "이고", "이며", "는", "로", "였다.", "이었다."):
            with self.subTest(tail=tail):
                self.assertEqual(self.grade("8 GB" + tail, 8, "GB")["status"], "pass")

    def test_separated_or_malformed_signs_fail_closed(self):
        for prefix in ("- ", "+ ", "−", "− ", "--", "+-", "-+", "++", "– "):
            with self.subTest(prefix=prefix):
                self.assertEqual(self.grade(prefix + "8 GB", 8, "GB")["status"], "ungradable")
        for text, value in (("-8 GB", -8), ("+8 GB", 8), ("값: 8 GB", 8)):
            with self.subTest(text=text):
                self.assertEqual(self.grade(text, value, "GB")["status"], "pass")


if __name__ == "__main__":
    unittest.main()
