"""Prospective legacy scoring: frozen code, semantic findings plus exact numeric checks.

freeze creates scoring-plan.json BEFORE model collection. prepare subsequently
accepts only the completed 210-answer archive that froze that exact plan. The two
planned paid-ledger children are judge-0 and judge-1 (at most 210 calls each); they
share the global registry budget. No auto-registration, retry, or extra sharding.

The 35 source-numeric fields (28 quantities, seven numeric symbols) require both
semantic satisfaction and deterministic code pass. The other 46 findings use
semantic judgment, never adapter string equality. Field accuracy can retain
categorical credit in prose; invalid final-facts format separately prevents a
strict structured pass. Raw semantic disagreement is diagnostic; scored agreement
compares final combined fields, unsupported claims, and strict structured pass.
"""
import argparse
from collections import Counter
import copy
import datetime
import fcntl
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
import budget_registry as budget
import haiku_rejudge as api
from legacy_field_contract_v5 import build_request_schema, grade_fields, extract_final_facts, schema_measurements, validate_measurement
from run_legacy_eval_v5 import validate_grid, ARMS
from semantic_judge_v5 import SYSTEM, validate

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'eval/v5/legacy-migration'
OUT = ROOT/'eval/v5/legacy-scoring'
VALIDATION = ROOT/'eval/v5/legacy-bridge-validation'
VERSION = 'legacy-scoring-draft-1'
LEDGERS = ('eval/v5/legacy-scoring/judge-0', 'eval/v5/legacy-scoring/judge-1')
CODE = ('scripts/score_legacy_eval_v5.py', 'scripts/legacy_field_contract_v5.py',
    'scripts/numeric_contract_v12.py', 'scripts/semantic_judge_v5.py', 'scripts/budget_registry.py',
    'scripts/haiku_rejudge.py', 'scripts/run_legacy_eval_v5.py', 'scripts/build_legacy_eval_v5.py',
    'scripts/analyze_legacy_eval_v5.py', 'docs/EVAL-V5-LEGACY-ANALYSIS-PLAN.md')


def digest(path): return api.sha(Path(path).read_bytes())


def build_payload(payload, contracts, request_schema):
    """Shared production/holdout bridge. Caller provides exact published descriptors."""
    required_keys = {'question', 'requested_answer_fields', 'answer', 'reference', 'observations'}
    if not isinstance(payload, dict) or set(payload) != required_keys:
        raise ValueError('Blind payload requires exactly question/schema/answer/reference/observations')
    if request_schema != build_request_schema(contracts, schema_measurements(request_schema)): raise ValueError('Undocumented binding schema')
    published = payload['requested_answer_fields']
    if not isinstance(published, list) or any(not isinstance(f, dict) or set(f) not in ({'key', 'question', 'type', 'unit'}, {'key', 'question', 'type', 'unit', 'measurement'}) for f in published):
        raise ValueError('Published descriptors allow only key/question/type/unit and optional measurement')
    for field in published:
        if 'measurement' in field: validate_measurement(field['measurement'])
    keys = [f['key'] for f in published]
    if len(keys) != len(set(keys)): raise ValueError('Duplicate published field key')
    by_key = {f['key']: f for f in published}
    for key, spec in request_schema['facts'].items():
        if by_key.get(key) != {'key': key, **spec}: raise ValueError('Published base binding differs from scoring schema')
    findings = payload['reference']['required_findings']; finding_keys = [f['key'] for f in findings]
    if not finding_keys or len(finding_keys) != len(set(finding_keys)) or set(finding_keys) != set(keys):
        raise ValueError('Every semantic finding must be explicitly requested')
    observations = payload['observations']
    if not isinstance(observations, list): raise ValueError('Exact delivered observations list required')
    ids = []
    for observation in observations:
        if set(observation) != {'id', 'tool', 'input', 'output'} or not all(isinstance(observation[k], str) for k in observation):
            raise ValueError('Use exact delivered tool envelopes, not raw-world evidence')
        ids.append(observation['id'])
    if len(ids) != len(set(ids)): raise ValueError('Duplicate delivered observation ID')
    adapter = grade_fields(payload['answer'], contracts, request_schema=request_schema)
    contract_map = {f['key']: f for f in contracts}; numeric = []
    for field in adapter['fields']:
        original = contract_map[field['key']]['original_gold']
        if type(original['value']) not in (int, float): continue
        numeric.append({
            'key': field['key'], 'check_kind': field['scoring_kind'],
            'status': field['status'], 'numeric_correct': field['value_correct'],
            'reason': field['reason'], 'quote': field['quote'], 'unit': field['unit'],
            'normalized_value': field.get('normalized_value'), 'normalized_unit': field.get('normalized_unit'),
            'window': copy.deepcopy(by_key[field['key']].get('measurement')), 'semantic_association': 'not_assessed',
            'evidence_grounding': 'not_assessed',
        })
    prepared = copy.deepcopy(payload)
    prepared['deterministic_numeric_checks'] = numeric
    prepared['structured_format_check'] = {'status': adapter['format_status'], 'reason': adapter['format_reason']}
    prepared['requested_schema_policy'] = {'null_policy': request_schema['null_policy'], 'meaning': 'Every requested facts key must be present. Null may report unknown; semantic evidence must justify unknown. Numeric null remains ungradable.'}
    prepared['requested_schema_check'] = check_requested_schema(payload['answer'], published, request_schema['null_policy'])
    prepared['measurement_scope'] = {'base_field_keys': list(contract_map), 'all_field_keys': finding_keys,
        'numeric_field_keys': [f['key'] for f in numeric], 'categorical_string_equality_used': False}
    return prepared


