"""Prospective70-answer audit: repetition0, every case and both arms, no judge labels."""
import hashlib
import json
import random
import uuid
from pathlib import Path

import haiku_rejudge as api
from score_legacy_eval_v55 import _verified_mapping

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT/'eval/v5/legacy-scoring-v55'
    mapping = _verified_mapping(source)
    contracts_path = ROOT/'eval/v5/legacy-migration/field-contracts.json'
    contracts = api.read(contracts_path)['fields']
    selected = [row for row in mapping if type(row['rep']) is int and row['rep'] == 0]
    if len(mapping) != 210 or len(selected) != 70 or len({(r['case'], r['arm']) for r in selected}) != 70:
        raise ValueError('Full35-case/two-arm repetition0 sample required')
    grouped = {arm: sorted((r for r in selected if r['arm'] == arm), key=lambda r: r['case'])
               for arm in ('pi_plus', 'compact_plus')}
    if any(len(rows) != 35 for rows in grouped.values()) or {r['case'] for r in grouped['pi_plus']} != {r['case'] for r in grouped['compact_plus']}:
        raise ValueError('Every case must occur in both arms')
    rng = random.SystemRandom()
    for rows in grouped.values():
        rng.shuffle(rows)
    batches = [grouped['pi_plus'][:18] + grouped['compact_plus'][:17],
               grouped['pi_plus'][18:] + grouped['compact_plus'][17:]]
    out = ROOT/'eval/v5/legacy-answer-audit'
    if out.exists():
        raise ValueError('Audit packets are immutable; no resampling')
    out.mkdir()
    for index, batch in enumerate(batches, 1):
        packet = []; private = []
        for row in batch:
            payload = api.read(source/'payloads'/f"{row['id']}.json")
            if api.sha(api.encode(payload)) != row['payload_sha256']:
                raise ValueError('Prepared payload identity changed')
            ident = 'sample-' + uuid.uuid4().hex
            visible = {key: payload[key] for key in ('question', 'requested_answer_fields', 'answer', 'reference', 'observations')}
            visible['requested_schema_policy'] = payload['requested_schema_policy']
            visible['numeric_rubric'] = [{'key': field['key'], 'expected_value': field['original_gold']['value'],
                'absolute_tolerance': field['original_gold'].get('tolerance', 0),
                'unit': field['answer_binding']['unit'], 'scoring_kind': field['scoring_kind'],
                'question': field['requested_question']}
                for field in contracts if field['case_id'] == row['case']
                and type(field['original_gold']['value']) in (int, float)]
            packet.append({'id': ident, 'payload': visible})
            private.append({'id': ident, 'scorer_id': row['id'], 'case': row['case'], 'arm': row['arm'], 'rep': row['rep']})
        rng.shuffle(packet)
        api.save(out/f'batch-{index}.json', packet)
        api.save(out/f'batch-{index}-mapping-private.json', private)
    api.save(out/'manifest.json', {'sample_policy': 'Every case and both arms, model repetition0, selected before collection',
        'answers': 70, 'batches': 2, 'per_batch': 35,
        'allocation': 'SystemRandom; fixed70 selected answers, no public reversible arm-order seed',
        'arm_balance': [[18, 17], [17, 18]], 'withheld': ['arm identity', 'judge verdicts', 'computed numeric verdicts', 'other independent review'],
        'source_mapping_sha256': api.sha((source/'mapping.json').read_bytes()),
        'numeric_contracts_sha256': api.sha(contracts_path.read_bytes()),
        'analysis_plan_sha256': api.sha((ROOT/'docs/EVAL-V5-LEGACY-ANALYSIS-PLAN.md').read_bytes()),
        'packet_sha256': {f'batch-{i}.json': api.sha((out/f'batch-{i}.json').read_bytes()) for i in (1, 2)},
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    print('Prepared70 independently reviewable answers in', out)


if __name__ == '__main__':
    main()
