"""Verify fixed query sample in isolated, networkless PostgreSQL/pgvector.

Uses an explicitly supplied container; never connects to the application's database.
Embeddings only (no source bodies) are loaded. Remove the temporary container afterward.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

import numpy as np
import eval_real_vector_retrieval as ev


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"monitoring-vector-real-eval-[a-z0-9-]+", args.container):
        raise SystemExit("Only explicitly isolated vector-real-eval containers are permitted")
    inspect = subprocess.run(["rtk", "proxy", "docker", "inspect", args.container], capture_output=True, text=True, check=True)
    container = json.loads(inspect.stdout)[0]
    assert container["HostConfig"]["NetworkMode"] == "none"
    assert not container["HostConfig"].get("PortBindings")
    assert not any(m["Type"] == "bind" for m in container["Mounts"])
    ev.check_protocol()
    docs, queries, gold, ko = ev.load_data()
    state = json.loads((ev.BASE / "cache/embedding-state.json").read_text())
    assert state["completed"] == len(docs) + len(queries) + len(ko)
    assert ev.sha(ev.BASE / "cache/embeddings.npy") == state["embeddings_sha256"]
    vectors = np.load(ev.BASE / "cache/embeddings.npy")
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    def vector(a):
        return "[" + ",".join(format(float(x), ".9g") for x in a) + "]"
    psql = ["rtk", "proxy", "docker", "exec", "-i", args.container, "psql", "-X", "-U", "postgres", "-d", "vector_eval", "-v", "ON_ERROR_STOP=1", "-qAt"]
    sql_path = ev.BASE / "cache/pgvector-load.sql"
    with sql_path.open("w") as f:
        f.write("CREATE EXTENSION IF NOT EXISTS vector;\nCREATE TABLE real_vectors(id text PRIMARY KEY, embedding vector(384));\nCOPY real_vectors FROM STDIN;\n")
        for i, d in enumerate(docs):
            assert d["_id"].isdigit()
            f.write(d["_id"] + "\t" + vector(vectors[i]) + "\n")
        f.write("\\.\nANALYZE real_vectors;\n")
    started = time.monotonic()
    with sql_path.open() as f:
        res = subprocess.run(psql, stdin=f, capture_output=True, text=True, check=True)
    chosen = sorted(queries, key=lambda q: hashlib.sha256(("pg-check-v1:" + q["_id"]).encode()).hexdigest())[:32]
    positions = {q["_id"]: i for i, q in enumerate(queries)}
    tests = [("en", q["_id"], len(docs) + positions[q["_id"]]) for q in chosen]
    tests += [("ko", q["_id"], len(docs) + len(queries) + i) for i, q in enumerate(ko)]
    expected = {}
    with gzip.open(ev.BASE / "runs/real-v1" / f"rankings-{len(docs)}.jsonl.gz", "rt") as f:
        for line in f:
            row = json.loads(line)
            if row["method"] == "dense":
                expected[(row["language"], row["query_id"])] = row["document_ids"][:10]
    outputs = []
    for language, qid, position in tests:
        literal = "'" + vector(vectors[position]) + "'::vector"
        sql = "SELECT json_agg(row_to_json(t)) FROM (SELECT id, embedding <=> " + literal + " AS distance FROM real_vectors ORDER BY distance, id COLLATE \"C\" LIMIT 10) t;\n"
        response = subprocess.run(psql, input=sql, capture_output=True, text=True, check=True)
        ranked = json.loads(response.stdout.strip())
        actual = [r["id"] for r in ranked]
        match = actual == expected[(language, qid)]
        outputs.append({"language": language, "query_id": qid, "exact_order_match": match, "pgvector_top10": ranked})
    response = subprocess.run(psql, input="SELECT json_build_object('postgres',version(),'pgvector',(SELECT extversion FROM pg_extension WHERE extname='vector'),'document_count',(SELECT count(*) FROM real_vectors));\n", capture_output=True, text=True, check=True)
    result = {"verified_at": ev.now(), "embedding_sha256": state["embeddings_sha256"], "runtime": json.loads(response.stdout.strip()),
              "sample_selection": "protocol: SHA256(pg-check-v1:query_id) first 32 English, all 32 Korean", "checked_queries": len(tests),
              "exact_top10_order_matches": sum(r["exact_order_match"] for r in outputs), "seconds": time.monotonic() - started,
              "rows": outputs, "scope": "exact cosine SQL only; Spring AI orchestration and HNSW are not exercised"}
    ev.save(ev.BASE / "runs/real-v1/pgvector-verification.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    assert all(r["exact_order_match"] for r in outputs), "Actual PostgreSQL ordering mismatch; inspect evidence, do not publish as pass"


if __name__ == "__main__":
    main()
