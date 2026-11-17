"""Draft structured legacy-field grading; no model, network, or evidence lookup.

Publish build_request_schema(contracts) in the actual question before collecting
answers, then pass that same schema to grade_fields. This API cannot prove the
caller published it. A sidecar alone never authorizes guessing a missing unit.

Only the final JSON answer object is selected, either the final fenced block or
the final balanced raw object. Its entire tree is parsed strictly, including
unrelated properties: duplicate keys and NaN/Infinity are invalid everywhere.
Earlier prose/objects do not supply values. Source spans are exact answer slices.

The enclosing /facts path is verified before the verbatim facts-object span is
passed to numeric_contract_v12's root-key binding API. Codes are typed symbols,
not counts. Null, missing, and string 'unknown' remain distinct; null is an
explicit reported-unknown awaiting semantic judgment. Prose-only answers are
ungradable format, not factually false. They remain structured nonpasses.

All output booleans are strict booleans; arithmetic results never establish
entity/window association, evidence grounding, or complete-answer correctness.
"""
from dataclasses import dataclass
from decimal import Decimal
import copy
import json
import re
from numeric_contract_v12 import grade_numeric

CONTRACT_VERSION = 'legacy-fields-v5-draft-1'
_WS = ' \t\r\n'
_FENCE = re.compile(r'(?m)^[ \t]*```(?!`)([^\r\n]*)(?:\r?\n|$)')


def _constant(value):
    raise ValueError('Nonfinite/nonstandard JSON constant: ' + value)


def _number(text, integer=False):
    value = Decimal(text)
    if len(text) > 256 or not value.is_finite() or abs(value.as_tuple().exponent) > 1000:
        raise ValueError('Out-of-contract JSON number')
    return int(text) if integer else value


@dataclass
class _Node:
    value: object
    start: int
    end: int
    children: object = None


class _Parser:
    """JSON grammar with source spans, decoded-key uniqueness, and bounded depth."""
    def __init__(self, text, base):
        self.text, self.base, self.i = text, base, 0
        self.decoder = json.JSONDecoder(parse_int=lambda x: _number(x, True),
            parse_float=_number, parse_constant=_constant)

    def ws(self):
        while self.i < len(self.text) and self.text[self.i] in _WS: self.i += 1

    def parse(self, depth=0):
        if depth > 64: raise ValueError('JSON nesting limit')
        self.ws(); start = self.i
        if self.i >= len(self.text): raise ValueError('Missing JSON value')
        char = self.text[self.i]
        if char not in '{[':
            value, self.i = self.decoder.raw_decode(self.text, self.i)
            return _Node(value, self.base+start, self.base+self.i)
        is_object = char == '{'; closing = '}' if is_object else ']'
        value, children = ({}, {}) if is_object else ([], [])
        self.i += 1; self.ws()
        if self.i < len(self.text) and self.text[self.i] == closing:
            self.i += 1; return _Node(value, self.base+start, self.base+self.i, children)
        while True:
            self.ws()
            if is_object:
                if self.i >= len(self.text) or self.text[self.i] != '"': raise ValueError('JSON object key required')
                key, self.i = self.decoder.raw_decode(self.text, self.i)
                if key in value: raise ValueError('Duplicate JSON key')
                self.ws()
                if self.i >= len(self.text) or self.text[self.i] != ':': raise ValueError('JSON colon required')
                self.i += 1
            child = self.parse(depth+1)
            if is_object: value[key], children[key] = child.value, child
            else: value.append(child.value); children.append(child)
            self.ws()
            if self.i >= len(self.text): raise ValueError('Unclosed JSON container')
            char = self.text[self.i]; self.i += 1
            if char == closing: break
            if char != ',': raise ValueError('JSON comma required')
        return _Node(value, self.base+start, self.base+self.i, children)


def _raw_objects(answer):
    """Locate balanced outer objects; braces within JSON strings never terminate them."""
    spans = []; start = None; stack = []; quoted = escaped = False
    for pos, char in enumerate(answer):
        if start is None:
            if char == '{': start = pos; stack = ['}']; quoted = escaped = False
            continue
        if quoted:
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == '"': quoted = False
            continue
        if char == '"': quoted = True
        elif char in '{[': stack.append('}' if char == '{' else ']')
        elif char in '}]':
            if not stack or char != stack.pop(): raise ValueError('Unbalanced JSON delimiters')
            if not stack: spans.append((start, pos+1)); start = None
    if start is not None: raise ValueError('Unclosed final JSON object')
    return spans


