"""Replay numeric ranks against published qrels, cross-check every metric with ir_measures."""
from collections import defaultdict
import gzip
import json
from pathlib import Path

import ir_measures
from ir_measures import nDCG, R, RR, Success
import numpy as np

import eval_real_vector_retrieval as ev


def main():
    p = ev.check_protocol()
    docs, queries, gold, ko = ev.load_data()
    run = ev.BASE / "runs/real-v1"
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["protocol_sha256"] == ev.sha(ev.BASE / "protocol.json")
    if manifest.get("protocol_amendment_sha256"):
        assert manifest["protocol_amendment_sha256"] == ev.sha(ev.BASE / "protocol-amendment.json")
    if manifest.get("runtime_observation_sha256"):
        assert manifest["runtime_observation_sha256"] == ev.sha(ev.BASE / "runtime-observation.json")
    if (run / "embedding-state.json").exists():
        assert manifest["embedding_state_sha256"] == ev.sha(run / "embedding-state.json")
    rows = json.loads((run / "per-query-metrics.json").read_text())
    lookup = {(r["pool_size"], r["language"], r["query_id"], r["method"]): r for r in rows}
    assert len(lookup) == len(rows)
    seen = set()
    external_runs = defaultdict(list)
    qrels = [ir_measures.Qrel(q, d, 1) for q, ds in gold.items() for d in ds]
    measures = {nDCG@10: "nDCG@10", R@5: "Recall@5", R@10: "Recall@10", R@100: "Recall@100",
                RR@10: "MRR@10", Success@1: "Hit@1", Success@5: "Hit@5"}
    for size in p["pool_sizes"]:
        ids = {docs[i]["_id"] for i in ev.pool_indices(docs, gold, size)}
        assert len(ids) == size
        with gzip.open(run / f"rankings-{size}.jsonl.gz", "rt") as f:
            for line in f:
                record = json.loads(line)
                q, language, method = record["query_id"], record["language"], record["method"]
                ranked = record["document_ids"]
                assert len(ranked) == len(set(ranked)) == 100 and set(ranked) <= ids
                key = (size, language, q, method)
                assert key not in seen
                seen.add(key)
                expected = lookup[key]
                for name, value in ev.metrics(ranked, gold[q]).items():
                    assert abs(value - expected[name]) < 1e-12, (key, name)
                external_runs[(size, language, method)].extend(ir_measures.ScoredDoc(q, d, 100 - i) for i, d in enumerate(ranked))
    assert seen == set(lookup)
    expected_count = (len(queries) * len(p["pool_sizes"]) + len(ko)) * len(ev.METHODS)
    assert len(rows) == expected_count
    checked = 0
    for (size, language, method), ranking in external_runs.items():
        selected_ids = {r.query_id for r in ranking}
        rels = [r for r in qrels if r.query_id in selected_ids]
        for result in ir_measures.iter_calc(list(measures), rels, ranking):
            expected = lookup[(size, language, result.query_id, method)][measures[result.measure]]
            assert abs(expected - result.value) < 1e-12, (result, expected)
            checked += 1
    summary = json.loads((run / "summary.json").read_text())
    assert summary == ev.summarize(rows)
    lengths = np.array([len(d["title"] + "\n" + d["text"]) for d in docs])
    stats = {"documents": len(docs), "queries": len(queries), "qrels": sum(map(len, gold.values())),
             "queries_with_multiple_positives": sum(len(g) > 1 for g in gold.values()),
             "text_char_quantiles": dict(zip(["p50", "p90", "p95", "p99", "max"], np.quantile(lengths, [.5, .9, .95, .99, 1]).tolist())),
             "documents_with_newlines_in_body": sum("\n" in d["text"] for d in docs),
             "documents_with_dollar_space": sum("$ " in d["text"] for d in docs),
             "documents_with_possible_duplicate_phrase": sum("possible duplicate" in d["text"].lower() for d in docs)}
    result = {"verified_at": ev.now(), "status": "pass", "ranking_rows": len(rows), "independently_checked_per_query_metrics": checked,
              "independent_metric_implementation": "ir_measures 0.4.3 / pytrec_eval-terrier 0.5.11",
              "summary_and_paired_bootstrap_replayed": True, "dataset_statistics": stats}
    ev.save(run / "verification.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
