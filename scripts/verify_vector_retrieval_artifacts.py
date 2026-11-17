"""Offline verification of the published synthetic retrieval run; no model/DB calls."""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import eval_vector_retrieval as ev

def verify(base):
    base=Path(base);out=base/"runs/initial";data=ev.read(base/"dataset.json");ev.validate_dataset(data)
    manifest=ev.read(out/"manifest.json")
    # Public fixture/runner hashes are checked relative to the repository root.
    root=base.parents[1]
    for path,expected in manifest["inputs"].items():
        if ev.sha(root/path)!=expected:raise ValueError("Frozen source mismatch: "+path)
    for name,expected in ev.read(out/"artifact-sha256.json").items():
        if ev.sha(out/name)!=expected:raise ValueError("Run artifact mismatch: "+name)
    embeddings=ev.read(out/"embeddings.json");pg=ev.read(out/"pgvector-rankings.json")
    stored=ev.read(out/"results.json");summary=ev.read(out/"summary.json")
    expected_items={x["id"] for x in data["corpus"]+data["queries"]}
    if set(embeddings)!=expected_items:raise ValueError("Embedding set mismatch")
    for vector in embeddings.values():
        if len(vector)!=384 or not all(math.isfinite(x) for x in vector):raise ValueError("Invalid vector")
    queries={q["id"]:q for q in data["queries"]};docs={d["id"]:d for d in data["corpus"]}
    pgmap={(x["query_id"],x["scope"]):x["rows"] for x in pg}
    if len(pgmap)!=136 or len(pg)!=136:raise ValueError("PG query grid mismatch")
    scores={};top_matches=0
    resolutions=[d for d in docs.values() if d["type"]=="resolution"]
    for q in queries.values():
        for scope in ("all","resolution"):
            corpus=list(docs.values()) if scope=="all" else resolutions
            expected=[{"id":d["id"],"score":ev.cosine(embeddings[q["id"]],embeddings[d["id"]])} for d in corpus]
            expected=sorted((x for x in expected if x["score"]>=0),key=lambda x:(-x["score"],x["id"]))
            actual=pgmap[(q["id"],scope)]
            if [x["id"] for x in expected]!=[x["id"] for x in actual]:raise ValueError("Replayed cosine ranking mismatch")
            for a,b in zip(expected,actual):
                if abs(a["score"]-b["score"])>1e-5:raise ValueError("Cosine score mismatch")
            top_matches+=1
        lexical=ev.bm25(q["text"],resolutions)
        scores[(q["id"],"dense_current_all")]=pgmap[(q["id"],"all")]
        scores[(q["id"],"dense_resolution_only")]=pgmap[(q["id"],"resolution")]
        scores[(q["id"],"bm25_resolution_only")]=lexical
        scores[(q["id"],"rrf_resolution_only")]=ev.fuse([pgmap[(q["id"],"resolution")],lexical])
    if len(stored)!=272 or len({(x["query_id"],x["method"]) for x in stored})!=272:raise ValueError("Result grid mismatch")
    groups=defaultdict(list)
    for row in stored:
        q=queries[row["query_id"]];ranking=scores[(q["id"],row["method"])];top=ranking[:5]
        if row["answerable"]!=q["answerable"] or row["variant"]!=q["variant"]:raise ValueError("Query group mismatch")
        if [x["id"] for x in row["top5"]]!=[x["id"] for x in top]:raise ValueError("Stored top5 order differs from ranking")
        # Set iteration can change floating-point summation by a few ulps between processes.
        if any(abs(a["score"]-b["score"])>1e-12 for a,b in zip(row["top5"],top)):raise ValueError("Stored top5 scores differ beyond rounding tolerance")
        wrong=sum(docs[x["id"]]["type"]!="resolution" for x in top)/len(top) if top else 0
        if abs(wrong-row["wrong_type_fraction_at_5"])>1e-12:raise ValueError("Wrong-type rate mismatch")
        if q["answerable"]:
            gold=next(iter(data["qrels"][q["id"]]));ids=[x["id"] for x in ranking];rank=ids.index(gold)+1 if gold in ids else None
            # Independently re-derive the metric formula, without calling ev.measures.
            expected={"hit_at_1":float(rank==1),"recall_at_3":float(rank is not None and rank<=3),"recall_at_5":float(rank is not None and rank<=5),
                      "mrr_at_5":1/rank if rank is not None and rank<=5 else 0,"ndcg_at_5":math.log(2)/math.log(rank+1) if rank is not None and rank<=5 else 0}
            if row["metrics"]["relevant_rank"]!=rank:raise ValueError("Relevant rank mismatch")
            for k,v in expected.items():
                if abs(v-row["metrics"][k])>1e-12:raise ValueError("Metric mismatch: "+k)
            groups[(row["method"],"all")].append(expected);groups[(row["method"],q["variant"])].append(expected)
        elif row["returned_without_relevant_document"]!=bool(top):raise ValueError("Negative-query result mismatch")
    for (method,variant),rows in groups.items():
        reported=summary["methods"][method]["positive"][variant]
        if reported["queries"]!=len(rows):raise ValueError("Denominator mismatch")
        for k in rows[0]:
            if abs(reported[k]-sum(x[k] for x in rows)/len(rows))>1e-12:raise ValueError("Aggregate mismatch")
    for method in ev.METHODS:
        positives=[x for x in stored if x["method"]==method and x["answerable"]]
        negatives=[x for x in stored if x["method"]==method and not x["answerable"]]
        reported=summary["methods"][method]
        if reported["negative_queries"]!=len(negatives):raise ValueError("Negative denominator mismatch")
        if abs(reported["negative_nonempty_rate"]-sum(x["returned_without_relevant_document"] for x in negatives)/len(negatives))>1e-12:raise ValueError("Negative rate mismatch")
        if abs(reported["wrong_type_fraction_at_5"]-sum(x["wrong_type_fraction_at_5"] for x in positives)/len(positives))>1e-12:raise ValueError("Aggregate wrong-type rate mismatch")
    return {"status":"passed","frozen_inputs":len(manifest["inputs"]),"artifacts":len(ev.read(out/"artifact-sha256.json")),"embedding_items":len(embeddings),"pgvector_rankings_reproduced":top_matches,"result_rows":len(stored),"positive_metric_groups":len(groups),"paid_api_calls":0,"scope":"Artifact integrity and arithmetic; not independent relevance-label certification."}

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--base",type=Path,default=ev.BASE);args=parser.parse_args()
    print(json.dumps(verify(args.base),ensure_ascii=False))
