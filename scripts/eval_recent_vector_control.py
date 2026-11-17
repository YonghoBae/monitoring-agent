"""Score the frozen recent-source control with the same three retrieval methods."""
import argparse
import gzip
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time

import ir_measures
from ir_measures import nDCG, R, RR, Success
import numpy as np

import eval_real_vector_retrieval as ev

BASE = ev.BASE / "recent-control"
MEASURES = {nDCG@10: "nDCG@10", R@5: "Recall@5", R@10: "Recall@10", R@100: "Recall@100",
            RR@10: "MRR@10", Success@1: "Hit@1", Success@5: "Hit@5"}


class BodyText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "pre", "div", "li", "br", "h1", "h2", "h3", "blockquote"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "pre", "div", "li", "h1", "h2", "h3", "blockquote"}:
            self.parts.append("\n")


def body_text(body):
    parser = BodyText()
    parser.feed(body)
    return "".join(parser.parts).strip()


def aggregate(rows):
    groups, comparisons = [], []
    for group in ("all", "operations"):
        selected = [r for r in rows if group == "all" or r["operations"]]
        if not selected:
            continue
        for method in ev.METHODS:
            subset = [r for r in selected if r["method"] == method]
            groups.append({"group": group, "method": method, "queries": len(subset),
                           **{name: float(np.mean([r[name] for r in subset])) for name in ev.metrics([], {"gold"})}})
        by = {m: {r["query_id"]: r["nDCG@10"] for r in selected if r["method"] == m} for m in ev.METHODS}
        ids = sorted(by["dense"])
        for first, second in (("bm25", "dense"), ("rrf", "dense"), ("rrf", "bm25")):
            delta = np.array([by[first][q] - by[second][q] for q in ids])
            rng = np.random.default_rng(20261117)
            bootstrap = delta[rng.integers(0, len(delta), (2000, len(delta)))].mean(axis=1)
            comparisons.append({"group": group, "difference": first + " - " + second, "mean": float(delta.mean()),
                                "ci95": np.quantile(bootstrap, [.025, .975]).tolist()})
    return {"groups": groups, "paired_ndcg10_comparisons": comparisons}


def verify():
    dataset = json.loads((BASE / "dataset-manifest.json").read_text())
    manifest = json.loads((BASE / "run-manifest.json").read_text())
    assert manifest["dataset_manifest_sha256"] == ev.sha(BASE / "dataset-manifest.json")
    assert dataset["plan_sha256"] == ev.sha(BASE / "acquisition-plan.json")
    gold = {q["query_id"]: set(q["target_ids"]) for q in dataset["queries"]}
    rows = json.loads((BASE / "per-query-metrics.json").read_text())
    expected = {(r["query_id"], r["method"]): r for r in rows}
    assert len(expected) == len(rows) == len(gold) * 3
    runs = {m: [] for m in ev.METHODS}
    seen = set()
    pool = set(json.loads((BASE / "candidate-ids.json").read_text()))
    assert len(pool) == manifest["candidate_documents"]
    assert set.union(*gold.values()) <= pool
    with gzip.open(BASE / "rankings.jsonl.gz", "rt") as f:
        for line in f:
            row = json.loads(line)
            q, m, docs = row["query_id"], row["method"], row["document_ids"]
            assert (q, m) not in seen
            seen.add((q, m))
            assert len(docs) == len(set(docs)) == 100 and set(docs) <= pool and q not in docs
            for name, value in ev.metrics(docs, gold[q]).items():
                assert abs(value - expected[(q, m)][name]) < 1e-12
            runs[m].extend(ir_measures.ScoredDoc(q, d, 100 - i) for i, d in enumerate(docs))
    assert seen == set(expected)
    qrels = [ir_measures.Qrel(q, d, 1) for q, ds in gold.items() for d in ds]
    count = 0
    for m, ranking in runs.items():
        for result in ir_measures.iter_calc(list(MEASURES), qrels, ranking):
            assert abs(result.value - expected[(result.query_id, m)][MEASURES[result.measure]]) < 1e-12
            count += 1
    assert aggregate(rows) == json.loads((BASE / "summary.json").read_text())
    result = {"verified_at": ev.now(), "status": "pass", "ranking_rows": len(rows), "external_per_query_metrics_checked": count,
              "source_queries": len(gold), "gold_pairs": sum(map(len, gold.values())), "self_retrieval_excluded": True,
              "numeric_replay_requires_api": False}
    ev.save(BASE / "verification.json", result)
    print(json.dumps(result, indent=2))