def check_requested_schema(answer, published, null_policy):
    """Syntax and requested presence/type are distinct; no value equality here."""
    failures = []
    try: _, facts = extract_final_facts(answer)
    except (ValueError, TypeError, RecursionError) as error:
        return {'status': 'ungradable', 'valid': False, 'failures': [{'reason': str(error)}]}
    for descriptor in published:
        key = descriptor['key']; allowed = descriptor['type'].split('|')
        if any(t not in ('number', 'string', 'null', 'boolean', 'integer') for t in allowed):
            raise ValueError('Unsupported published JSON type')
        node = facts.children.get(key)
        if node is None:
            failures.append({'key': key, 'reason': 'missing_field'}); continue
        value = node.value
        actual = ('null' if value is None else 'boolean' if type(value) is bool else
                  'number' if type(value) in (int, Decimal) else 'string' if type(value) is str else
                  'object' if type(value) is dict else 'array')
        matches = (actual == 'null' and null_policy == 'reported_unknown_requires_semantic_judgment') or actual in allowed or ('integer' in allowed and actual == 'number' and value == int(value))
        if not matches: failures.append({'key': key, 'reason': 'wrong_json_type', 'actual_type': actual})
    return {'status': 'valid' if not failures else 'invalid', 'valid': not failures, 'failures': failures}

def grade_components(prepared_payload, semantic_result, runner_error=''):
    """Shared scoring/validation composition. Never repairs a model verdict."""
    result = validate(semantic_result, prepared_payload)
    semantic = {f['key']: f['satisfied'] for f in result['findings']}
    checks = prepared_payload['deterministic_numeric_checks']; numeric = {}
    for check in checks:
        key, status, correct = check['key'], check['status'], check['numeric_correct']
        if key in numeric or key not in semantic: raise ValueError('Duplicate/unknown deterministic field')
        if status not in ('pass', 'fail', 'ungradable') or (correct is not None and type(correct) is not bool):
            raise ValueError('Invalid deterministic status/boolean')
        if (status == 'pass' and correct is not True) or (status == 'fail' and correct is not False) or (status == 'ungradable' and correct is not None):
            raise ValueError('Inconsistent deterministic result')
        numeric[key] = {'status': status, 'numeric_correct': correct}
    scope = prepared_payload['measurement_scope']
    if set(numeric) != set(scope['numeric_field_keys']) or set(semantic) != set(scope['all_field_keys']):
        raise ValueError('Measurement scope changed')
    combined = {key: bool(satisfied and (key not in numeric or numeric[key]['status'] == 'pass'))
                for key, satisfied in semantic.items()}
    format_valid = prepared_payload['structured_format_check']['status'] == 'valid'
    schema_valid = prepared_payload['requested_schema_check']['valid']
    if type(schema_valid) is not bool: raise ValueError('Schema validity must be boolean')
    all_correct = all(combined.values())
    return {
        'combined_fields': combined, 'base_fields': {key: combined[key] for key in scope['base_field_keys']},
        'extra_fields': {key: value for key, value in combined.items() if key not in scope['base_field_keys']},
        'raw_semantic_fields': semantic, 'raw_semantic_pass': result['pass'],
        'numeric_labels': numeric, 'requested_schema_valid': schema_valid, 'requested_schema_status': prepared_payload['requested_schema_check']['status'], 'format_valid': bool(format_valid), 'format_ungradable': not format_valid,
        'all_findings_correct': bool(all_correct), 'unsupported_claims': result['unsupported_claims'],
        'structured_pass': bool(format_valid and schema_valid and all_correct and not result['unsupported_claims'] and not runner_error),
        'runner_error': bool(runner_error),
    }


