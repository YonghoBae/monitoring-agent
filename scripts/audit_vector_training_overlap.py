"""Post-score validity audit, not a new benchmark or parameter-selection step.

Find exact title-pair matches in a declared MiniLM training-data mirror. A match
does not prove a particular optimizer batch saw that item; absence is not proof
of clean holdout, because other training sources/body variants are not checked.
Raw training text remains in the ignored cache.
"""
import gzip
import html
import json
import urllib.request

import eval_real_vector_retrieval as ev

REPO = "sentence-transformers/embedding-training-data"
NAME = "stackexchange_duplicate_questions_title_title.jsonl.gz"
CONFIG_URL = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/raw/main/data_config.json"


def download(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        req = urllib.request.Request(url, headers={"User-Agent": "monitoring-agent-training-overlap-audit"})
        tmp = path.with_suffix(path.suffix + ".part")
        count = 0
        with urllib.request.urlopen(req, timeout=30) as response, tmp.open("wb") as f:
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > 100 * 1024 * 1024:
                    raise RuntimeError("Unexpected download >100 MiB; stop audit")
                f.write(chunk)
        tmp.rename(path)


def main():
    ev.check_protocol()
    cache = ev.BASE / "training-audit-cache"
    config_path = cache / "data_config.json"
    download(CONFIG_URL, config_path)
    config = json.loads(config_path.read_text())
    source = next(row for row in config if row["name"] == NAME)
    with urllib.request.urlopen("https://huggingface.co/api/datasets/" + REPO, timeout=20) as response:
        meta = json.load(response)
    revision = meta["sha"]
    url = "https://huggingface.co/datasets/" + REPO + "/resolve/" + revision + "/" + NAME
    path = cache / NAME
    download(url, path)
    docs, queries, gold, ko = ev.load_data()
    titles = {d["_id"]: d["title"] for d in docs}
    def normalized(s):
        return " ".join(html.unescape(s).casefold().split())
    def key(a, b, normal=False):
        return tuple(sorted((normalized(a), normalized(b)))) if normal else tuple(sorted((a, b)))
    exact = {}
    norm = {}
    for q in queries:
        for doc in gold[q["_id"]]:
            exact.setdefault(key(q["text"], titles[doc]), []).append((q["_id"], doc))
            norm.setdefault(key(q["text"], titles[doc], True), []).append((q["_id"], doc))
    matches = set()
    normalized_matches = set()
    lines = 0
    with gzip.open(path, "rt") as f:
        for line in f:
            row = json.loads(line)
            pair = row if isinstance(row, list) else row.get("texts", row.get("sentences"))
            assert isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, str) for x in pair), "Unexpected training pair schema"
            matches.update(exact.get(key(*pair), []))
            normalized_matches.update(norm.get(key(*pair, normal=True), []))
            lines += 1
    result = {"audited_at": ev.now(), "audit_timing": "after primary scores; primary scores and protocol unchanged",
              "model_card": "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2",
              "training_config_url": CONFIG_URL, "training_config_sha256": ev.sha(config_path), "declared_training_entry": source,
              "mirror_repository": REPO, "mirror_revision": revision, "mirror_url": url, "mirror_sha256": ev.sha(path),
              "training_pairs_scanned": lines, "declared_line_count_matches": lines == source["lines"],
              "evaluation_qrel_pairs": sum(map(len, gold.values())), "evaluation_queries": len(queries),
              "exact_title_pair_matches": len(matches), "queries_with_exact_pair_match": len({q for q, d in matches}),
              "normalized_title_pair_matches": len(normalized_matches), "queries_with_normalized_pair_match": len({q for q, d in normalized_matches}),
              "normalized_match_rule": "HTML entity unescape, casefold, collapse whitespace; pair direction ignored",
              "exact_matching_qrel_ids": [list(pair) for pair in sorted(matches)],
              "normalized_matching_qrel_ids": [list(pair) for pair in sorted(normalized_matches)],
              "limits": ["Title-pair overlap with a declared training mirror is evidence of contamination risk, not proof of actual batch exposure.", "No-match subset is not certified unseen: body/title-body/answer sources and base-model training were not audited.", "Do not claim clean held-out generalization or transfer to production from this benchmark."]}
    ev.save(ev.BASE / "training-overlap-audit.json", result)
    print(json.dumps({k: v for k, v in result.items() if not k.endswith("qrel_ids")}, indent=2))


if __name__ == "__main__":
    main()