def score(url):
    assert not (BASE / "summary.json").exists(), "Completed run exists; verify rather than overwrite"
    ev.check_protocol()
    dataset = json.loads((BASE / "dataset-manifest.json").read_text())
    assert dataset["plan_sha256"] == ev.sha(BASE / "acquisition-plan.json")
    for path, digest in dataset["source_file_sha256"].items():
        assert ev.sha(BASE / path) == digest
    base_docs, _, _, _ = ev.load_data()
    all_docs = {d["_id"]: d for d in base_docs}
    raw_targets = json.loads((BASE / "cache/target-questions.json").read_text())
    changed = [{"_id": qid, "title": unescape(q["title"]), "text": body_text(q["body"])} for qid, q in sorted(raw_targets.items())]
    all_docs.update({d["_id"]: d for d in changed})
    docs = sorted(all_docs.values(), key=lambda d: d["_id"])
    queries = sorted(json.loads((BASE / "cache/selected-questions.json").read_text()), key=lambda q: str(q["question_id"]))
    gold = {q["query_id"]: set(q["target_ids"]) for q in dataset["queries"]}
    assert {str(q["question_id"]) for q in queries} == set(gold)
    ids = [d["_id"] for d in docs]
    positions = {qid: i for i, qid in enumerate(ids)}
    ev.save(BASE / "candidate-ids.json", ids)
    subset = json.loads((ev.BASE / "query-subsets.json").read_text())
    operation_ids = {str(q["question_id"]) for q in queries if re.search(subset["admin_pattern"], unescape(q["title"]), re.I)}
    inputs = [d["title"] + "\n" + d["text"] for d in changed] + [unescape(q["title"]) for q in queries]
    # Commit effective selection, input hashes and method implementation before calling embeddings.
    frozen = {"frozen_at": ev.now(), "dataset_manifest_sha256": ev.sha(BASE / "dataset-manifest.json"),
              "main_protocol_sha256": ev.sha(ev.BASE / "protocol.json"), "main_runner_sha256": ev.sha(Path(ev.__file__)),
              "runner_sha256": ev.sha(Path(__file__)), "candidate_documents": len(docs), "changed_target_records": len(changed),
              "new_target_ids": sum(d["_id"] not in {x["_id"] for x in base_docs} for d in changed),
              "queries": len(queries), "gold_pairs": sum(map(len, gold.values())), "operations_query_ids": sorted(operation_ids),
              "inputs_sha256": ev.hashlib.sha256(json.dumps(inputs, ensure_ascii=False).encode()).hexdigest(),
              "runtime_context": 256, "embedding_truncate": True, "paid_api_calls": 0,
              "bootstrap": "paired 2000 query resamples, seed=20261117, 95% percentile; descriptive without multiplicity adjustment"}
    frozen_path = BASE / "run-plan.json"
    if frozen_path.exists():
        old = json.loads(frozen_path.read_text())
        assert all(old[k] == v for k, v in frozen.items() if k != "frozen_at")
        frozen = old
    else:
        ev.save(frozen_path, frozen)
    model = ev.api(url, "/api/tags")
    assert any(m["name"] == ev.MODEL and m["digest"] == ev.DIGEST for m in model["models"])
    extra_path = BASE / "cache/embeddings.npy"
    embed_log_path = BASE / "cache/embedding-batches.json"
    if extra_path.exists():
        extra = np.load(extra_path)
        batches = json.loads(embed_log_path.read_text())
    else:
        extra, batches = [], []
        for i in range(0, len(inputs), 32):
            start = time.monotonic()
            result = ev.api(url, "/api/embed", {"model": ev.MODEL, "input": inputs[i:i + 32], "truncate": True, "keep_alive": "10m"})
            extra.extend(result["embeddings"])
            batches.append({"offset": i, "count": len(result["embeddings"]), "seconds": time.monotonic() - start,
                            "prompt_eval_count": result.get("prompt_eval_count")})
        extra = np.asarray(extra, dtype=np.float32)
        assert extra.shape == (len(inputs), 384) and np.isfinite(extra).all()
        np.save(extra_path, extra)
        ev.save(embed_log_path, batches)
    assert extra.shape == (len(inputs), 384)
    state = json.loads((ev.BASE / "cache/embedding-state.json").read_text())
    assert ev.sha(ev.BASE / "cache/embeddings.npy") == state["embeddings_sha256"]
    vectors = np.concatenate([np.load(ev.BASE / "cache/embeddings.npy")[:len(base_docs)], extra[:len(changed)]])
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    source_pos = {d["_id"]: i for i, d in enumerate(base_docs)}
    source_pos.update({d["_id"]: len(base_docs) + i for i, d in enumerate(changed)})
    dv = np.ascontiguousarray(vectors[[source_pos[d["_id"]] for d in docs]])
    qv = extra[len(changed):] / np.linalg.norm(extra[len(changed):], axis=1, keepdims=True)
    started = time.monotonic()
    lexical = ev.BM25([d["title"] + "\n" + d["text"] for d in docs])
    rows = []
    with gzip.open(BASE / "rankings.jsonl.gz", "wt") as f:
        for i, q in enumerate(queries):
            qid = str(q["question_id"])
            ds = dv @ qv[i]
            bs = lexical.scores(unescape(q["title"]))
            if qid in positions:
                ds[positions[qid]] = -np.inf
                bs[positions[qid]] = -np.inf
            dense, bm = ev.ranked(ds), ev.ranked(bs)
            for method, order in {"dense": dense, "bm25": bm, "rrf": ev.fuse(dense, bm, bs, len(ids))}.items():
                docids = [ids[j] for j in order]
                rows.append({"query_id": qid, "method": method, "operations": qid in operation_ids, **ev.metrics(docids, gold[qid])})
                f.write(json.dumps({"query_id": qid, "method": method, "document_ids": docids}) + "\n")
    ev.save(BASE / "per-query-metrics.json", rows)
    ev.save(BASE / "summary.json", aggregate(rows))
    ev.save(BASE / "run-manifest.json", {**frozen, "finished_at": ev.now(), "run_plan_sha256": ev.sha(frozen_path),
                                        "base_embeddings_sha256": state["embeddings_sha256"], "additional_embeddings_sha256": ev.sha(extra_path),
                                        "embedding_inputs": len(inputs), "embedding_http_requests": len(batches), "embedding_seconds": sum(b["seconds"] for b in batches),
                                        "index_and_retrieval_seconds": time.monotonic() - started})
    verify()
    print(json.dumps(aggregate(rows), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["score", "verify"])
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    args = parser.parse_args()
    if args.command == "verify":
        verify()
    else:
        score(args.ollama_url)