def bridge_identity():
    """Hashes the exact pipeline to record in the independent validation manifest."""
    return {'system_sha256': api.sha(SYSTEM.encode()),
        'judge_code_sha256': digest(ROOT/'scripts/semantic_judge_v5.py'),
        'scorer_code_sha256': digest(__file__),
        'adapter_code_sha256': digest(ROOT/'scripts/legacy_field_contract_v5.py'),
        'numeric_contract_sha256': digest(ROOT/'scripts/numeric_contract_v12.py')}


def _inputs(base):
    dataset = api.read(base/'dataset.json'); sidecar = api.read(base/'field-contracts.json')
    schemas = api.read(base/'request-schemas.json'); references = api.read(base/'semantic-references.json')
    build = api.read(base/'build-manifest.json')
    identities = {'source_dataset_sha256': sidecar['source_sha256'],
        'field_contracts_sha256': digest(base/'field-contracts.json'), 'built_dataset_sha256': digest(base/'dataset.json')}
    if any(build.get(k) != v or references.get(k) != v for k, v in identities.items()):
        raise ValueError('Built/semantic/source identities disagree')
    if build['request_schemas_sha256'] != digest(base/'request-schemas.json'): raise ValueError('Binding subset changed')
    if build.get('measurement_definitions_sha256') != digest(base/'measurement-definitions.json'): raise ValueError('Published measurement definitions changed')
    measurements = api.read(base/'measurement-definitions.json')
    scenes = {s['id']: s for s in dataset['scenarios']}
    if len(scenes) != 35 or set(scenes) != set(schemas) or set(scenes) != set(references['cases']):
        raise ValueError('Expected exact 35-case schema/reference correspondence')
    counts = Counter()
    for case, scene in scenes.items():
        fields = [f for f in sidecar['fields'] if f['case_id'] == case]
        if schema_measurements(schemas[case]) != measurements.get(case, {}): raise ValueError('Published measurement mapping differs from binding schema')
        if [f['original_gold'] for f in fields] != scene['gold']: raise ValueError('Original 62-field gold changed')
        # Empty synthetic input validates schema coverage without consulting answers.
        build_payload({'question': scene['question'], 'requested_answer_fields': scene['answer_fields'],
            'answer': '', 'reference': references['cases'][case]['reference'], 'observations': []}, fields, schemas[case])
        counts['base'] += len(fields); counts['all'] += len(scene['answer_fields'])
        counts['numeric'] += sum(type(f['original_gold']['value']) in (int, float) for f in fields)
    if counts != {'base': 62, 'all': 81, 'numeric': 35}: raise ValueError('Expected 62 base/81 full/35 numeric fields')
    if references.get('blockers') != []: raise ValueError('Semantic source blockers unresolved')
    for name in ('source-audit.json', 'preflight.json'):
        gate = api.read(base/name)
        if gate.get('status') != 'passed' or gate.get('blockers') != [] or any(gate.get(k) != v for k, v in identities.items()):
            raise ValueError('Source/replay preflight not approved for current inputs: '+name)
    return dataset, sidecar, schemas, references


def _bridge_gate(base):
    manifest = api.read(VALIDATION/'manifest.json'); summary = api.read(VALIDATION/'summary.json')
    if summary.get('gate_passed') is not True or type(summary.get('cases')) is not int or summary['cases'] != 20 or type(summary.get('judgments')) is not int or summary['judgments'] != 60:
        raise ValueError('Fresh 20-case/60-judgment numeric-semantic bridge gate required')
    if any(manifest.get(key) != value for key, value in bridge_identity().items()): raise ValueError('Bridge was not validated against this exact pipeline')
    if manifest.get('holdout_sha256') != digest(base/'numeric-bridge-holdout.json'): raise ValueError('Bridge holdout identity changed')