def extract_final_facts(answer):
    """Return internal span nodes. Raises ValueError for invalid structured format."""
    if not isinstance(answer, str) or len(answer) > 262144: raise ValueError('Invalid answer text')
    fences = list(_FENCE.finditer(answer))
    if fences:
        if len(fences) % 2: raise ValueError('Unclosed answer fence')
        opening, closing = fences[-2:]
        if opening.group(1).strip().lower() not in ('', 'json') or closing.group(1).strip():
            raise ValueError('Final block is not a JSON block')
        start, end = opening.end(), closing.start()
        if answer[closing.end():].strip(): raise ValueError('JSON block is not final')
    else:
        spans = _raw_objects(answer)
        if not spans: raise ValueError('No final JSON answer object')
        start, end = spans[-1]
        if answer[end:].strip(): raise ValueError('JSON object is not final')
    text = answer[start:end]
    if len(text) > 65536: raise ValueError('JSON answer object too long')
    parser = _Parser(text, start); root = parser.parse(); parser.ws()
    if parser.i != len(text) or not isinstance(root.value, dict): raise ValueError('Entire final block must be one JSON object')
    facts = root.children.get('facts')
    if facts is None or not isinstance(facts.value, dict): raise ValueError('Root facts object required')
    return root, facts


def _contracts(contracts):
    if not isinstance(contracts, list) or not contracts: raise ValueError('Field contracts required')
    if len({f['case_id'] for f in contracts}) != 1 or len({f['key'] for f in contracts}) != len(contracts):
        raise ValueError('One case with unique requested keys required')
    for field in contracts:
        if field['original_gold']['key'] != field['key']: raise ValueError('Gold key mismatch')
    return contracts


def validate_measurement(measurement):
    """Validate only neutral, explicitly published measurement metadata."""
    if (not isinstance(measurement, dict) or set(measurement) != {'lookback_seconds', 'aggregation'}
            or type(measurement['lookback_seconds']) is not int or measurement['lookback_seconds'] <= 0
            or measurement['aggregation'] not in ('rate', 'increase')):
        raise ValueError('Invalid published measurement definition')
    return copy.deepcopy(measurement)

def schema_measurements(request_schema):
    return {key: validate_measurement(spec['measurement']) for key, spec in request_schema['facts'].items()
            if 'measurement' in spec}

def build_request_schema(contracts, measurements=None):
    """Return schema to publish to both answering arms, never an answer/gold payload."""
    fields = {}
    measurements = {} if measurements is None else measurements
    if not isinstance(measurements, dict): raise ValueError('Measurement mapping required')
    for field in _contracts(contracts):
        binding = field['answer_binding']; key = field['key']
        if binding.get('kind') != 'requested_json_field' or binding.get('json_pointer') != '/facts/'+key:
            raise ValueError('Undocumented requested field path')
        unit = binding.get('unit')
        if field['scoring_kind'] == 'numeric_quantity':
            authority = binding.get('unit_authority', {})
            if not isinstance(unit, str) or authority.get('kind') != 'explicit_requested_quantity' or authority.get('verbatim_question') != field['requested_question']:
                raise ValueError('Numeric unit lacks explicit question authority')
            if binding.get('expected_json_type') != 'number' or type(field['original_gold']['value']) not in (int, float):
                raise ValueError('Numeric binding requires an actual numeric source value and schema')
        elif unit is not None: raise ValueError('Categorical symbols cannot acquire numeric units')
        fields[key] = {'question': field['requested_question'], 'type': binding['expected_json_type'], 'unit': unit}
        if key in measurements: fields[key]['measurement'] = validate_measurement(measurements[key])
    if set(measurements)-set(fields): raise ValueError('Measurement for unrequested field')
    return {'version': 'legacy-request-schema-draft-1', 'facts': fields,
            'null_policy': 'reported_unknown_requires_semantic_judgment',
            'format': 'Return one final JSON object with a root facts object; do not duplicate keys.'}


def _json_safe(value):
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, dict): return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list): return [_json_safe(v) for v in value]
    return value


