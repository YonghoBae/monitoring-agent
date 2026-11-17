import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from semantic_judge_v51 import validate
class FullQuestionContractTest(unittest.TestCase):
    def setUp(self):
        self.p={'answer':'The backup passed. Restore outcome unknown.','reference':{'required_findings':[{'key':'backup'}]},'observations':[{'id':'o1'}]}
        self.r={'pass':True,'unsupported_claims':False,'complete_answer':True,'answer_correct':True,'answer_status':'answered',
                'findings':[{'key':'backup','satisfied':True,'answer_quote':'The backup passed.','observation_ids':['o1'],'reason':'direct'}],'reason':'complete'}
    def test_missing_unlisted_clause_can_fail_while_listed_fields_pass(self):
        self.r.update(pass_=False)
        self.r['pass']=False;self.r['complete_answer']=False;self.r['answer_correct']=False
        self.assertFalse(validate(self.r,self.p)['pass'])
    def test_wrong_secondary_clause_can_be_complete(self):
        self.r.update(answer_correct=False);self.r['pass']=False
        self.assertTrue(validate(self.r,self.p)['complete_answer'])
    def test_unsupported_extra_does_not_rewrite_requested_correctness(self):
        self.r['unsupported_claims']=True;self.r['pass']=False
        self.assertTrue(validate(self.r,self.p)['answer_correct'])
    def test_correct_cannot_be_incomplete(self):
        self.r['complete_answer']=False;self.r['pass']=False
        with self.assertRaises(ValueError):validate(self.r,self.p)
    def test_empty_and_invented_evidence_rejected(self):
        self.r['findings'][0]['answer_quote']=''
        with self.assertRaises(ValueError):validate(self.r,self.p)
        self.r['findings'][0].update(answer_quote='The backup passed.',observation_ids=['hidden'])
        with self.assertRaises(ValueError):validate(self.r,self.p)
if __name__=='__main__':unittest.main()
