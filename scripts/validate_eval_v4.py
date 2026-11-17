"""Finalize alert status from actual Prometheus expressions across the rule for-window."""
from pathlib import Path
import datetime as dt
import hashlib,json,re
from urllib.parse import urlencode
from urllib.request import urlopen
from numeric_fixture import FixtureSession
from categorical_gold_contract import assert_categorical_log_support

ROOT=Path(__file__).resolve().parents[1]
def query(session,path,params):
    with urlopen(session.prometheus_url+'/api/v1/'+path+'?'+urlencode(params),timeout=15) as r:return json.load(r)['data']['result']
def main():
    folder=ROOT/'eval/v4';data=json.loads((folder/'dataset.draft.json').read_text());checks=[]
    for scene in data['scenarios']:
        categorical_checks=assert_categorical_log_support(scene)
        with FixtureSession(scene) as session:
            rule=scene['operational_rule'];check={'id':scene['id'],'rendered':True,'categorical_log_marker_checks':categorical_checks}
            if rule:
                epoch=dt.datetime.fromisoformat(session.evaluation_time.replace('Z','+00:00')).timestamp()
                duration=int(rule['duration']);expr=rule['query']
                now=query(session,'query',{'query':expr,'time':epoch})
                window=query(session,'query_range',{'query':expr,'start':epoch-duration,'end':epoch,'step':60})
                if now:
                    assert len(now)==1,(scene['id'],'ambiguous target',now)
                    labels=now[0]['metric'];samples=[v for v in window if v['metric']==labels]
                    assert len(samples)==1 and len(samples[0]['values'])==duration//60+1,(scene['id'],'not sustained for full rule window')
                    scene['alert']['labels']=labels
                    scene['world']['verify']={'status':'CONFIRMED','value':float(now[0]['value'][1]),'activeAt':dt.datetime.fromtimestamp(epoch-duration,dt.timezone.utc).isoformat()}
                else:
                    assert scene['id'] in ('cpu_transient_spike','public_probe_recovered'),(scene['id'],'expected real rule condition not met')
                    scene['world']['verify']={'status':'STALE'}
                check.update(expression=expr,for_seconds=duration,instant=now,status=scene['world']['verify']['status'])
                summary=rule['annotations'].get('summary',rule['name'])
                scene['alert']['message']=re.sub(r'\{\{\s*\$labels\.(\w+)\s*\}\}',lambda m:str(scene['alert']['labels'].get(m.group(1),'미제공')),summary)
            # Numeric claims need numeric probes as well; categorical claims need reachable logs.
            for gold in scene['gold']:
                if gold.get('validation_expr'):
                    result=query(session,'query',{'query':gold['validation_expr'],'time':session.evaluation_time})
                    assert len(result)==1,(scene['id'],gold['key'],'ambiguous gold result',result)
                    actual=float(result[0]['value'][1])
                    assert abs(actual-gold['value'])<=gold['tolerance'],(scene['id'],gold['key'],'gold arithmetic mismatch',actual,gold['value'])
                elif gold.get('validation_log_substring'):
                    assert any(gold['validation_log_substring'] in e['line'] for l in scene['world']['logs'] for e in l['entries']),(scene['id'],gold['key'],'gold log absent')
                elif isinstance(gold['value'],(int,float)):
                    raise AssertionError((scene['id'],gold['key'],'numeric gold has no validation'))
                for ref in gold['evidence_targets']:
                    if ref.startswith('log:docker:'):
                        name=ref.removeprefix('log:docker:')
                        assert any(e['offset_seconds']>=-1800 for l in scene['world']['logs'] if l['source']=='docker' and l['name']==name for e in l['entries']),(scene['id'],ref)
                    elif ref=='docker_inventory':
                        assert 'containers' in scene['world']
                    elif ref=='docker_inspect':
                        assert scene['world'].get('container_details')
                    elif ref!='verify_alert':
                        assert query(session,'query',{'query':ref,'time':session.evaluation_time}),(scene['id'],ref)
            checks.append(check);print(scene['id'],'validated',flush=True)
    data['validation']={'kind':'actual_prometheus_expression_and_continuous_60s_for_window_with_categorical_log_marker_checks','independent_human_review':False,'categorical_scope':'necessary explicit log markers, not complete semantic validation'}
    raw=json.dumps(data,ensure_ascii=False,indent=2)+'\n';(folder/'dataset.json').write_text(raw)
    (folder/'validation.json').write_text(json.dumps({'sha256':hashlib.sha256(raw.encode()).hexdigest(),'checks':checks},ensure_ascii=False,indent=2)+'\n')
    print('VALIDATED',len(checks))
if __name__=='__main__':main()
