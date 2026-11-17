"""Separate diagnostic replay of truncated judgments; never rewrites official scores.
Only max_tokens changes. Requests are hash-matched to the original paid ledger.
Each selected (answer, judge repetition) is called once, without automatic retries.
"""
import argparse
import copy
import datetime
import json
from pathlib import Path
from unittest.mock import patch
import budget_registry as budget
import structured_haiku_v54 as api
from semantic_judge_v54 import SYSTEM, validate

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "eval/v5/legacy-scoring-v55"
DEST = "eval/v5/output-budget-diagnostic-16384-20261117"
LIMIT = 16384
CODE = ("scripts/diagnose_judge_output_budget.py", "scripts/structured_haiku_v54.py",
        "scripts/semantic_judge_v54.py", "scripts/haiku_rejudge.py", "scripts/budget_registry.py")

def digest(path):
    return api.sha(Path(path).read_bytes())

def change_limit(body):
    if body.get("max_tokens") != 4096:
        raise ValueError("Expected original 4096-token request")
    result = copy.deepcopy(body)
    result["max_tokens"] = LIMIT
    return result

def verify_files(root, hashes):
    for relative, expected in hashes.items():
        if digest(root/relative) != expected:
            raise ValueError("Frozen diagnostic input changed: " + relative)

def plan(root=ROOT):
    source = root/SOURCE
    diagnostic = api.read(source/"judge-output-diagnostics.json")
    rows = [row for row in diagnostic["rows"] if row["stop_reason"] == "max_tokens"]
    if len(rows) != 33 or len({(r["id"], r["judge_rep"]) for r in rows}) != 33:
        raise ValueError("Unexpected selected request set")
    requests = []
    for row in rows:
        ident, rep = row["id"], row["judge_rep"]
        payload = api.read(source/"payloads"/(ident+".json"))
        old = api.request_body(payload, SYSTEM)
        request_id = "legacy-comparison-"+ident
        events = api.lines(source/f"judge-{rep}"/"requests.jsonl")
        starts = [e for e in events if e.get("event") == "started" and e["request_id"] == request_id]
        old_hash = api.sha(api.encode(old).encode())
        if len(starts) != 1 or starts[0]["payload_sha256"] != old_hash:
            raise ValueError("Original request cannot be reproduced exactly")
        original_raw = source/f"judge-{rep}"/"raw"/(request_id+".json")
        if api.read(original_raw).get("stop_reason") != "max_tokens":
            raise ValueError("Selected original response was not truncated")
        new = change_limit(old)
        raw = api.encode(new).encode()
        reserved_input = len(raw)+4096
        if reserved_input > 100000:
            raise ValueError("Unexpected long-context reservation")
        requests.append({"id": f"rep-{rep}-{ident}", "original_answer_id": ident,
            "original_judge_rep": rep, "original_request_sha256": old_hash,
            "original_response": str(original_raw.relative_to(root)),
            "new_request_sha256": api.sha(raw), "payload_sha256": api.sha(api.encode(payload).encode()),
            "reservation_usd": (reserved_input*.10 + LIMIT*.50)/1e6,
            "payload": payload, "request_body": new})
    hashes = {str(p.relative_to(root)): digest(p) for p in source.rglob("*")
              if p.is_file() and not p.name.endswith(".lock")}
    hashes.update({relative: digest(root/relative) for relative in CODE})
    state = budget.preflight(root, source/"judge-1")
    maximum = sum(r["reservation_usd"] for r in requests)
    if state["total_campaigns_estimated_usd"]+maximum > 2:
        raise ValueError("Entire diagnostic would exceed the existing global budget")
    return {"kind": "posthoc_truncation_diagnostic_not_a_score_update",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "changed_parameter": {"max_tokens": {"before": 4096, "after": LIMIT}},
        "model": api.MODEL, "effort": "medium", "calls": len(requests),
        "unique_answers": len({r["original_answer_id"] for r in requests}),
        "prior_cost_usd": state["total_campaigns_estimated_usd"],
        "conservative_additional_usd": maximum, "source_hashes": hashes,
        "requests": requests, "scope": "Selected failures only; completion/validation is not correctness calibration."}