def grade_fields(answer, contracts, *, request_schema):
    """Grade explicit structured values; semantic association is always unassessed."""
    contracts = _contracts(contracts)
    output = {'contract_version': CONTRACT_VERSION, 'format_status': 'ungradable',
        'format_reason': None, 'answer_object_quote': None, 'answer_object_span': None,
        'facts_quote': None, 'fields': [], 'all_deterministic_fields_pass': False,
        'structured_nonpass': True, 'semantic_association': 'not_assessed', 'evidence_grounding': 'not_assessed'}
    schema_error = None
    try:
        if request_schema != build_request_schema(contracts, schema_measurements(request_schema)): raise ValueError('Published request schema differs or lacks explicit binding')
    except (ValueError, KeyError, TypeError) as error: schema_error = str(error)
    try:
        root, facts = extract_final_facts(answer)
        output.update(format_status='valid', answer_object_quote=answer[root.start:root.end],
                      answer_object_span=[root.start, root.end], facts_quote=answer[facts.start:facts.end])
    except (ValueError, TypeError, RecursionError) as error:
        output['format_reason'] = str(error); root = facts = None
    for field in contracts:
        key = field['key']; gold = field['original_gold']; kind = field['scoring_kind']
        result = {'field_id': field['field_id'], 'key': key, 'scoring_kind': kind,
            'status': 'ungradable', 'numeric_correct': None, 'value_correct': None,
            'reason': 'ungradable_format', 'presence': 'not_parsed', 'quote': None, 'span': None,
            'unit': field['answer_binding'].get('unit'), 'reported_unknown': False,
            'original_gold': copy.deepcopy(gold), 'window': copy.deepcopy(field['window']),
            'quantity_association': copy.deepcopy(field['quantity_association']),
            'evidence_policy': copy.deepcopy(field['evidence_policy']),
            'semantic_association': 'not_assessed', 'window_association': 'not_assessed',
            'evidence_grounding': 'not_assessed', 'structured_nonpass': True}
        output['fields'].append(result)
        if facts is None: continue
        if schema_error:
            result.update(reason='unbound_request_schema', schema_error=schema_error); continue
        node = facts.children.get(key)
        if node is None:
            result.update(reason='missing_field', presence='missing'); continue
        actual = node.value
        result.update(presence='null' if actual is None else 'value', quote=answer[node.start:node.end],
                      span=[node.start, node.end], actual_value=_json_safe(actual),
                      actual_json_type=('null' if actual is None else 'boolean' if type(actual) is bool
                          else 'number' if type(actual) in (int, Decimal) else 'string' if type(actual) is str
                          else 'object' if type(actual) is dict else 'array'))
        if actual is None:
            result.update(reason='explicit_null_requires_semantic_unknown_check', reported_unknown=True); continue
        if kind == 'numeric_quantity':
            contract = field.get('numeric_contract', {})
            unit = request_schema['facts'][key]['unit']
            # Preserve source numbers/tolerances, checking the duplicate sidecar view agrees.
            if (contract.get('value') != str(gold['value']) or contract.get('unit') != unit
                    or contract.get('tolerance') != {'absolute': str(gold['tolerance']), 'relative': '0'}):
                result['reason'] = 'inconsistent_numeric_sidecar'; continue
            expected = {'value': str(gold['value']), 'unit': unit,
                'tolerance': {'absolute': str(gold['tolerance']), 'relative': '0'},
                'binding': {'kind': 'json', 'key': key, 'unit': unit}}
            checked = grade_numeric(answer, output['facts_quote'], expected)
            result.update(status=checked['status'], numeric_correct=checked['numeric_correct'],
                          value_correct=checked['numeric_correct'], reason=checked['reason'],
                          numeric_result=checked, normalized_value=checked['normalized_value'],
                          normalized_unit=checked['normalized_unit'])
        elif kind in ('categorical_numeric_symbol', 'categorical', 'explicit_unknown'):
            if kind == 'categorical_numeric_symbol' and request_schema['facts'][key]['type'] == 'number':
                # JSON's published number type includes 1, 1.0 and 1e0. Preserve
                # exact magnitude without a hidden integer-literal restriction.
                correct = (type(actual) in (int, Decimal) and type(gold['value']) in (int, float)
                           and Decimal(str(actual)) == Decimal(str(gold['value'])))
            else:
                correct = type(actual) is type(gold['value']) and actual == gold['value']
            result.update(status='pass' if correct else 'fail', value_correct=bool(correct),
                          reason='typed_exact_match' if correct else 'typed_value_mismatch',
                          reported_unknown=type(actual) is str and actual == 'unknown')
        else: result['reason'] = 'unknown_scoring_kind'
        result['structured_nonpass'] = result['status'] != 'pass'
    output['all_deterministic_fields_pass'] = all(f['status'] == 'pass' for f in output['fields'])
    output['structured_nonpass'] = not output['all_deterministic_fields_pass']
    return output
