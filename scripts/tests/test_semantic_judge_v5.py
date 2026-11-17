import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from semantic_judge_v5 import validate

class SemanticContractTest(unittest.TestCase):
    def setUp(self):
        self.p={'answer':'원인을 확인할 수 없습니다.','reference':{'required_findings':[{'key':'cause'}]},'observations':[]}
        self.r={'pass':True,'unsupported_claims':False,'answer_status':'explicit_unknown','findings':[{'key':'cause','satisfied':True,'answer_quote':self.p['answer'],'observation_ids':[],'reason':'Evidence absent'}],'reason':'Unknown warranted'}
    def test_explicit_unknown_without_observation_is_valid(self):
        self.assertTrue(validate(self.r,self.p)['pass'])
    def test_empty_quote_cannot_ground_satisfied_finding(self):
        self.r['findings'][0]['answer_quote']=''
        with self.assertRaises(ValueError):validate(self.r,self.p)
    def test_unanswered_cannot_satisfy(self):
        self.r['answer_status']='unanswered'
        with self.assertRaises(ValueError):validate(self.r,self.p)
    def test_empty_answer_is_fixed(self):
        self.p['answer']='';self.r['pass']=False;self.r['answer_status']='unanswered';self.r['findings'][0].update(satisfied=False,answer_quote='')
        self.assertFalse(validate(self.r,self.p)['pass'])
        self.r['unsupported_claims']=True
        with self.assertRaises(ValueError):validate(self.r,self.p)
    def test_invented_observation_and_quote_rejected(self):
        self.r['findings'][0]['observation_ids']=['invented']
        with self.assertRaises(ValueError):validate(self.r,self.p)
        self.r['findings'][0].update(observation_ids=[],answer_quote='invented')
        with self.assertRaises(ValueError):validate(self.r,self.p)

if __name__=='__main__':unittest.main()
