import hashlib,json,urllib.request,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'eval/v5/sources'
SOURCES=[('gitlab-postmortem.html','https://about.gitlab.com/blog/postmortem-of-database-outage-of-january-31/','Published production postmortem; only pg_dump client/server incompatibility mechanism adapted.'),
('pg-dump-17-web-extract.txt','https://www.postgresql.org/docs/17/app-pgdump.html','Official directional version compatibility specification, archived browser text extract; direct TLS fetch timed out.'),
('postgres-722-issue.json','https://github.com/docker-library/postgres/issues/722','Real user report; PostgreSQL11 unreadable init SQL.'),
('postgres-722-comments.json','https://github.com/docker-library/postgres/issues/722#issuecomment-621161536','Reporter chown workaround and closure; no independent post-fix telemetry.'),
('compose-12593-comments.json','https://github.com/docker/compose/issues/12593','Rejected as clean single-cause gold: multiple network/resolver changes.')]
def main():
    rows=[]
    for filename,url,claim in SOURCES:
        path=OUT/filename
        if not path.exists():
            req=urllib.request.Request(url,headers={'User-Agent':'evaluation-source-archive/1.0'})
            with urllib.request.urlopen(req,timeout=30) as r:path.write_bytes(r.read())
        rows.append({'path':filename,'url':url,'claim_scope':claim,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
    (OUT/'manifest.json').write_text(json.dumps({'frozen_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sources':rows},indent=2)+'\n')
    print('Frozen',len(rows),'public source artifacts; URLs, exact hashes and adaptation scopes recorded.')
if __name__=='__main__':main()