def freeze_plan(base=BASE):
    base = Path(base); _inputs(base); _bridge_gate(base)
    for relative in LEDGERS: budget.preflight(ROOT, ROOT/relative)
    plan_path = base/'scoring-plan.json'; snapshot = base/'scoring-plan-inputs'
    if plan_path.exists() or snapshot.exists(): raise ValueError('New scoring-plan identity required; do not overwrite a freeze')
    paths = [ROOT/rel for rel in CODE]
    paths += [base/name for name in ('dataset.json', 'field-contracts.json', 'request-schemas.json',
        'extra-answer-fields.json', 'measurement-definitions.json', 'semantic-references.json', 'build-manifest.json', 'source-audit.json',
        'preflight.json', 'numeric-bridge-holdout.json')]
    paths += [VALIDATION/'manifest.json', VALIDATION/'summary.json', ROOT/'eval/paid-campaigns.json']
    hashes = {}
    for path in paths:
        relative = str(path.resolve().relative_to(ROOT.resolve())); target = snapshot/relative
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); hashes[relative] = digest(target)
    plan = {'version': VERSION, 'status': 'frozen', 'frozen_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'base_relative': str(base.resolve().relative_to(ROOT.resolve())),
        'snapshot_relative': str(snapshot.resolve().relative_to(ROOT.resolve())), 'frozen_hashes': hashes,
        'arms': list(ARMS), 'repeats': 3, 'expected_answers': 210, 'base_fields': 62, 'all_fields': 81,
        'source_numeric_fields': 35, 'semantic_only_fields': 46,
        'judge_ledgers': list(LEDGERS), 'max_paid_calls_per_child': 210, 'api_child_attempt_cap': 240,
        'global_budget_usd': 2, 'bridge_identity': bridge_identity(),
        'policy': 'Final fields = semantic AND code for 35 numeric fields; other 46 semantic. Invalid format is separately reported and prevents strict structured pass. Compare final combined fields/unsupported/structured pass; raw semantic disagreements remain diagnostics.',
        'scope': 'Controlled legacy regression; not natural incident replay or human validation'}
    api.save(plan_path, plan); return plan


def verify_plan(plan_path):
    plan_path = Path(plan_path); plan = api.read(plan_path)
    if plan.get('status') != 'frozen' or plan.get('version') != VERSION or plan.get('judge_ledgers') != list(LEDGERS):
        raise ValueError('Unsupported/nonfrozen scoring plan')
    snapshot = ROOT/plan['snapshot_relative']
    for relative, expected in plan['frozen_hashes'].items():
        if digest(ROOT/relative) != expected or digest(snapshot/relative) != expected: raise ValueError('Frozen scoring input changed: '+relative)
    if plan['bridge_identity'] != bridge_identity(): raise ValueError('Validated bridge pipeline changed')
    _bridge_gate(ROOT/plan['base_relative'])
    return plan


