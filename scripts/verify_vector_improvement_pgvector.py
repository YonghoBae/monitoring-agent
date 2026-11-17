"""Compare frozen dense rankings with exact pgvector cosine on an isolated DB.

Requires Docker and local vector caches. Uses no production database or network.
The temporary container has no published ports and is removed in finally.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

import numpy as np

BASE = Path(__file__).resolve().parents[1] / 'eval/vector-v3-improvement'
IMAGE = 'sha256:b0108689bf51bd54d3129130967d4adf7ba58b395a9ff6653aa598b5fe7d7ba3'


def command(*args, **kwargs):
    return subprocess.run(['rtk', 'proxy', *args], check=True, text=True, capture_output=True, **kwargs)


def vector(v):
    return '[' + ','.join(format(float(x), '.9g') for x in v) + ']'


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def main(image=IMAGE):
    lock = json.loads((BASE / 'final-selection-lock.json').read_text())
    dataset = json.loads((BASE / 'final/numeric-dataset.json').read_text())
    ids, queries = dataset['candidate_ids'], dataset['queries']
    vectors_path = BASE / 'cache/full' / (lock['encoder'] + '-head.npy')
    vectors = np.load(vectors_path, mmap_mode='r')
    assert vectors.shape[0] == len(ids) + len(queries)
    dimensions = vectors.shape[1]
    tail = np.load(BASE / 'cache/full' / (lock['encoder'] + '-tail.npy'), mmap_mode='r') if lock['tail'] else None
    with gzip.open(BASE / 'final/selected_encoder-rankings.jsonl.gz', 'rt') as f:
        expected = {r['query_id']: r['document_ids'][:10] for r in map(json.loads, f)}
    holdout = [q for q in queries if q['group'] not in ['recent_en', 'historical_en', 'historical_ko']]
    chosen = sorted([q for q in holdout if q['group'].endswith('_en')], key=lambda q: hashlib.sha256(('v3-pg:' + q['id']).encode()).hexdigest())[:16]
    chosen += [q for q in holdout if q['group'].endswith('_ko')]
    positions = {q['id']: len(ids) + i for i, q in enumerate(queries)}
    name = 'vector-v3-check-' + uuid.uuid4().hex[:10]
    created = False
    started = time.monotonic()
    try:
        command('docker', 'run', '-d', '--name', name, '--network', 'none', '--memory', '1536m', '--cpus', '1',
                '--tmpfs', '/var/lib/postgresql/data:rw,size=1073741824', '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', image)
        created = True
        for attempt in range(60):
            try:
                # The image's initialization server only listens on a Unix socket.
                # TCP readiness prevents racing that temporary server's shutdown.
                command('docker', 'exec', name, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres')
                break
            except subprocess.CalledProcessError:
                if attempt == 59:
                    raise
                time.sleep(1)
        psql = ['rtk', 'proxy', 'docker', 'exec', '-i', name, 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres']
        process = subprocess.Popen(psql, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            process.stdin.write(f'CREATE EXTENSION vector; CREATE TABLE vectors (id text, embedding vector({dimensions}));\nCOPY vectors FROM STDIN;\n')
            for i, doc_id in enumerate(ids):
                assert not any(x in doc_id for x in '\t\n\\')
                process.stdin.write(doc_id + '\t' + vector(vectors[i]) + '\n')
                if tail is not None:
                    process.stdin.write(doc_id + '\t' + vector(tail[i]) + '\n')
            process.stdin.write('\\.\n')
            process.stdin.close()
            process.stdin = None
            output, error = process.communicate(timeout=180)
            if process.returncode:
                raise RuntimeError(error)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        version = command('docker', 'exec', name, 'psql', '-XAt', '-U', 'postgres', '-c', "SELECT version(); SELECT extversion FROM pg_extension WHERE extname='vector';").stdout.strip()
        checks = []
        for q in chosen:
            distance = 'embedding <=> ' + literal(vector(vectors[positions[q['id']]])) + '::vector'
            sql = f'SELECT id FROM vectors WHERE id <> {literal(q["source_id"])} GROUP BY id ORDER BY min({distance}), id COLLATE "C" LIMIT 10;'
            before = time.monotonic()
            result = command('docker', 'exec', name, 'psql', '-XAt', '-U', 'postgres', '-c', sql).stdout.splitlines()
            checks.append({'query_id': q['id'], 'expected_top10': expected[q['id']], 'pgvector_top10': result,
                           'exact_order_match': result == expected[q['id']], 'sql_wall_seconds': time.monotonic() - before})
        result = {'status': 'pass' if all(r['exact_order_match'] for r in checks) else 'mismatch',
                  'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'image': image, 'version': version,
                  'candidate_documents': len(ids), 'vector_dimensions': dimensions, 'queries': len(checks),
                  'matching_top10_orders': sum(r['exact_order_match'] for r in checks), 'checks': checks,
                  'elapsed_seconds': time.monotonic() - started, 'production_database_accessed': False,
                  'scope': 'Exact cosine scan only; not HNSW/IVFFlat recall, Spring AI integration, or production latency.'}
        (BASE / 'final/pgvector-verification.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({k: v for k, v in result.items() if k != 'checks'}, indent=2))
        assert result['status'] == 'pass', 'Inspect numeric ties or implementation differences; do not erase mismatches.'
    finally:
        if created:
            command('docker', 'rm', '-f', name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', default=IMAGE)
    main(parser.parse_args().image)
