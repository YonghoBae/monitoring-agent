import copy
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import eval_vector_retrieval as ev

class RetrievalMeasuresTest(unittest.TestCase):
    def test_known_relevant_rank_and_cutoff(self):
        ranking=[{"id":str(i)} for i in range(1,7)]
        third=ev.measures(ranking,{"3":1})
        self.assertEqual(third["recall_at_3"],1)
        self.assertEqual(third["mrr_at_5"],1/3)
        self.assertEqual(third["ndcg_at_5"],.5)
        self.assertEqual(third["hit_at_1"],0)
        sixth=ev.measures(ranking,{"6":1})
        self.assertEqual(sixth["relevant_rank"],6)
        self.assertEqual(sixth["recall_at_5"],0)
        self.assertEqual(sixth["ndcg_at_5"],0)
    def test_absent_and_duplicate_are_not_silent_credit(self):
        self.assertEqual(ev.measures([{"id":"x"}],{"missing":1})["mrr_at_5"],0)
        with self.assertRaises(ValueError):ev.measures([{"id":"x"},{"id":"x"}],{"x":1})
        with self.assertRaises(ValueError):ev.measures([], {})
    def test_bm25_discriminates_terms_and_ties_stably(self):
        docs=[{"id":"z","text":"disk disk error"},{"id":"a","text":"certificate renewal"}]
        self.assertEqual(ev.bm25("disk",docs)[0]["id"],"z")
        self.assertEqual([r["id"] for r in ev.bm25("unknown",docs)],["a","z"])
    def test_korean_partial_word_matching_is_explicit(self):
        docs=[{"id":"memory","text":"메모리 부족"},{"id":"certificate","text":"인증서 만료"}]
        self.assertEqual(ev.bm25("메모리가",docs)[0]["id"],"memory")
        self.assertIn("ko:메모",ev.tokens("메모리가"))
    def test_rrf_known_rank_sum_and_duplicate_rejection(self):
        a=[{"id":"a"},{"id":"b"}];b=[{"id":"b"},{"id":"c"}]
        result=ev.fuse([a,b]);self.assertEqual(result[0]["id"],"b")
        self.assertAlmostEqual(result[0]["score"],1/62+1/61)
        with self.assertRaises(ValueError):ev.fuse([[{"id":"x"},{"id":"x"}]])
    def test_cosine_handles_nonunit_vectors(self):
        self.assertEqual(ev.cosine([2,0],[3,0]),1)
        self.assertEqual(ev.cosine([2,0],[0,3]),0)
        self.assertEqual(ev.cosine([2,0],[-3,0]),-1)
    def test_dataset_contract_and_wrong_type_labels(self):
        data=ev.read(ev.BASE/"dataset.json");self.assertTrue(ev.validate_dataset(data))
        bad=copy.deepcopy(data);q=bad["queries"][0];bad["qrels"][q["id"]]={"alert-"+q["family"]:1}
        with self.assertRaises(ValueError):ev.validate_dataset(bad)
        bad=copy.deepcopy(data);bad["corpus"][0]["text"]+=" changed"
        with self.assertRaises(ValueError):ev.validate_dataset(bad)
    def test_postgres_multiline_json_stream(self):
        text='  {"rows": [{"id":"a"},\n {"id":"b"}]}\n{"rows": []}\n'
        self.assertEqual(ev.decode_json_stream(text),[{"rows":[{"id":"a"},{"id":"b"}]},{"rows":[]}])
        with self.assertRaises(ValueError):ev.decode_json_stream('{"rows": [')
    def test_sql_text_is_escaped_without_shell_interpolation(self):
        self.assertEqual(ev.sql_string("it's a test"),"'it''s a test'")

if __name__=="__main__":unittest.main()