def prepare(campaign, out=OUT, plan_path=BASE/'scoring-plan.json'):
    campaign, out, plan_path = Path(campaign), Path(out), Path(plan_path)
    if out.resolve() != OUT.resolve(): raise ValueError('Use the two preregistered ledger children; no arbitrary scoring shard')
    plan = verify_plan(plan_path); base = ROOT/plan['base_relative']
    dataset, sidecar, schemas, references = _inputs(base)
    archive = api.read(campaign/'manifest.json')
    if archive.get('status') != 'completed' or archive.get('answers') != 210: raise ValueError('Complete 210-answer archive required')
    plan_relative = str(plan_path.resolve().relative_to(ROOT.resolve()))
    if archive.get('frozen_hashes', {}).get(plan_relative) != digest(plan_path): raise ValueError('This scoring plan was not frozen before model collection')
    for relative, expected in archive['frozen_hashes'].items():
        if digest(campaign/'frozen-inputs'/relative) != expected: raise ValueError('Model archive changed')
    dataset_relative = str((base/'dataset.json').resolve().relative_to(ROOT.resolve()))
    if archive['frozen_hashes'].get(dataset_relative) != digest(base/'dataset.json'): raise ValueError('Model dataset differs from scoring plan')
    rows = api.lines(campaign/'raw-comparison/results.jsonl'); validate_grid(rows, dataset)
    for relative in LEDGERS: budget.preflight(ROOT, ROOT/relative)
    if out.exists(): raise ValueError('Scoring output already exists; no silent retry')
    out.mkdir(); (out/'payloads').mkdir()
    scenes = {s['id']: s for s in dataset['scenarios']}; mapping = []
    rows = sorted(rows, key=lambda r: api.sha((r['id']+r['arm']+str(r['rep'])).encode()))
    for index, row in enumerate(rows):
        case = row['id']; scene = scenes[case]; ident = f'answer-{index+1:03d}'
        contracts = [f for f in sidecar['fields'] if f['case_id'] == case]
        payload = build_payload({'question': scene['question'], 'requested_answer_fields': scene['answer_fields'],
            'answer': row['answer'], 'reference': references['cases'][case]['reference'],
            'observations': row['trace']['observations']}, contracts, schemas[case])
        api.save(out/'payloads'/f'{ident}.json', payload)
        mapping.append({'id': ident, 'case': case, 'family': scene['family'], 'source_tier': scene['provenance']['kind'],
            'arm': row['arm'], 'rep': row['rep'], 'runner_error': row['error'], 'elapsed_ms': row['elapsedMs'],
            'payload_sha256': api.sha(api.encode(payload).encode())})
    api.save(out/'mapping.json', mapping)
    manifest = {'version': VERSION, 'plan': str(plan_path.resolve()), 'plan_sha256': digest(plan_path),
        'comparison': str(campaign.resolve()), 'comparison_manifest_sha256': digest(campaign/'manifest.json'),
        'comparison_results_sha256': digest(campaign/'raw-comparison/results.jsonl'),
        'mapping_sha256': api.sha(api.encode(mapping).encode()), 'expected_answers': 210, 'judge_ledgers': list(LEDGERS)}
    api.save(out/'manifest.json', manifest)
    for rep, relative in enumerate(LEDGERS):
        child = ROOT/relative
        if child.parent.resolve() != out.resolve(): raise ValueError('Ledger parent mismatch')
        child.mkdir(); (child/'raw').mkdir()
        api.save(child/'manifest.json', {'purpose': 'preregistered legacy judge replicate', 'judge_rep': rep,
            'planned_answers': 210, 'planned_max_paid_calls': 210, 'parent_manifest_sha256': digest(out/'manifest.json'),
            'prior_campaign_cost_usd': budget.preflight(ROOT, child)['prior_campaign_cost_usd']})
    return manifest


def _verified_mapping(out):
    out = Path(out)
    if out.resolve() != OUT.resolve(): raise ValueError('Unregistered scoring root')
    manifest = api.read(out/'manifest.json'); plan_path = Path(manifest['plan'])
    if digest(plan_path) != manifest['plan_sha256']: raise ValueError('Scoring plan changed')
    plan = verify_plan(plan_path); archive = Path(manifest['comparison'])
    if digest(archive/'manifest.json') != manifest['comparison_manifest_sha256'] or digest(archive/'raw-comparison/results.jsonl') != manifest['comparison_results_sha256']:
        raise ValueError('Original model archive changed after preparation')
    mapping = api.read(out/'mapping.json')
    if api.sha(api.encode(mapping).encode()) != manifest['mapping_sha256'] or len(mapping) != 210 or len({m['id'] for m in mapping}) != 210:
        raise ValueError('Mapping/grid changed')
    scenes = api.read(ROOT/plan['base_relative']/'dataset.json')['scenarios']
    expected = {(s['id'], arm, rep) for s in scenes for arm in ARMS for rep in range(3)}
    if {(m['case'], m['arm'], m['rep']) for m in mapping} != expected: raise ValueError('Missing or duplicate 210-grid cell')
    for m in mapping:
        payload = api.read(out/'payloads'/f"{m['id']}.json")
        if api.sha(api.encode(payload).encode()) != m['payload_sha256']: raise ValueError('Prepared payload changed')
    return mapping


@contextmanager
def ledger_run_lock(child):
    """A process owns a ledger's complete run; budget locking is independent."""
    lock = Path(child)/'.scorer-run.lock'
    with lock.open('a') as stream:
        try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error: raise ValueError('Scoring ledger is already running') from error
        try: yield
        finally: fcntl.flock(stream, fcntl.LOCK_UN)

