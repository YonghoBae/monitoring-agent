"""Build a narrow capture replay benchmark; no manufactured incident telemetry."""
import datetime,hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'eval/v5'
def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def main():
    capture=OUT/'capture-20261117'
    events={e['id']:e for e in json.loads((capture/'events.json').read_text())}
    phases=json.loads((capture/'phases.json').read_text())
    scenes=[];gold={};mapping={}
    plans=[('pg_dump_version','normal','case-201'),('pg_init_permissions','fault','case-202'),
           ('pg_dump_version','partial','case-203'),('pg_init_permissions','recovered','case-204'),
           ('pg_dump_version','fault','case-205'),('pg_init_permissions','normal','case-206'),
           ('pg_dump_version','recovered','case-207'),('pg_init_permissions','partial','case-208')]
    for family,phase,ident in plans:
        backup=family=='pg_dump_version';partial=phase=='partial';fault=phase=='fault'
        selected=phases[family]['fault' if partial else phase]
        logs=[]
        for eid in selected:
            e=events[eid]
            if partial:
                if (backup and eid!='event-24') or (not backup and eid!='event-51'):continue
                output={'operation':'pg_dump' if backup else 'container state',
                        'exit_code':e['exit_code'] if backup else json.loads(e['stdout'])['ExitCode'],
                        'detail':'Detailed output is unavailable in this view.'}
                logs.append((json.dumps(output,ensure_ascii=False),e['captured_at']));continue
            if not backup and eid in ('event-43','event-52','event-67'):
                # Docker logs stdout/stderr are separate pipes. Merge original timestamped lines.
                logs.extend((line,e['captured_at']) for line in sorted((e['stdout']+e['stderr']).splitlines()))
            else:
                operation=('pg_dump' if eid in ('event-19','event-24','event-25') else
                           'SELECT count(*),sum(value) FROM restored eval_marker' if eid in ('event-22','event-28') else
                           'SELECT count(*) FROM eval_marker' if eid in ('event-42','event-66') else
                           'pg_dump --version' if eid=='event-23' else
                           'SHOW server_version' if eid=='event-18' else 'container state')
                logs.append((json.dumps({'operation':operation,'exit_code':e['exit_code'],
                                       'stdout':e['stdout'],'stderr':e['stderr']},ensure_ascii=False),e['captured_at']))
        # Source IDs, experimental names and interventions remain out of agent-visible views.
        entries=[];evaluation_time=datetime.datetime.fromisoformat('2026-11-16T15:17:00+00:00')
        for line,captured_at in logs:
            timestamp=re.match(r'^(\d{4}-\d\d-\d\dT\S+Z) ',line)
            observed_at=datetime.datetime.fromisoformat((timestamp.group(1) if timestamp else captured_at).replace('Z','+00:00'))
            entries.append({'offset_seconds':int((observed_at-evaluation_time).total_seconds()),
                            'line':re.sub(r'monitoring-v5-[a-z0-9]+-[A-Za-z0-9-]+','service-db',line)})
        task=('백업 작업과 해당 덤프의 제한적인 복원 검사' if backup else 'PostgreSQL 초기화와 초기 데이터 조회')
        question=f'service-db의 수집 기록을 조회해서 {task} 결과를 알려줘. 실패했다면 기록으로 확인되는 직접 원인을 설명하고, 확인되지 않는 근본 원인은 단정하지 마. 성공 여부나 원인을 알 수 없으면 구분해서 알려줘. 운영 변경은 실행하지 마.'
        fields=[{'key':'operation_status','question':'수집된 작업 결과: succeeded, failed, unknown 중 하나'},
                {'key':'direct_cause','question':'실패의 직접 원인. 성공이면 not_applicable, 원인 미확인이면 null, 확인되면 짧게 설명'}]
        world={'evaluation_time':'2026-11-16T15:17:00Z','step_seconds':60,'series':[],'allow_empty_series':True,
               'declared_metrics':[],'containers':['service-db'],'logs':[{'source':'docker','name':'service-db',
               'entries':entries}],'rag':[]}
        scenes.append({'id':ident,'family':family,'split':'test','task_mode':'question','question':question,
                       'answer_fields':fields,'world':world})
        status='failed' if (fault or partial) else 'succeeded'
        cause=('unknown' if partial else 'pg_dump client 16.16 refuses PostgreSQL server 17.12 due to server version mismatch' if fault and backup else
               'psql cannot read /docker-entrypoint-initdb.d/00-eval.sql: Permission denied' if fault else 'not_applicable')
        reference={'required_findings':[{'key':'operation_status','statement':f'The recorded operation {status}.'},
                   {'key':'direct_cause','statement':cause}],
                   'scope':'Only captured isolated operation. No production recovery or universal health claim.',
                   'unobservable':'No evidence of who changed permissions, exact file ownership/mode from tool view, why old client was chosen, or earlier incident history.'}
        if not (fault or partial):reference['scope']+=' '+('Restore check covers row count 3 and sum 60 only.' if backup else 'Fresh PGDATA initialization and marker row count 3, not repairing an existing failed data directory.')
        gold[ident]={'reference':reference,'expected_status':status,'direct_cause':cause,
                     'optional_numeric_facts_not_scored':([] if fault or partial else [{'quantity':'restore marker row count' if backup else 'initialized marker row count','value':3,'unit':'count'}])}
        mapping[ident]={'family':family,'phase':phase,'source_phase_event_ids':selected,
                        'visible_event_ids':(['event-24'] if backup else ['event-51']) if partial else selected,
                        'source':phases[family]['source'],
                        'view_transform':'Actual captured outputs replayed as log collector records; actual embedded timestamps or capture timestamp determine query offsets; command wrapper/alias added; partial control withholds details.',
                        'fidelity':phases[family]['source_fidelity'],
                        'intervention':('PG16 Debian client vs PG17 Alpine client: version AND distribution/image differ.' if backup else phases[family]['intervention'])}
    save(OUT/'dataset.json',{'schema_version':5,'kind':'source-backed isolated capture replay','scenarios':scenes})
    save(OUT/'gold.json',gold);save(OUT/'provenance.json',mapping)
    print('Built 8 views from 2 captured mechanism families. Gold is separate. Not 8 independent incidents.')
if __name__=='__main__':main()
