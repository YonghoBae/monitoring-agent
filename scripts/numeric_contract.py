"""Deterministic, deliberately narrow numeric grading; no model or log access.

``grade_numeric(answer, quote, expected)`` requires a verbatim quote and an
expected ``value`` and explicit ``unit``. ``tolerance`` optionally contains
``absolute`` (in expected units) and ``relative`` (a fraction, not a percent).
The allowed error is max(absolute, abs(expected) * relative); defaults are zero.
SI and IEC byte labels retain their actual meanings. A rate never becomes an
interval total. Supported families are bytes, byte_rate, duration, percent,
count, and count_rate. Count aliases do not establish event identity.

Prose requires explicit units on every numeric token in the selected quote.
Unknown compound-unit suffixes and separated signs are rejected. Attached
Korean grammatical particles are limited to a small explicit allowlist; other
attached letters are not silently discarded. Unsupported notation is ungradable.
Multiple quantities are accepted only when their canonical values and families
are identical. Select a smaller *verbatim* quote to remove unrelated numbers;
that selection still needs an independent semantic/evidence check.

For a unitless JSON number only, an external requested schema can bind a root
field using ``binding={"kind": "json", "key": "free_gib", "unit": "GiB"}``.
The quote must then be a complete JSON object. Binding is a caller assertion
about the requested schema, never a guessed key/unit or a unit borrowed from
gold/logs. Duplicate keys, strings, booleans and nested values are rejected.

Optional ``dimension`` validates the expected unit family. Optional ``quantity``
and ``window`` are metadata, not automatically proven. An externally established
``observed_window`` is compared with ``window`` if both are provided; comparison
is structural equality, with no implicit time-window conversion. A pass means
only numeric correctness of this quote under this contract. It does NOT prove
the number answers the question, names the right quantity, covers the requested
window, or is supported by evidence. These checks must be graded separately.

All calculated numbers are JSON-safe decimal strings. Decimal arithmetic uses
bounded inputs and enough precision for exact supported arithmetic; floats in
expected are interpreted using their decimal string representation.
"""

from decimal import Decimal, InvalidOperation, localcontext
import json
import re

CONTRACT_VERSION = "1.1"

# unit -> (dimension, multiplier to canonical unit, canonical unit)
UNITS = {}
for _label, _factor in {"B": 1, "KB": 1000, "MB": 1000**2,
                        "GB": 1000**3, "TB": 1000**4,
                        "KiB": 1024, "MiB": 1024**2,
                        "GiB": 1024**3, "TiB": 1024**4}.items():
    UNITS[_label] = ("bytes", Decimal(_factor), "B")
    UNITS[_label + "/s"] = ("byte_rate", Decimal(_factor), "B/s")
for _label in ("count", "counts", "회", "건"):
    UNITS[_label] = ("count", Decimal(1), "count")
    UNITS[_label + "/s"] = ("count_rate", Decimal(1), "count/s")
for _label in ("s", "sec", "second", "seconds", "초"):
    UNITS[_label] = ("duration", Decimal(1), "s")
for _label in ("ms", "밀리초"):
    UNITS[_label] = ("duration", Decimal("0.001"), "s")
UNITS["%"] = ("percent", Decimal(1), "%")
DIMENSIONS = frozenset(spec[0] for spec in UNITS.values())
_NUMBER = r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?"
_TOKEN = re.compile(r"(?<![\w.,])" + _NUMBER + r"(?![\d.,])")
_UNIT = re.compile(r"\s*(?P<unit>" + "|".join(
    re.escape(unit) for unit in sorted(UNITS, key=len, reverse=True)
) + r")(?![A-Za-z0-9_/%])")
_KOREAN_ENDINGS = frozenset((
    "입니다", "이다", "이고", "이며", "이었다", "였다", "정도", "가", "는",
    "를", "의", "에", "로", "으로", "이", "인", "와", "과", "이라고", "라고",
    "이고요", "입니다만", "입니다요", "였습니다", "이었습니다",
))
_ADJACENT_UNIT = re.compile(r"\s+(?:" + "|".join(
    re.escape(unit) for unit in sorted(UNITS, key=len, reverse=True)
) + r")(?!\w)")


def _unsupported_suffix(tail):
    if re.match(r"\s*(?:[/\\*^·⋅∙×÷]|per\b)", tail):
        return True
    if _ADJACENT_UNIT.match(tail):
        return True
    # A valid prefix inside an unknown Unicode unit is not a valid whole unit.
    attached = re.match(r"[^\W\d_]+", tail)
    return bool(attached and attached.group() not in _KOREAN_ENDINGS)


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("not a number")
    raw = str(value)
    if len(raw) > 256:
        raise ValueError("number too long")
    try:
        result = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    if not result.is_finite() or abs(result.as_tuple().exponent) > 1000:
        raise ValueError("nonfinite or out-of-range decimal")
    return result


