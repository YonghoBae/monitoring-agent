import hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apply_answer_review import apply,validate_normalization
from review_harness_answers import exclude_invalid_gold,validate_evidence_override

class AnswerReviewTest(unittest.TestCase):
    def test_empty_query_supports_no_verification_but_not_healthy_state(self):
        obs={'o':{'status':'empty','data':[]}}
        evidence={'supported':True,'observation_ids':['o'],'scope':'absence_of_verification'}
        validate_evidence_override('no',evidence,obs)
        with self.assertRaises(AssertionError):validate_evidence_override('healthy',evidence,obs)
        with self.assertRaises(AssertionError):validate_evidence_override('no',dict(evidence,scope=''),obs)
    def test_invalid_gold_exclusion_is_case_wide_and_keeps_valid_fields(self):
        scene={'id':'x','gold':[{'key':'cores'},{'key':'encoding'}]}
        scored,excluded=exclude_invalid_gold(scene,{'x':{'encoding':'No encoder appears in logs'}})
        self.assertEqual(scored['gold'],[{'key':'cores'}])
        self.assertEqual(len(scene['gold']),2)
        self.assertEqual(set(excluded),{'encoding'})
        with self.assertRaises(AssertionError):exclude_invalid_gold(scene,{'x':{'cores':'a','encoding':'b'}})
        with self.assertRaises(AssertionError):exclude_invalid_gold(scene,{'x':{'absent':'a'}})
    def test_explicit_same_quantity_units_are_checked_but_rate_is_not_a_count(self):
        item={'value':7.45*2**30/1e9,'quote':'available: 7.45 GiB','normalization':{'from':'GiB','to':'GB','value':7.45}}
        validate_normalization(item)
        item['value']=7.45
        with self.assertRaises(AssertionError):validate_normalization(item)
        item['normalization']={'from':'per_second','to':'count','value':.0044}
        with self.assertRaises(KeyError):validate_normalization(item)
    def test_quotes_and_observation_ids_must_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            run=Path(temp);answer='CPU usage is 18%.'
            row={'id':'x','arm':'pi','rep':0,'answer':answer,'trace':{'observations':[{'id':'obs-1','source':'verify_alert','status':'ok','data':'CONFIRMED'}]}}
            (run/'results.jsonl').write_text(json.dumps(row)+'\n')
            entry={'id':'x','arm':'pi','rep':0,'answer_sha256':hashlib.sha256(answer.encode()).hexdigest(),'fields':{'cpu':{'value':None,'quote':'','method':'pending_prose_review'}},'causal_claims_reviewed':False}
            (run/'answer-review.json').write_text(json.dumps({'rows':[entry]}))
            annotation={'id':'x','arm':'pi','fields':{'cpu':{'value':18,'quote':'CPU usage is 92%.'}}}
            with self.assertRaises(AssertionError):apply(run,[annotation])
            annotation['fields']['cpu']['quote']='CPU usage is 18%.'
            annotation['evidence_overrides']={'cpu':{'supported':True,'observation_ids':['invented'],'reason':'invalid'}}
            with self.assertRaises(AssertionError):apply(run,[annotation])
            annotation['evidence_overrides']['cpu']['observation_ids']=['obs-1']
            self.assertEqual(apply(run,[annotation])['reviewed'],1)
            row['answer']='Changed answer';(run/'results.jsonl').write_text(json.dumps(row)+'\n')
            with self.assertRaises(AssertionError):apply(run,[annotation])
