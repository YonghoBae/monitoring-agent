"""Frozen CQADupStack Unix retrieval experiment; no generated documents or LLM judge.

Run freeze BEFORE embed/score. Raw upstream text and vector caches stay local.
Only numeric rankings, IDs, parameters and aggregates are intended for publication.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import datetime as dt
import hashlib
import gzip
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.request

os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "eval/vector-v2-real"
MODEL = "all-minilm:latest"
DIGEST = "1b226e2802dbb772b5fc32a58f103ca1804ef7501331012de126ab22f67475ef"
TOKEN_RE = r"[^\W_]+(?:_[^\W_]+)*"
METHODS = ("dense", "bm25", "rrf")


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def tokens(text):
    return re.findall(TOKEN_RE, text.lower())


def load_data():
    def jl(name):
        return [json.loads(line) for line in (BASE / "upstream" / name).read_text().splitlines()]
    docs = sorted(jl("corpus.jsonl"), key=lambda x: str(x["_id"]))
    queries = sorted(jl("queries.jsonl"), key=lambda x: str(x["_id"]))
    gold = defaultdict(set)
    with (BASE / "upstream/qrels/test.tsv").open() as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if float(row["score"]) > 0:
                gold[row["query-id"]].add(row["corpus-id"])
    ids = {str(d["_id"]) for d in docs}
    qids = {str(q["_id"]) for q in queries}
    assert len(ids) == len(docs) and len(qids) == len(queries)
    assert not ids & qids, "No self retrieval is permitted"
    assert qids == set(gold) and set.union(*gold.values()) <= ids
    ko = json.loads((BASE / "korean-queries.json").read_text())["queries"]
    assert len({q["_id"] for q in ko}) == len(ko)
    assert {q["_id"] for q in ko} <= qids
    return docs, queries, dict(gold), ko


def pool_indices(docs, gold, size):
    required = set.union(*gold.values())
    assert size >= len(required)
    extras = sorted((d["_id"] for d in docs if d["_id"] not in required),
                    key=lambda x: hashlib.sha256(("vector-real-pool-v1:" + x).encode()).hexdigest())
    selected = required | set(extras[:size - len(required)])
    return np.array([i for i, d in enumerate(docs) if d["_id"] in selected], dtype=np.int32)


def freeze():
    path = BASE / "protocol.json"
    if path.exists():
        raise SystemExit("Protocol already frozen; create a new experiment rather than overwrite it")
    docs, queries, gold, ko = load_data()
    sources = json.loads((BASE / "source-manifest.json").read_text())
    for source in sources["files"]:
        assert sha(BASE / "upstream" / source["path"]) == source["sha256"]
    protocol = {
        "version": 1, "frozen_at": now(), "corpus_count": len(docs), "query_count": len(queries),
        "qrel_count": sum(map(len, gold.values())), "korean_query_count": len(ko),
        "dataset_revision": sources["revision"],
        "input_sha256": {str(p.relative_to(BASE)): sha(p) for p in [
            BASE / "source-manifest.json", BASE / "query-subsets.json", BASE / "korean-queries.json",
            BASE / "upstream/corpus.jsonl", BASE / "upstream/queries.jsonl", BASE / "upstream/qrels/test.tsv"]},
        "methods": list(METHODS), "model": MODEL, "model_digest": DIGEST, "dimensions": 384,
        "document_input": "title + newline + text, unchanged upstream fields",
        "query_input": "unchanged upstream title; separately labeled Korean translations",
        "embedding_truncate": True, "embedding_context": 256, "model_max_context_metadata": 512, "batch_size": 32,
        "dense": "exact normalized float32 dot product; no ANN",
        "bm25": {"k1": 1.2, "b": 0.75, "idf": "log(1+(N-df+0.5)/(df+0.5))",
                 "token_pattern": TOKEN_RE, "lowercase": True, "stemming": False,
                 "stopword_removal": False, "duplicate_query_terms": "count once", "input": "full text"},
        "rrf": {"k": 60, "depth": 100, "weights": [1, 1], "exclude_nonpositive_bm25": True},
        "tie_break": "document ID ascending as string",
        "pool_sizes": [5000, 20000, len(docs)],
        "pool_selection": "all 1693 judged-relevant documents plus SHA256(vector-real-pool-v1:docid) ordered distractors; nested; no retrieval score selection",
        "primary": "full-corpus English nDCG@10", "metrics": ["nDCG@10", "Recall@5", "Recall@10", "Recall@100", "Hit@1", "Hit@5", "MRR@10"],
        "groups": ["all English", "operations title regex subset", "32 Korean translations (full corpus only)"],
        "confidence": "paired query bootstrap 2000 resamples, seed=20261117, 95% percentile CI on nDCG@10 difference; query independence assumption",
        "pgvector_check": "first 32 English queries by SHA256(pg-check-v1:query_id), plus all 32 Korean translations, full corpus top10",
        "paid_api_calls": 0,
        "limits": ["duplicate-question relevance, not repair correctness", "English StackExchange snapshot from 2014", "upstream text preprocessing retained", "incomplete community judgments", "no no-answer calibration", "BM25 sees full text; dense context truncates at 256", "Korean translations are an authored cross-language diagnostic, not native operations queries", "no model training or parameter tuning on test scores"],
    }
    save(path, protocol)
    print(json.dumps({"frozen_at": protocol["frozen_at"], "corpus": len(docs), "queries": len(queries), "qrels": protocol["qrel_count"], "protocol_sha256": sha(path)}), flush=True)


def check_protocol():
    p = json.loads((BASE / "protocol.json").read_text())
    for name, expected in p["input_sha256"].items():
        assert sha(BASE / name) == expected, f"Changed frozen input: {name}"
    assert p["bm25"]["token_pattern"] == TOKEN_RE and p["methods"] == list(METHODS)
    return p


def api(base, path, body=None):
    req = urllib.request.Request(base.rstrip("/") + path,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as res:
        return json.load(res)


def embed(base):
    p = check_protocol()
    info = api(base, "/api/tags")
    assert any(m["name"] == MODEL and m["digest"] == DIGEST for m in info["models"]), "Wrong embedding model"
    docs, queries, gold, ko = load_data()
    inputs = [d["title"] + "\n" + d["text"] for d in docs] + [q["text"] for q in queries] + [q["text"] for q in ko]
    cache = BASE / "cache"
    cache.mkdir(exist_ok=True)
    state_path = cache / "embedding-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "protocol_sha256": sha(BASE / "protocol.json"), "completed": 0, "total": len(inputs),
        "model": MODEL, "model_digest": DIGEST, "started_at": now(),
        "ollama_version": api(base, "/api/version"), "batches": [], "paid_api_calls": 0}
    assert state["protocol_sha256"] == sha(BASE / "protocol.json") and state["total"] == len(inputs)
    mode = "r+" if (cache / "embeddings.npy").exists() else "w+"
    assert mode != "w+" or state["completed"] == 0
    vectors = np.lib.format.open_memmap(cache / "embeddings.npy", mode=mode, dtype=np.float32, shape=(len(inputs), 384))
    started = time.monotonic()
    initial = state["completed"]
    for i in range(initial, len(inputs), p["batch_size"]):
        before = time.monotonic()
        result = api(base, "/api/embed", {"model": MODEL, "input": inputs[i:i + p["batch_size"]], "truncate": True, "keep_alive": "10m"})
        arr = np.asarray(result["embeddings"], dtype=np.float32)
        assert arr.shape == (min(p["batch_size"], len(inputs) - i), 384)
        assert np.isfinite(arr).all() and (np.linalg.norm(arr, axis=1) > 0).all()
        vectors[i:i + len(arr)] = arr
        vectors.flush()
        state["completed"] = i + len(arr)
        state["batches"].append({"offset": i, "count": len(arr), "seconds": time.monotonic() - before,
                                 "prompt_eval_count": result.get("prompt_eval_count"), "total_duration_ns": result.get("total_duration")})
        save(state_path, state)
        if i == initial or state["completed"] % 1024 == 0 or state["completed"] == len(inputs):
            done = state["completed"] - initial
            elapsed = time.monotonic() - started
            print(json.dumps({"embedded": state["completed"], "total": len(inputs), "elapsed_seconds": round(elapsed, 1), "estimated_remaining_seconds": round((len(inputs) - state["completed"]) * elapsed / done, 1)}), flush=True)
    state["finished_at"] = now()
    state["embeddings_sha256"] = sha(cache / "embeddings.npy")
    save(state_path, state)


class BM25:
    def __init__(self, texts):
        counts = [Counter(tokens(t)) for t in texts]
        self.n = len(texts)
        lengths = np.array([sum(c.values()) for c in counts], dtype=np.float64)
        avg = lengths.mean() or 1
        norm = 1.2 * (1 - .75 + .75 * lengths / avg)
        postings = defaultdict(list)
        for i, counter in enumerate(counts):
            for term, freq in counter.items():
                postings[term].append((i, freq))
        self.postings = {}
        for term, pairs in postings.items():
            a = np.array(pairs)
            idx, freq = a[:, 0], a[:, 1]
            idf = math.log(1 + (self.n - len(pairs) + .5) / (len(pairs) + .5))
            self.postings[term] = (idx, idf * freq * 2.2 / (freq + norm[idx]))

    def scores(self, query):
        out = np.zeros(self.n, dtype=np.float64)
        for term in sorted(set(tokens(query))):
            if term in self.postings:
                idx, value = self.postings[term]
                out[idx] += value
        return out


def ranked(scores, limit=100):
    # Inputs are already lexicographically sorted by document ID.
    return np.argsort(-scores, kind="stable")[:limit]


def fuse(dense, lexical, lexical_scores, n):
    scores = np.zeros(n, dtype=np.float64)
    for rank, idx in enumerate(dense[:100], 1):
        scores[idx] += 1 / (60 + rank)
    for rank, idx in enumerate(lexical[:100], 1):
        if lexical_scores[idx] > 0:
            scores[idx] += 1 / (60 + rank)
    # Union can contain <100 documents only in tiny unit tests.
    return ranked(scores, min(100, int(np.count_nonzero(scores))))


def metrics(order, relevant):
    hits = [int(d in relevant) for d in order]
    dcg = sum(v / math.log2(i + 2) for i, v in enumerate(hits[:10]))
    idcg = sum(1 / math.log2(i + 2) for i in range(min(10, len(relevant))))
    return {"nDCG@10": dcg / idcg, "Recall@5": sum(hits[:5]) / len(relevant),
            "Recall@10": sum(hits[:10]) / len(relevant), "Recall@100": sum(hits[:100]) / len(relevant),
            "Hit@1": float(any(hits[:1])), "Hit@5": float(any(hits[:5])),
            "MRR@10": next((1 / (i + 1) for i, hit in enumerate(hits[:10]) if hit), 0.0)}


def score():
    p = check_protocol()
    run = BASE / "runs/real-v1"
    if (run / "summary.json").exists():
        raise SystemExit("Completed scores already exist; use verifier, do not overwrite")
    run.mkdir(parents=True, exist_ok=True)
    docs, queries, gold, ko = load_data()
    state = json.loads((BASE / "cache/embedding-state.json").read_text())
    assert state["completed"] == len(docs) + len(queries) + len(ko)
    assert state["protocol_sha256"] == sha(BASE / "protocol.json")
    assert sha(BASE / "cache/embeddings.npy") == state["embeddings_sha256"]
    raw = np.load(BASE / "cache/embeddings.npy")
    norm = np.linalg.norm(raw, axis=1, keepdims=True)
    assert np.isfinite(raw).all() and (norm > 0).all()
    vectors = raw / norm
    qvec = vectors[len(docs):]
    admin = set(json.loads((BASE / "query-subsets.json").read_text())["admin_query_ids"])
    rows = []
    timings = []
    for size in p["pool_sizes"]:
        started = time.monotonic()
        idx = pool_indices(docs, gold, size)
        ids = [docs[i]["_id"] for i in idx]
        bm25 = BM25([docs[i]["title"] + "\n" + docs[i]["text"] for i in idx])
        build_seconds = time.monotonic() - started
        dv = np.ascontiguousarray(vectors[idx])
        qs = queries + ko if size == len(docs) else queries
        ranks_path = run / f"rankings-{size}.jsonl.gz"
        with gzip.open(ranks_path, "wt") as out:
            for qi, q in enumerate(qs):
                ds = dv @ qvec[qi]
                bs = bm25.scores(q["text"])
                dense, lexical = ranked(ds), ranked(bs)
                rankings = {"dense": dense, "bm25": lexical, "rrf": fuse(dense, lexical, bs, size)}
                language = "ko" if qi >= len(queries) else "en"
                for method, order in rankings.items():
                    docids = [ids[j] for j in order]
                    row = {"pool_size": size, "language": language, "query_id": q["_id"],
                           "method": method, "operations": q["_id"] in admin, **metrics(docids, gold[q["_id"]])}
                    rows.append(row)
                    out.write(json.dumps({"query_id": q["_id"], "language": language, "method": method, "document_ids": docids}) + "\n")
        timings.append({"pool_size": size, "index_build_seconds": build_seconds, "total_seconds": time.monotonic() - started})
        print(json.dumps({"scored_pool": size, "queries": len(qs), "elapsed_seconds": timings[-1]["total_seconds"]}), flush=True)
    save(run / "per-query-metrics.json", rows)
    summary = summarize(rows)
    save(run / "summary.json", summary)
    save(run / "manifest.json", {"created_at": now(), "protocol_sha256": sha(BASE / "protocol.json"),
                                  "protocol_amendment_sha256": sha(BASE / "protocol-amendment.json") if (BASE / "protocol-amendment.json").exists() else None,
                                  "runtime_observation_sha256": sha(BASE / "runtime-observation.json") if (BASE / "runtime-observation.json").exists() else None,
                                  "runner_sha256": sha(Path(__file__)), "embedding_state_sha256": sha(BASE / "cache/embedding-state.json"),
                                  "embedding_sha256": state["embeddings_sha256"], "timings": timings, "numpy_version": np.__version__,
                                  "paid_api_calls": 0, "embedding_inputs": state["total"], "embedding_http_requests": len(state["batches"]),
                                  "embedding_elapsed_seconds": sum(b["seconds"] for b in state["batches"]), "ollama_version": state["ollama_version"]})
    print(json.dumps(summary, indent=2), flush=True)


def summarize(rows):
    groups = []
    comparisons = []
    translated_ids = {r["query_id"] for r in rows if r["language"] == "ko"}
    largest_pool = max(r["pool_size"] for r in rows)
    for size in sorted({r["pool_size"] for r in rows}):
        for language, group in (("en", "all"), ("en", "operations"), ("en", "translation_sources"), ("ko", "translations")):
            if group == "translation_sources" and size != largest_pool:
                continue
            selected = [r for r in rows if r["pool_size"] == size and r["language"] == language
                        and (group != "operations" or r["operations"])
                        and (group != "translation_sources" or r["query_id"] in translated_ids)]
            if not selected:
                continue
            for method in METHODS:
                subset = [r for r in selected if r["method"] == method]
                groups.append({"pool_size": size, "language": language, "group": group, "method": method, "queries": len(subset),
                               **{key: float(np.mean([r[key] for r in subset])) for key in metrics([], {"gold"})}})
            by = {m: {r["query_id"]: r["nDCG@10"] for r in selected if r["method"] == m} for m in METHODS}
            qids = sorted(by["dense"])
            for first, second in (("bm25", "dense"), ("rrf", "dense"), ("rrf", "bm25")):
                delta = np.array([by[first][q] - by[second][q] for q in qids])
                rng = np.random.default_rng(20261117)
                bootstrap = delta[rng.integers(0, len(delta), size=(2000, len(delta)))].mean(axis=1)
                comparisons.append({"pool_size": size, "language": language, "group": group, "difference": first + " - " + second,
                                    "mean": float(delta.mean()), "ci95": np.quantile(bootstrap, [.025, .975]).tolist()})
    return {"groups": groups, "paired_ndcg10_comparisons": comparisons}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["freeze", "embed", "score"])
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    args = parser.parse_args()
    if args.command == "freeze":
        freeze()
    elif args.command == "embed":
        embed(args.ollama_url)
    else:
        score()


if __name__ == "__main__":
    main()
