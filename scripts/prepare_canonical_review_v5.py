"""Arm/judge-blind packets of completed canonical answers, with corrected gold."""
import argparse
import hashlib
import json
import random
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=int, required=True)
    parser.add_argument('--count', type=int, required=True)
    parser.add_argument('--batch', required=True)
    args = parser.parse_args()
    if args.start < 0 or args.count < 1 or Path(args.batch).name != args.batch:
        raise ValueError('Invalid batch specification')
    dataset_path = ROOT/'eval/v5/canonical-core/dataset.json'
    dataset_bytes = dataset_path.read_bytes()
    scenes = {s['id']: s for s in json.loads(dataset_bytes)['scenarios']}
    gold_path = ROOT/'eval/v5/gold-v52.json'
    gold = json.loads(gold_path.read_text())
    candidates = sorted((ROOT/'build/eval').glob('comparison-*'), key=lambda p: int(p.name.split('-')[-1]), reverse=True)
    source = next(p for p in candidates if (p/'dataset.json').exists() and (p/'dataset.json').read_bytes() == dataset_bytes)
    rows = [json.loads(line) for line in (source/'results.jsonl').read_text().splitlines()]
    if len(rows) < args.start + args.count:
        raise ValueError('Requested rows not yet completed')
    out = ROOT/'eval/v5/canonical-core/independent-review'
    out.mkdir(exist_ok=True)
    target = out/(args.batch + '.json')
    if target.exists():
        raise ValueError('Review packets are immutable')
    packet = []; mapping = []
    for row in rows[args.start:args.start + args.count]:
        ident = 'sample-' + uuid.uuid4().hex
        scene = scenes[row['id']]
        packet.append({'id': ident, 'payload': {'question': scene['question'],
            'requested_answer_fields': scene['answer_fields'], 'answer': row['answer'],
            'reference': gold[row['id']]['reference'], 'observations': row['trace']['observations']}})
        mapping.append({'id': ident, 'case': row['id'], 'arm': row['arm'], 'rep': row['rep'],
            'source_row_sha256': hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()})
    random.SystemRandom().shuffle(packet)
    target.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + '\n')
    (out/(args.batch + '-mapping-private.json')).write_text(json.dumps(mapping, indent=2) + '\n')
    (out/(args.batch + '-manifest.json')).write_text(json.dumps({'count': args.count,
        'dataset_sha256': hashlib.sha256(dataset_bytes).hexdigest(),
        'gold_sha256': hashlib.sha256(gold_path.read_bytes()).hexdigest(),
        'packet_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'source': str(source), 'start': args.start,
        'policy': 'No arm labels, judge outcomes, or raw backend evidence in reviewer packet'}, indent=2) + '\n')
    print('Prepared', args.count, 'blind answers:', target)


if __name__ == '__main__':
    main()