def prepare(root=ROOT):
    out = root/DEST
    if out.exists():
        raise ValueError("Diagnostic output already exists; no overwrite")
    prepared = plan(root)
    out.mkdir(parents=True)
    (out/"raw").mkdir()
    (out/"inputs").mkdir()
    for row in prepared["requests"]:
        api.save(out/"inputs"/(row["id"]+".json"), row.pop("payload"))
        api.save(out/"inputs"/(row["id"]+"-request.json"), row.pop("request_body"))
    api.save(out/"plan.json", prepared)
    api.save(out/"manifest.json", {"kind": prepared["kind"], "max_output_tokens": LIMIT,
             "prior_campaign_cost_usd": prepared["prior_cost_usd"],
             "plan_sha256": digest(out/"plan.json")})
    # Preserve the old registry bytes before explicitly adding this new authorized diagnostic.
    with budget._lock(root):
        registry_path = root/"eval/paid-campaigns.json"
        original = registry_path.read_bytes()
        (out/"budget-registry-before.json").write_bytes(original)
        registry = json.loads(original)
        if DEST in registry["campaigns"]:
            raise ValueError("Diagnostic already registered")
        registry["campaigns"].append(DEST)
        api.save(registry_path, registry)
        budget.state(root, out)
    return prepared

def summary(root=ROOT):
    out = root/DEST
    prepared = api.read(out/"plan.json")
    rows = api.lines(out/"results.jsonl")
    state = budget.preflight(root, out)
    result = {"kind": prepared["kind"], "planned_calls": prepared["calls"],
        "completed_calls": len(rows), "locally_valid": sum(r["locally_valid"] for r in rows),
        "truncated": sum(r["stop_reason"] == "max_tokens" for r in rows),
        "other_invalid": sum(not r["locally_valid"] and r["stop_reason"] != "max_tokens" for r in rows),
        "output_tokens": [r["usage"]["output_tokens"] for r in rows],
        "cost": state, "official_scores_modified": False,
        "caveat": "Validation checks structure/evidence bindings, not independent semantic correctness."}
    api.save(out/"summary.json", result)
    return result

def run(root=ROOT):
    out = root/DEST
    prepared = api.read(out/"plan.json")
    manifest = api.read(out/"manifest.json")
    if digest(out/"plan.json") != manifest["plan_sha256"]:
        raise ValueError("Diagnostic plan changed")
    if (out/"requests.jsonl").exists() or (out/"results.jsonl").exists():
        raise ValueError("Already attempted; automatic replay forbidden")
    verify_files(root, prepared["source_hashes"])
    key = api.key_from_env(root/".env")
    # Process-local override: original transport and scoring files remain byte-identical.
    with patch.object(api, "MAX_OUTPUT", LIMIT):
        for index, item in enumerate(prepared["requests"], 1):
            payload = api.read(out/"inputs"/(item["id"]+".json"))
            if api.sha(api.encode(payload).encode()) != item["payload_sha256"]:
                raise ValueError("Diagnostic payload changed")
            body = api.request_body(payload, SYSTEM)
            saved = api.read(out/"inputs"/(item["id"]+"-request.json"))
            if body != saved or api.sha(api.encode(body).encode()) != item["new_request_sha256"]:
                raise ValueError("Request differs beyond the approved token limit")
            raw = budget.paid_call(api, root, out, item["id"], payload, key, "token-diagnostic", SYSTEM)
            result = {"id": item["id"], "original_answer_id": item["original_answer_id"],
                      "original_judge_rep": item["original_judge_rep"], "locally_valid": False,
                      "stop_reason": raw.get("stop_reason"), "usage": raw["usage"]}
            try:
                parsed = api.response_json(raw)
                validate(parsed, payload)
                result.update(locally_valid=True, semantic_result=parsed)
            except (ValueError, KeyError, TypeError) as error:
                result["validation_error"] = str(error)
            api.append(out/"results.jsonl", result)
            current = summary(root)
            print(json.dumps({"completed": index, "planned": prepared["calls"],
                "valid": current["locally_valid"], "truncated": current["truncated"],
                "other_invalid": current["other_invalid"],
                "additional_usd": current["cost"]["estimated_usd"],
                "total_usd": current["cost"]["total_campaigns_estimated_usd"]}), flush=True)
    verify_files(root, prepared["source_hashes"])
    final = summary(root)
    final["original_artifact_hashes_verified"] = len(prepared["source_hashes"])
    api.save(out/"summary.json", final)
    return final

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "prepare", "run"))
    args = parser.parse_args()
    if args.mode == "preflight":
        result = plan()
        print(json.dumps({k:v for k,v in result.items() if k not in ("requests", "source_hashes")}))
    elif args.mode == "prepare":
        result = prepare()
        print(json.dumps({"prepared_calls": result["calls"], "reservation_usd": result["conservative_additional_usd"]}))
    else:
        run()
