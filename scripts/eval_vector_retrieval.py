"""Source-grounded controlled retrieval diagnostic; stdlib only, no paid API.
Uses local Ollama embeddings and a disposable, network-isolated pgvector DB.
No production DB connection, threshold tuning, LLM judge or remediation.
"""
import argparse
from collections import Counter, defaultdict
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "eval/vector-v1"
MODEL = "all-minilm:latest"
METHODS = ("dense_current_all", "dense_resolution_only", "bm25_resolution_only", "rrf_resolution_only")

def read(path): return json.loads(Path(path).read_text())
def save(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2)+"\n")
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def api(endpoint, route, body=None):
    request = urllib.request.Request(endpoint.rstrip("/")+route,
        data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response: return json.load(response)

def tokens(text):
    parts = re.findall(r"[a-z0-9_]+|[가-힣]+", text.lower())
    result = []
    for word in parts:
        if re.fullmatch(r"[가-힣]+", word):
            result.extend(["ko:"+word[i:i+2] for i in range(len(word)-1)] if len(word)>1 else ["ko:"+word])
        else: result.append("latin:"+word)
    return result

def bm25(query, docs, k1=1.2, b=.75):
    counts = {d["id"]: Counter(tokens(d["text"])) for d in docs}
    lengths = {k:sum(v.values()) for k,v in counts.items()}
    average = sum(lengths.values())/len(docs)
    df = Counter(term for c in counts.values() for term in c)
    result = []
    for doc in docs:
        ident = doc["id"]; score = 0.0
        for term in set(tokens(query)):
            tf = counts[ident][term]
            if not tf: continue
            idf = math.log(1+(len(docs)-df[term]+.5)/(df[term]+.5))
            score += idf*tf*(k1+1)/(tf+k1*(1-b+b*lengths[ident]/average))
        result.append({"id": ident, "score": score})
    return sorted(result, key=lambda row:(-row["score"],row["id"]))

def fuse(rankings, constant=60):
    scores = defaultdict(float)
    for ranking in rankings:
        if len({r["id"] for r in ranking}) != len(ranking): raise ValueError("Duplicate ranking document")
        for rank,row in enumerate(ranking,1): scores[row["id"]] += 1/(constant+rank)
    return sorted(({"id":ident,"score":score} for ident,score in scores.items()), key=lambda r:(-r["score"],r["id"]))

def measures(ranking, relevant):
    if len(relevant)!=1: raise ValueError("This controlled benchmark requires exactly one relevant document")
    ids=[row["id"] for row in ranking]
    if len(ids)!=len(set(ids)): raise ValueError("Duplicate document in ranking")
    positions=[i+1 for i,ident in enumerate(ids) if ident in relevant]
    rank=min(positions) if positions else None
    return {"hit_at_1":float(rank==1), "recall_at_3":float(rank is not None and rank<=3),
            "recall_at_5":float(rank is not None and rank<=5),
            "mrr_at_5":1/rank if rank is not None and rank<=5 else 0.0,
            "ndcg_at_5":1/math.log2(rank+1) if rank is not None and rank<=5 else 0.0,
            "relevant_rank":rank}

def validate_dataset(data):
    docs={d["id"]:d for d in data["corpus"]}
    if len(docs)!=40 or len(data["corpus"])!=40 or len(data["queries"])!=68: raise ValueError("Unexpected dataset size")
    query_ids=[q["id"] for q in data["queries"]]
    if len(set(query_ids))!=len(query_ids) or set(query_ids)!=set(data["qrels"]): raise ValueError("Query/qrel mismatch")
    if sum(q["answerable"] for q in data["queries"])!=60: raise ValueError("Unexpected positive query count")
    for q in data["queries"]:
        gold=data["qrels"][q["id"]]
        if bool(gold)!=q["answerable"]: raise ValueError("Answerability mismatch")
        if q["answerable"] and (len(gold)!=1 or any(docs[k]["type"]!="resolution" or docs[k]["family"]!=q["family"] for k in gold)):
            raise ValueError("Wrong-type/family relevance label")
    for doc in docs.values():
        fields=("alertName","alertSummary","resolutionSteps") if doc["type"]=="resolution" else ("alertName","message","annotationSummary")
        expected=" | ".join([doc[k] for k in fields]+(["outcome="+doc["outcome"]] if doc["type"]=="resolution" else []))
        if doc["text"]!=expected or not doc["synthetic"]: raise ValueError("Serialization or provenance mismatch")
    return True

def model_identity(endpoint):
    candidates=[m for m in api(endpoint,"/api/tags")["models"] if m["name"]==MODEL]
    if len(candidates)!=1: raise ValueError("Exact configured model is not installed")
    return {k:candidates[0][k] for k in ("name","digest","size")}

def freeze(endpoint):
    out=BASE/"runs/initial"
    if out.exists(): raise ValueError("Run already exists; do not overwrite")
    data=read(BASE/"dataset.json");validate_dataset(data)
    paths=["eval/vector-v1/"+f for f in ("dataset.json","sources.json","protocol.json")]+[
        "scripts/eval_vector_retrieval.py","scripts/tests/test_vector_retrieval.py",
        "src/main/java/io/ohgnoy/monitoring/infrastructure/rag/AlertVectorService.java"]
    manifest={"kind":"controlled_retrieval_diagnostic", "frozen_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "inputs":{p:sha(ROOT/p) for p in paths}, "model":model_identity(endpoint),
        "ollama_version":api(endpoint,"/api/version"), "endpoint":"local Ollama; address excluded from public metadata",
        "model_details":api(endpoint,"/api/show",{"model":MODEL})["details"], "paid_api_calls":0}
    save(out/"manifest.json",manifest)
    return manifest

def verify_frozen(manifest):
    for name,expected in manifest["inputs"].items():
        if sha(ROOT/name)!=expected: raise ValueError("Frozen input changed: "+name)

def cosine(a,b):
    return sum(x*y for x,y in zip(a,b))/math.sqrt(sum(x*x for x in a)*sum(y*y for y in b))
def sql_string(value): return "'"+value.replace("'","''")+"'"
def vector_literal(values): return sql_string("["+",".join(format(v,".10g") for v in values)+"]")+"::vector"
def sql(container, script):
    command=["rtk","proxy","docker","exec","-i",container,"psql","-U","postgres","-d","vector_eval","-v","ON_ERROR_STOP=1","-qAt"]
    result=subprocess.run(command,input=script,capture_output=True,text=True)
    if result.returncode: raise RuntimeError("Isolated pgvector SQL failed: "+result.stderr[:1000])
    return result.stdout

def decode_json_stream(text):
    decoder=json.JSONDecoder();rows=[];position=0
    while position<len(text):
        while position<len(text) and text[position].isspace():position+=1
        if position==len(text):break
        row,position=decoder.raw_decode(text,position);rows.append(row)
    return rows

def run(endpoint, container):
    out=BASE/"runs/initial";manifest=read(out/"manifest.json");verify_frozen(manifest)
    if (out/"embeddings.json").exists() or (out/"results.json").exists(): raise ValueError("Run already attempted; preserve its artifacts")
    if model_identity(endpoint)!=manifest["model"]: raise ValueError("Model identity changed")
    data=read(BASE/"dataset.json");validate_dataset(data)
    items=data["corpus"]+data["queries"];embeddings={};batches=[]
    for offset in range(0,len(items),8):
        batch=items[offset:offset+8];start=time.perf_counter()
        response=api(endpoint,"/api/embed",{"model":MODEL,"input":[x["text"] for x in batch],"truncate":False,"keep_alive":"5m"})
        elapsed=time.perf_counter()-start;vectors=response["embeddings"]
        if len(vectors)!=len(batch): raise ValueError("Embedding cardinality mismatch")
        for item,vector in zip(batch,vectors):
            if len(vector)!=384 or not all(math.isfinite(x) for x in vector) or sum(x*x for x in vector)<=0: raise ValueError("Invalid embedding")
            embeddings[item["id"]]=vector
        batches.append({"count":len(batch),"elapsed_seconds":elapsed,"prompt_eval_count":response.get("prompt_eval_count"),"load_duration":response.get("load_duration")})
        print(json.dumps({"embedded":len(embeddings),"total":len(items)}),flush=True)
    save(out/"embeddings.json",embeddings);save(out/"embedding-batches.json",batches)
    statements=["CREATE EXTENSION IF NOT EXISTS vector;", "CREATE TABLE retrieval_eval (id text PRIMARY KEY, kind text NOT NULL, content text NOT NULL, embedding vector(384));"]
    for doc in data["corpus"]:
        statements.append("INSERT INTO retrieval_eval VALUES ("+",".join([sql_string(doc["id"]),sql_string(doc["type"]),sql_string(doc["text"]),vector_literal(embeddings[doc["id"]])])+");")
    sql(container,"\n".join(statements))
    db_version=sql(container,"SELECT json_build_object('postgres_version',version(),'pgvector_version',(SELECT extversion FROM pg_extension WHERE extname='vector'));" ).strip()
    queries=[]
    for query in data["queries"]:
        vec=vector_literal(embeddings[query["id"]])
        for scope in ("all","resolution"):
            where="1-(embedding <=> "+vec+") >= 0"+(" AND kind='resolution'" if scope=="resolution" else "")
            queries.append("SELECT json_build_object('query_id',"+sql_string(query["id"])+",'scope',"+sql_string(scope)+",'rows',COALESCE(json_agg(r),'[]'::json)) FROM (SELECT id, 1-(embedding <=> "+vec+") AS score FROM retrieval_eval WHERE "+where+" ORDER BY embedding <=> "+vec+",id) r;")
    started=time.perf_counter();pg_rows=decode_json_stream(sql(container,"\n".join(queries)));pg_seconds=time.perf_counter()-started
    if len(pg_rows)!=len(data["queries"])*2: raise ValueError("Missing DB query results")
    save(out/"pgvector-rankings.json",pg_rows)
    lookup={(x["query_id"],x["scope"]):x["rows"] for x in pg_rows}
    docs={d["id"]:d for d in data["corpus"]};resolutions=[d for d in data["corpus"] if d["type"]=="resolution"]
    results=[];max_delta=0.0;exact_rank_matches=0
    for query in data["queries"]:
        for scope in ("all","resolution"):
            ranked=lookup[(query["id"],scope)];candidates=data["corpus"] if scope=="all" else resolutions
            python_rank=sorted([{"id":d["id"],"score":cosine(embeddings[query["id"]],embeddings[d["id"]])} for d in candidates],key=lambda x:(-x["score"],x["id"]))
            python_rank=[x for x in python_rank if x["score"]>=0]
            if set(x["id"] for x in ranked)!=set(x["id"] for x in python_rank): raise ValueError("DB candidate mismatch")
            exact_rank_matches += [x["id"] for x in ranked]==[x["id"] for x in python_rank]
            py_scores={x["id"]:x["score"] for x in python_rank}
            for x in ranked:
                delta=abs(x["score"]-py_scores[x["id"]]);max_delta=max(max_delta,delta)
                if delta>1e-5: raise ValueError("DB cosine disagrees with independent arithmetic")
        lexical=bm25(query["text"],resolutions)
        rankings={"dense_current_all":lookup[(query["id"],"all")],"dense_resolution_only":lookup[(query["id"],"resolution")],
                  "bm25_resolution_only":lexical,"rrf_resolution_only":fuse([lookup[(query["id"],"resolution")],lexical])}
        for method,ranking in rankings.items():
            top=ranking[:5];row={"query_id":query["id"],"family":query["family"],"variant":query["variant"],"answerable":query["answerable"],"method":method,"top5":top,
                "wrong_type_fraction_at_5":sum(docs[x["id"]]["type"]!="resolution" for x in top)/len(top) if top else 0.0}
            if query["answerable"]: row["metrics"]=measures(ranking,data["qrels"][query["id"]])
            else: row["returned_without_relevant_document"]=bool(top)
            results.append(row)
    metrics=["hit_at_1","recall_at_3","recall_at_5","mrr_at_5","ndcg_at_5"]
    aggregates={}
    for method in METHODS:
        selected=[r for r in results if r["method"]==method];positive=[r for r in selected if r["answerable"]];negative=[r for r in selected if not r["answerable"]]
        groups={}
        for variant in ("all","ko_direct","ko_paraphrase","en_paraphrase"):
            group=positive if variant=="all" else [r for r in positive if r["variant"]==variant]
            groups[variant]={"queries":len(group),**{metric:sum(r["metrics"][metric] for r in group)/len(group) for metric in metrics}}
        aggregates[method]={"positive":groups,"wrong_type_fraction_at_5":sum(r["wrong_type_fraction_at_5"] for r in positive)/len(positive),
            "negative_queries":len(negative),"negative_nonempty_rate":sum(r["returned_without_relevant_document"] for r in negative)/len(negative)}
    verify_frozen(manifest)
    if model_identity(endpoint)!=manifest["model"]: raise ValueError("Model changed during run")
    summary={"kind":"controlled_retrieval_diagnostic", "completed_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"methods":aggregates,
        "embedding_items":len(items),"embedding_elapsed_seconds":sum(b["elapsed_seconds"] for b in batches),
        "postgres":json.loads(db_version),"pgvector_queries":len(pg_rows),"pgvector_total_seconds_including_docker_exec":pg_seconds,
        "max_cosine_difference_from_python":max_delta,"identical_full_rankings_to_python":exact_rank_matches,
        "inputs_unchanged":True,"paid_api_calls":0,"limitations":["authored controlled relevance labels, no independent human review","small 20-family corpus, no population accuracy claim","current serialization and retrieval policy reproduced, not full Spring AI end-to-end","no ANN performance or threshold calibration","no downstream answer/remediation quality measurement"]}
    save(out/"results.json",results);save(out/"summary.json",summary)
    artifacts={p.name:sha(p) for p in out.iterdir() if p.is_file()}
    save(out/"artifact-sha256.json",artifacts)
    print(json.dumps({method:summary["methods"][method]["positive"]["all"] for method in METHODS},ensure_ascii=False),flush=True)
    return summary

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("freeze","run"));parser.add_argument("--endpoint",default=os.environ.get("EVAL_EMBEDDING_URL","http://localhost:11434"))
    parser.add_argument("--container",default="monitoring-vector-eval-20261117")
    args=parser.parse_args()
    if args.mode=="freeze": print(json.dumps(freeze(args.endpoint),ensure_ascii=False))
    else: run(args.endpoint,args.container)