def run(out=OUT, judge_rep=None):
    out = Path(out); mapping = _verified_mapping(out)
    if judge_rep is not None and (type(judge_rep) is not int or judge_rep not in (0, 1)): raise ValueError('Only planned judge-0/judge-1 are allowed')
    key = api.key_from_env(ROOT/'.env')
    for rep in ((0, 1) if judge_rep is None else (judge_rep,)):
        child = ROOT/LEDGERS[rep]
        with ledger_run_lock(child):
            if (child/'requests.jsonl').exists() or (child/'results.jsonl').exists(): raise ValueError('No ledger replay, retry, or automatic shard')
            budget.preflight(ROOT, child)
            for m in mapping:
                payload = api.read(out/'payloads'/f"{m['id']}.json")
                if api.sha(api.encode(payload).encode()) != m['payload_sha256']: raise ValueError('Prepared payload changed')
                row = {'id': m['id'], 'judge_rep': rep}
                if not payload['answer'].strip():
                    semantic = {'pass': False, 'unsupported_claims': False, 'answer_status': 'unanswered',
                        'findings': [{'key': f['key'], 'satisfied': False, 'answer_quote': '', 'observation_ids': [], 'reason': 'Empty answer'}
                                     for f in payload['reference']['required_findings']], 'reason': 'Deterministic empty-answer rule'}
                    row.update(semantic_result=semantic, components=grade_components(payload, semantic, m['runner_error']), method='deterministic_empty')
                else:
                    try: raw = budget.paid_call(api, ROOT, child, m['id'], payload, key, 'legacy-comparison', system=SYSTEM)
                    except Exception as error:
                        row.update(error=str(error), method='api_error'); api.append(child/'results.jsonl', row); summarize(out); raise
                    try:
                        semantic = api.response_json(raw)
                        row.update(semantic_result=semantic, components=grade_components(payload, semantic, m['runner_error']), method='haiku')
                    except Exception as error: row.update(error=str(error), method='invalid')
                api.append(child/'results.jsonl', row)
    return summarize(out)


