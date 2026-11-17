"""Read-only evidence audit of source threads for the preselected operations control.

This is supplemental current-source evidence, never a replacement for frozen qrels.
Question/answer bodies stay in ignored local cache; public output has IDs and URLs only.
"""
import gzip
import json
import time
import urllib.parse
import urllib.request

import eval_real_vector_retrieval as ev


def fetch(kind, ids):
    url = "https://api.stackexchange.com/2.3/" + kind + "/" + ";".join(ids)
    url += "?" + urllib.parse.urlencode({"site": "unix", "pagesize": 100, "filter": "withbody"})
    req = urllib.request.Request(url, headers={"User-Agent": "monitoring-agent-public-source-audit"})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    data = json.loads(raw)
    if data.get("backoff"):
        time.sleep(min(data["backoff"], 60))
        if data["backoff"] > 60:
            raise RuntimeError("API requests longer backoff; stop audit and retry later")
    assert "error_id" not in data, str(data.get("error_name"))
    return data


def main():
    ev.check_protocol()
    docs, queries, gold, ko = ev.load_data()
    target_ids = sorted(set.union(*(gold[q["_id"]] for q in ko)))
    assert len(target_ids) <= 100
    cache = ev.BASE / "source-audit-cache"
    questions = fetch("questions", target_ids)
    ev.save(cache / "questions.json", questions)
    accepted = sorted(str(q["accepted_answer_id"]) for q in questions["items"] if "accepted_answer_id" in q)
    answers = fetch("answers", accepted) if accepted else {"items": []}
    ev.save(cache / "answers.json", answers)
    available_answers = {str(a["answer_id"]) for a in answers["items"]}
    records = [{"question_id": str(q["question_id"]), "source_url": "https://unix.stackexchange.com/questions/" + str(q["question_id"]),
                "answer_count": q["answer_count"], "accepted_answer_id": str(q["accepted_answer_id"]) if "accepted_answer_id" in q else None,
                "accepted_answer_retrieved": str(q.get("accepted_answer_id")) in available_answers}
               for q in questions["items"]]
    result = {"audited_at": ev.now(), "selection": "all existing gold targets of the 32 preselected Korean-control source query IDs",
              "requested_question_count": len(target_ids), "retrieved_question_count": len(records),
              "accepted_answer_count": len(accepted), "retrieved_accepted_answer_count": len(answers["items"]),
              "missing_question_ids": sorted(set(target_ids) - {r["question_id"] for r in records}),
              "interpretation": "Current source threads with community/user-accepted answers; not independent verification of fixes and not the 2014 answer snapshot. Answers are not embedded or used to change relevance labels.",
              "records": sorted(records, key=lambda r: r["question_id"])}
    ev.save(ev.BASE / "source-case-audit.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "records"}, indent=2))


if __name__ == "__main__":
    main()
