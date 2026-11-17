"""Collect a prospective follow-up control after finding historical training overlap.

Community duplicate targets remain the gold labels; no LLM-generated documents,
labels or questions. Frozen selection uses dates/API order, never retrieval score.
Full API responses remain local. Only IDs, dates, links and digests are published.
"""
import datetime as dt
import gzip
import html
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request

import eval_real_vector_retrieval as ev

BASE = ev.BASE / "recent-control"


def api(endpoint, params, cache_name):
    path = BASE / "cache" / cache_name
    if path.exists():
        return json.loads(path.read_text())
    url = "https://api.stackexchange.com/2.3/" + endpoint + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    data = json.loads(raw)
    assert "error_id" not in data, str(data.get("error_name"))
    if data.get("backoff", 0) > 60:
        raise RuntimeError("API requested a longer backoff; retry later")
    if data.get("backoff"):
        time.sleep(data["backoff"])
    ev.save(path, data)
    return data


def main():
    plan_path = BASE / "acquisition-plan.json"
    if not plan_path.exists():
        ev.save(plan_path, {"frozen_at": ev.now(), "reason": "Adaptive follow-up after historical benchmark overlap audit; before any recent-control score",
                            "site": "unix", "fromdate": 1640995200, "todate": int(time.time()),
                            "pages": 5, "page_size": 100, "sort": "creation", "order": "desc", "closed": True,
                            "max_queries": 100, "selection": "First 100 duplicate questions with original_questions targets from first 500 closed questions created since 2022-01-01; API creation descending, ID descending for ties",
                            "exclusions": ["missing target after batched API fetch", "normalized query/target title pair matches declared MiniLM duplicate-title training source"],
                            "candidate_corpus": "all 47382 frozen historical records, union current fetched duplicate target records; current target body replaces older snapshot for same ID; exclude own query ID at ranking time",
                            "query_input": "original English question title, HTML entities unescaped; no rewriting",
                            "target_input": "title plus newline plus HTML-unescaped text extracted from body; preserve text/code order",
                            "methods": "same dense/BM25/RRF formulas and fixed parameters as vector-v2-real protocol",
                            "primary_metric": "nDCG@10", "no_tuning": True,
                            "scope": "Additional temporally newer real-question control; not an official BEIR split or proof of fully unseen pretraining data"})
    plan = json.loads(plan_path.read_text())
    assert not (BASE / "summary.json").exists(), "Never reacquire source data after scoring"
    filtered = api("filters/create", {"base": "withbody", "include": "question.closed_details;closed_details.original_questions;original_question.question_id"}, "filter.json")
    filter_id = filtered["items"][0]["filter"]
    all_items = []
    for page in range(1, plan["pages"] + 1):
        data = api("search/advanced", {"site": "unix", "fromdate": plan["fromdate"], "todate": plan["todate"], "closed": "true", "sort": "creation", "order": "desc", "pagesize": 100, "page": page, "filter": filter_id}, f"closed-{page}.json")
        all_items.extend(data["items"])
        print(json.dumps({"page": page, "fetched": len(data["items"]), "quota_remaining": data.get("quota_remaining")}), flush=True)
        if not data.get("has_more"):
            break
    seen = set()
    queries = []
    for q in sorted(all_items, key=lambda q: (q["creation_date"], q["question_id"]), reverse=True):
        if q["question_id"] in seen:
            continue
        seen.add(q["question_id"])
        targets = q.get("closed_details", {}).get("original_questions", [])
        if str(q.get("closed_reason", "")).lower() != "duplicate" or not targets:
            continue
        queries.append(q)
        if len(queries) == plan["max_queries"]:
            break
    assert queries, "No duplicate questions with authoritative targets found"
    target_ids = sorted({str(t["question_id"]) for q in queries for t in q["closed_details"]["original_questions"]})
    targets = {}
    for i in range(0, len(target_ids), 100):
        data = api("questions/" + ";".join(target_ids[i:i + 100]), {"site": "unix", "pagesize": 100, "filter": "withbody"}, f"targets-{i}.json")
        targets.update({str(q["question_id"]): q for q in data["items"]})
    def norm(s):
        return " ".join(html.unescape(s).casefold().split())
    def pair(a, b):
        return tuple(sorted((norm(a), norm(b))))
    wanted = {}
    for q in queries:
        for t in q["closed_details"]["original_questions"]:
            tid = str(t["question_id"])
            if tid in targets:
                wanted.setdefault(pair(q["title"], targets[tid]["title"]), set()).add(str(q["question_id"]))
    matches = set()
    path = ev.BASE / "training-audit-cache/stackexchange_duplicate_questions_title_title.jsonl.gz"
    with gzip.open(path, "rt") as f:
        for line in f:
            row = json.loads(line)
            texts = row if isinstance(row, list) else row.get("texts", row.get("sentences"))
            matches.update(wanted.get(pair(*texts), set()))
    accepted, excluded = [], []
    for q in queries:
        qid = str(q["question_id"])
        tids = sorted({str(t["question_id"]) for t in q["closed_details"]["original_questions"]})
        missing = sorted(set(tids) - targets.keys())
        if missing or qid in matches:
            excluded.append({"query_id": qid, "missing_target_ids": missing, "known_training_title_pair_match": qid in matches})
            continue
        accepted.append({"query_id": qid, "creation_date": q["creation_date"], "source_url": "https://unix.stackexchange.com/questions/" + qid,
                         "target_ids": tids, "target_source_urls": ["https://unix.stackexchange.com/questions/" + t for t in tids]})
    assert accepted
    ev.save(BASE / "cache/selected-questions.json", [q for q in queries if str(q["question_id"]) in {a["query_id"] for a in accepted}])
    ev.save(BASE / "cache/target-questions.json", targets)
    result = {"collected_at": ev.now(), "plan_sha256": ev.sha(plan_path), "closed_questions_fetched": len(all_items),
              "duplicate_questions_selected_before_exclusions": len(queries), "eligible_queries": len(accepted),
              "gold_pairs": sum(len(q["target_ids"]) for q in accepted), "unique_targets": len({t for q in accepted for t in q["target_ids"]}),
              "query_creation_utc_range": [dt.datetime.fromtimestamp(min(q["creation_date"] for q in accepted), dt.timezone.utc).isoformat(), dt.datetime.fromtimestamp(max(q["creation_date"] for q in accepted), dt.timezone.utc).isoformat()],
              "excluded": excluded, "queries": accepted,
              "source_file_sha256": {str(p.relative_to(BASE)): ev.sha(p) for p in sorted((BASE / "cache").glob("*.json"))},
              "source_documentation": "https://api.stackexchange.com/docs/types/closed-details",
              "training_overlap_audit": "All selected query/target title pairs checked against the same 304525-pair declared training mirror; known matches excluded before scoring. Other training sources remain unaudited."}
    ev.save(BASE / "dataset-manifest.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ["queries", "source_file_sha256", "excluded"]}, indent=2))


if __name__ == "__main__":
    main()
