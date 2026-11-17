"""Build a prospective controlled-regression dataset; no tools/models are invoked.

Only the 35 test scenes are selected. Their world, question, gold, alert and other
source content remain unchanged; answer_fields gains published type/unit schema
plus 19 source-question clauses. request-schemas.json remains the legacy 62-field
binding subset; it is not the complete 81-field semantic request.
No expected value, scoring kind, or unknown label enters the published schema.
Existing generated artifacts are never overwritten.
"""
import argparse
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path
from legacy_field_contract_v5 import build_request_schema

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT/'eval/v4/dataset.json'
DEFAULT_CONTRACTS = ROOT/'eval/v5/legacy-migration/field-contracts.json'
DEFAULT_OUT = ROOT/'eval/v5/legacy-migration'
DEFAULT_EXTRAS = DEFAULT_OUT/'extra-answer-fields.json'
DEFAULT_MEASUREMENTS = DEFAULT_OUT/'measurement-definitions.json'


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def build(source=DEFAULT_SOURCE, contracts_path=DEFAULT_CONTRACTS, out=DEFAULT_OUT,
          extras_path=DEFAULT_EXTRAS, replace_after_lineage=None, measurements_path=DEFAULT_MEASUREMENTS):
    source, contracts_path, out = Path(source), Path(contracts_path), Path(out)
    original = json.loads(source.read_text()); contracts = json.loads(contracts_path.read_text())
    if contracts.get('source_sha256') != digest(source): raise ValueError('Sidecar/source identity mismatch')
    scenes = [s for s in original['scenarios'] if s['split'] == 'test']
    if len(scenes) != 35 or len({s['id'] for s in scenes}) != 35: raise ValueError('Expected 35 unique source test scenes')
    pairs = {(s['id'], g['key']): g for s in scenes for g in s['gold']}
    entries = contracts['fields']
    if len(pairs) != 62 or len(entries) != 62 or {(f['case_id'], f['key']) for f in entries} != set(pairs):
        raise ValueError('Expected exact 62-field source/sidecar correspondence')
    for field in entries:
        if field['original_gold'] != pairs[(field['case_id'], field['key'])]: raise ValueError('Source gold changed in sidecar')
    extras_path = Path(extras_path); extras = json.loads(extras_path.read_text())
    if not isinstance(extras, dict) or set(extras)-{s['id'] for s in scenes} or sum(len(v) for v in extras.values()) != 19:
        raise ValueError('Expected 19 explicitly requested secondary-clause descriptors')
    measurements_path = Path(measurements_path); measurements = json.loads(measurements_path.read_text())
    if (not isinstance(measurements, dict) or set(measurements)-{s['id'] for s in scenes}
            or sum(len(v) for v in measurements.values()) != 8): raise ValueError('Expected eight explicit measurement definitions')
    built = []; schemas = {}
    for scene in scenes:
        case_fields = [f for f in entries if f['case_id'] == scene['id']]
        schema = build_request_schema(case_fields, measurements.get(scene['id'], {})); schemas[scene['id']] = schema
        questions = {f['key']: f['question'] for f in scene['answer_fields']}
        if set(questions) != set(schema['facts']): raise ValueError('Requested fields changed')
        for key, spec in schema['facts'].items():
            if spec['question'] != questions[key] or set(spec) not in ({'question', 'type', 'unit'}, {'question', 'type', 'unit', 'measurement'}):
                raise ValueError('Published schema leaks or changes source request')
        revised = copy.deepcopy(scene)
        revised['answer_fields'] = [{'key': f['key'], **schema['facts'][f['key']]} for f in scene['answer_fields']]
        seen = set(questions)
        for extra in extras.get(scene['id'], []):
            if (set(extra) != {'key', 'question', 'type', 'unit'} or extra['key'] in seen
                    or extra['type'] != 'string|null' or extra['unit'] is not None
                    or not isinstance(extra['question'], str) or not extra['question']
                    or extra['question'] not in scene['question']):
                raise ValueError('Secondary descriptor changes/duplicates a request or leaks non-request data')
            seen.add(extra['key']); revised['answer_fields'].append(copy.deepcopy(extra))
        for key in scene:
            if key != 'answer_fields' and revised[key] != scene[key]: raise ValueError('Source scene mutated')
        built.append(revised)
    dataset = {
        'version': 'legacy-controlled-v5-draft-1', 'status': 'built_not_validated_or_run',
        'source_revision': original.get('revision'),
        'coverage_claim': '35-case legacy controlled regression benchmark; not natural incident replay or population accuracy',
        'schema_change': 'Original 62 answer_fields plus explicit JSON type/unit, followed by 19 verbatim requested-clause descriptors; worlds, questions, gold and alerts unchanged',
        'request_schemas_scope': 'Legacy 62-field binding subset only; all 81 published requests are in each scene answer_fields',
        'scenarios': built,
    }
    targets = [out/name for name in ('dataset.json', 'request-schemas.json', 'build-manifest.json')]
    if any(p.exists() for p in targets):
        if replace_after_lineage is None: raise ValueError('Generated artifacts already exist; preserve prior attempts')
        lineage_dir = Path(replace_after_lineage); lineage = json.loads((lineage_dir/'lineage.json').read_text())
        for target in targets:
            if not target.is_file() or lineage['sha256'].get(target.name) != digest(target) or digest(lineage_dir/target.name) != digest(target):
                raise ValueError('Prior build must be preserved and match explicit amendment lineage')
    out.mkdir(parents=True, exist_ok=True)
    save(targets[0], dataset); save(targets[1], schemas)
    manifest = {
        'status': 'built_not_validated_or_run', 'source_dataset': str(source.resolve()),
        'source_dataset_sha256': digest(source), 'field_contracts': str(contracts_path.resolve()),
        'field_contracts_sha256': digest(contracts_path), 'built_dataset_sha256': digest(targets[0]),
        'request_schemas_sha256': digest(targets[1]), 'cases': 35, 'fields': 81,
        'legacy_binding_fields': 62, 'extra_requested_fields': 19,
        'measurement_definitions': str(measurements_path.resolve()), 'measurement_definitions_sha256': digest(measurements_path),
        'published_measurement_fields': 8,
        'extra_answer_fields': str(extras_path.resolve()), 'extra_answer_fields_sha256': digest(extras_path),
        'request_schemas_scope': 'Binding subset for original 62 fields; do not treat omitted secondary fields as unrequested',
        'prior_build_lineage': str(Path(replace_after_lineage).resolve()) if replace_after_lineage else None,
        'case_ids': [s['id'] for s in scenes],
        'family_counts': dict(Counter(s['family'] for s in scenes)),
        'source_quality_cases': dict(Counter(s['provenance']['kind'] for s in scenes)),
        'source_world_question_gold_preserved': True,
        'published_field_keys': ['key', 'question', 'type', 'unit'], 'optional_published_field_keys': ['measurement'],
        'builder_sha256': digest(__file__),
        'schema_adapter_sha256': digest(ROOT/'scripts/legacy_field_contract_v5.py'),
        'readiness': 'Requires source-audit, actual-tool preflight, root protocol and scorer freeze before any model run',
    }
    save(targets[2], manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--contracts', type=Path, default=DEFAULT_CONTRACTS)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--extras', type=Path, default=DEFAULT_EXTRAS)
    parser.add_argument('--measurements', type=Path, default=DEFAULT_MEASUREMENTS)
    parser.add_argument('--replace-after-lineage', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.contracts, args.out, args.extras, args.replace_after_lineage, args.measurements), ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