def summarize(out=OUT):
    out = Path(out); mapping = _verified_mapping(out); judgments = []
    for rep, relative in enumerate(LEDGERS):
        for row in api.lines(ROOT/relative/'results.jsonl'):
            judgments.append({**row, '_ledger_rep': rep})
    ids = {m['id'] for m in mapping}
    if any(j.get('id') not in ids for j in judgments): raise ValueError('Judgment for unknown answer')
    answers = []
    for m in mapping:
        payload = api.read(out/'payloads'/f"{m['id']}.json"); js = [j for j in judgments if j['id'] == m['id']]
        counts = Counter(j.get('judge_rep') for j in js if type(j.get('judge_rep')) is int); errors = []
        if any(type(j.get('judge_rep')) is not int or j['judge_rep'] != j['_ledger_rep'] for j in js): errors.append('invalid_judge_rep')
        if any(counts[rep] > 1 for rep in (0, 1)): errors.append('duplicate_judge_rep')
        if set(counts) != {0, 1}: errors.append('missing_judge_rep')
        valid = {}
        for j in js:
            rep = j.get('judge_rep')
            if type(rep) is not int or rep not in (0, 1) or rep != j['_ledger_rep'] or counts[rep] != 1: continue
            try: valid[rep] = grade_components(payload, j['semantic_result'], m['runner_error'])
            except Exception: errors.append('invalid_judgment')
        complete = not errors and len(valid) == 2 and len(js) == 2
        signatures = [(tuple(sorted(c['combined_fields'].items())), c['unsupported_claims'], c['structured_pass']) for c in valid.values()]
        raw = [(tuple(sorted(c['raw_semantic_fields'].items())), c['unsupported_claims'], c['raw_semantic_pass']) for c in valid.values()]
        agreement = bool(complete and signatures[0] == signatures[1])
        scope = payload['measurement_scope']; stable = {key: bool(complete and all(c['combined_fields'][key] for c in valid.values())) for key in scope['all_field_keys']}
        base_stable = {key: stable[key] for key in scope['base_field_keys']}
        answers.append({**m, 'complete': bool(complete), 'scored_agreement': agreement,
            'raw_semantic_disagreement': bool(complete and raw[0] != raw[1]), 'integrity_errors': sorted(set(errors)),
            'stable_fields': stable, 'stable_base_fields': base_stable,
            'stable_all_findings_correct': bool(complete and all(stable.values())),
            'stable_unsupported_free': bool(complete and all(not c['unsupported_claims'] for c in valid.values())),
            'stable_structured_pass': bool(agreement and all(c['structured_pass'] for c in valid.values())),
            'format_ungradable': payload['structured_format_check']['status'] != 'valid',
            'requested_schema_invalid': not payload['requested_schema_check']['valid'],
            'numeric_labels': {c['key']: {'status': c['status'], 'numeric_correct': c['numeric_correct']} for c in payload['deterministic_numeric_checks']},
            'judge_components': {str(rep): value for rep, value in valid.items()}})
    arms = {}
    for arm in ARMS:
        rows = [r for r in answers if r['arm'] == arm]
        full_n = sum(len(r['stable_fields']) for r in rows); base_n = sum(len(r['stable_base_fields']) for r in rows)
        arms[arm] = {'n': len(rows), 'all_finding_denominator': full_n, 'base_field_denominator': base_n,
            'stable_all_field_micro_percent': 100*sum(sum(r['stable_fields'].values()) for r in rows)/full_n,
            'stable_base_field_micro_percent': 100*sum(sum(r['stable_base_fields'].values()) for r in rows)/base_n,
            'stable_all_field_case_macro_percent': 100*sum(sum(r['stable_fields'].values())/len(r['stable_fields']) for r in rows)/len(rows),
            'stable_base_field_case_macro_percent': 100*sum(sum(r['stable_base_fields'].values())/len(r['stable_base_fields']) for r in rows)/len(rows),
            'stable_all_findings_correct': sum(r['stable_all_findings_correct'] for r in rows),
            'stable_unsupported_free': sum(r['stable_unsupported_free'] for r in rows),
            'stable_structured_pass': sum(r['stable_structured_pass'] for r in rows),
            'requested_schema_invalid': sum(r['requested_schema_invalid'] for r in rows),
            'format_ungradable': sum(r['format_ungradable'] for r in rows), 'runner_errors': sum(bool(r['runner_error']) for r in rows),
            'unresolved': sum(not r['scored_agreement'] for r in rows), 'raw_semantic_disagreements': sum(r['raw_semantic_disagreement'] for r in rows),
            'numeric_field_denominator': sum(len(r['numeric_labels']) for r in rows),
            'numeric_code_pass': sum(c['status'] == 'pass' for r in rows for c in r['numeric_labels'].values()),
            'numeric_ungradable': sum(c['status'] == 'ungradable' for r in rows for c in r['numeric_labels'].values()),
            'per_judge_repeat': {str(rep): {'n': len(rows), 'valid': sum(str(rep) in r['judge_components'] for r in rows),
                'structured_pass': sum(r['judge_components'].get(str(rep), {}).get('structured_pass', False) for r in rows)} for rep in (0, 1)},
            'per_source_tier': {tier: {'n': sum(r['source_tier'] == tier for r in rows), 'stable_structured_pass': sum(r['stable_structured_pass'] for r in rows if r['source_tier'] == tier)} for tier in sorted({r['source_tier'] for r in rows})}}
    try: costs = budget.preflight(ROOT, ROOT/LEDGERS[0])
    except ValueError as error: costs = {'blocked': str(error)}
    summary = {'version': VERSION, 'arms': arms, 'answers': answers, 'judgments': len(judgments), 'global_budget': costs,
        'ledger_costs': {relative: api.cost_state(ROOT/relative) for relative in LEDGERS},
        'scope': 'Controlled source-tiered legacy regression; 35 cases/28 correlated families, not natural incident accuracy; answer_status is descriptive only'}
    api.save(out/'summary.json', summary); return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'prepare', 'run', 'summarize'])
    parser.add_argument('--base', type=Path, default=BASE); parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--campaign', type=Path, default=ROOT/'eval/v5/legacy-comparison-1')
    parser.add_argument('--judge-rep', type=int, choices=(0, 1))
    args = parser.parse_args()
    if args.action == 'freeze': result = freeze_plan(args.base)
    elif args.action == 'prepare': result = prepare(args.campaign, args.out, args.base/'scoring-plan.json')
    elif args.action == 'run': result = run(args.out, args.judge_rep)
    else: result = summarize(args.out)
    print(api.encode({k: v for k, v in result.items() if k not in ('answers', 'frozen_hashes')}))


if __name__ == '__main__': main()
