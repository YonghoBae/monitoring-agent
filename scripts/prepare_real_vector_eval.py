"""Download the maintained public CQADupStack Unix snapshot without rewriting it."""
import datetime,hashlib,json,os,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'eval/vector-v2-real'
REPO='mteb/cqadupstack-unix'
FILES=('corpus.jsonl','queries.jsonl','qrels/test.tsv','README.md')
def save(path,obj):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def main():
 BASE.mkdir(exist_ok=True)
 revision='3197b09145642430d9db451fcdc1e1987e54d74c'
 manifest=json.loads((BASE/'source-manifest.json').read_text()) if (BASE/'source-manifest.json').exists() else None
 if manifest: assert manifest['revision']==revision and manifest['repository']==REPO
 expected={row['path']:row['sha256'] for row in manifest['files']} if manifest else {}
 print('Pinned dataset revision '+revision,flush=True);records=[]
 for name in FILES:
  dest=BASE/'upstream'/name;dest.parent.mkdir(parents=True,exist_ok=True)
  url='https://huggingface.co/datasets/'+REPO+'/resolve/'+revision+'/'+name
  if not dest.exists():
   temp=dest.with_suffix(dest.suffix+'.part');request=urllib.request.Request(url,headers={'User-Agent':'monitoring-agent-retrieval-eval'})
   count=0
   with urllib.request.urlopen(request,timeout=30) as response,temp.open('wb') as out:
    while True:
     chunk=response.read(1024*1024)
     if not chunk:break
     out.write(chunk);count+=len(chunk)
     if count%(5*1024*1024)<1024*1024:print(name+' bytes='+str(count),flush=True)
   temp.rename(dest)
  digest=hashlib.sha256(dest.read_bytes()).hexdigest()
  if expected: assert digest==expected[name], 'Source checksum mismatch: '+name
  records.append({'path':name,'url':url,'bytes':dest.stat().st_size,'sha256':digest});print('Verified '+name+' '+str(dest.stat().st_size),flush=True)
 if not manifest:
  save(BASE/'source-manifest.json',{'repository':REPO,'revision':revision,'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':records,'original_paper':'https://doi.org/10.1145/2838931.2838934','benchmark':'https://github.com/beir-cellar/beir','upstream_terms_note':'Original CQADupStack paper specifies CC BY-SA 3.0; maintained mirrors have differing metadata. Original text is cached locally and not redistributed by this project.'})
if __name__=='__main__':main()