def _string(value):
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def grade_numeric(answer, quote, expected):
    """Return pass/fail/ungradable; numeric_correct is bool or None.

    Unknown/missing units and ambiguous parses are ungradable (never passes).
    Explicit incompatible units, window mismatches and out-of-tolerance values
    fail. A caller must never count ungradable as numerically correct.
    """
    result = {
        "contract_version": CONTRACT_VERSION, "status": "ungradable",
        "numeric_correct": None, "reason": "invalid_expected",
        "matched_span": None, "matched_unit": None, "normalized_value": None,
        "normalized_unit": None, "expected_normalized_value": None,
        "expected_normalized_unit": None,
        "allowed_error": None, "semantic_association": "not_assessed",
        "evidence_grounding": "not_assessed", "window_association": "not_assessed",
    }

    def stop(reason, status="ungradable"):
        result.update(reason=reason, status=status,
                      numeric_correct=False if status == "fail" else None)
        return result

    if not isinstance(expected, dict):
        return result
    with localcontext() as context:
        context.prec = 4096
        try:
            target = _decimal(expected["value"])
            unit = expected["unit"]
            if not isinstance(unit, str) or unit not in UNITS:
                return stop("unknown_expected_unit")
            family, factor, canonical = UNITS[unit]
            dimension = expected.get("dimension", family)
            if dimension not in DIMENSIONS or dimension != family:
                return stop("invalid_expected_dimension")
            tolerance = expected.get("tolerance", {})
            if not isinstance(tolerance, dict) or set(tolerance) - {"absolute", "relative"}:
                return stop("invalid_tolerance")
            absolute = _decimal(tolerance.get("absolute", 0))
            relative = _decimal(tolerance.get("relative", 0))
            if absolute < 0 or relative < 0:
                return stop("invalid_tolerance")
            target *= factor
            allowed = max(absolute * factor, abs(target) * relative)
        except (KeyError, ValueError, TypeError):
            return stop("invalid_expected")
        result.update(expected_normalized_value=_string(target),
                      expected_normalized_unit=canonical,
                      normalized_unit=canonical, allowed_error=_string(allowed))
        for key in ("quantity", "window", "observed_window"):
            if key in expected:
                result[key] = expected[key]
        if not isinstance(answer, str) or not isinstance(quote, str) or not quote:
            return stop("invalid_quote")
        if quote not in answer:
            return stop("quote_not_verbatim")
        if len(quote) > 65536:
            return stop("quote_too_long")
        if "window" in expected and "observed_window" in expected:
            if expected["window"] != expected["observed_window"]:
                return stop("window_mismatch", "fail")
            result["window_association"] = "caller_metadata_equal"

        candidates = []
        binding = expected.get("binding")
        if binding is not None:
            if (not isinstance(binding, dict) or binding.get("kind") != "json"
                    or not isinstance(binding.get("key"), str)
                    or not isinstance(binding.get("unit"), str)
                    or binding["unit"] not in UNITS):
                return stop("invalid_schema_binding")
            try:
                obj = json.loads(quote, parse_int=Decimal, parse_float=Decimal,
                                 parse_constant=lambda value: None,
                                 object_pairs_hook=_object)
                if not isinstance(obj, dict) or binding["key"] not in obj:
                    return stop("missing_schema_field")
                number = obj[binding["key"]]
                if not isinstance(number, Decimal):
                    return stop("schema_field_not_numeric")
                number = _decimal(number)
            except (ValueError, TypeError, RecursionError):
                return stop("invalid_bound_json")
            # The complete object is the verbatim span; never synthesize a field.
            candidates.append((number, binding["unit"], quote))
            result["schema_key"] = binding["key"]
        else:
            tokens = list(_TOKEN.finditer(quote))
            if not tokens:
                return stop("no_numeric_candidate")
            # Do not silently skip a malformed number or a numeric identifier.
            remainder = _TOKEN.sub("", quote)
            if any(character.isdigit() for character in remainder):
                return stop("malformed_or_embedded_numeric_token")
            for token in tokens:
                if re.search(r"[+\-−‒–—]\s*$", quote[:token.start()]):
                    return stop("ambiguous_numeric_sign")
                match = _UNIT.match(quote, token.end())
                if match is None:
                    return stop("missing_or_unknown_unit")
                if _unsupported_suffix(quote[match.end():]):
                    return stop("unsupported_unit_suffix")
                try:
                    number = _decimal(token.group().replace(",", ""))
                except ValueError:
                    return stop("invalid_numeric_candidate")
                candidates.append((number, match["unit"], quote[token.start():match.end()]))
        normalized = [(number * UNITS[label][1], UNITS[label][0])
                      for number, label, _ in candidates]
        if len(set(normalized)) != 1:
            return stop("conflicting_numeric_candidates")
        number, actual_family = normalized[0]
        result.update(normalized_value=_string(number),
                      normalized_unit=UNITS[candidates[0][1]][2],
                      matched_span=candidates[0][2], matched_unit=candidates[0][1])
        if actual_family != family:
            return stop("incompatible_unit_dimension", "fail")
        if abs(number - target) > allowed:
            return stop("outside_tolerance", "fail")
        result.update(status="pass", numeric_correct=True, reason="within_tolerance")
        return result
