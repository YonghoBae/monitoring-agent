import importlib.util
from pathlib import Path
import unittest

import numpy as np
import ir_measures
from ir_measures import nDCG, R, RR, Success

spec = importlib.util.spec_from_file_location("real_eval", Path(__file__).resolve().parents[1] / "eval_real_vector_retrieval.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


class RealRetrievalTests(unittest.TestCase):
    def test_multiple_relevant_documents_match_external_trec_metrics(self):
        order = ["b", "noise", "c", "a"]
        gold = {"a", "b", "c", "missing"}
        actual = ev.metrics(order, gold)
        qrels = [ir_measures.Qrel("q", d, 1) for d in gold]
        run = [ir_measures.ScoredDoc("q", d, 4 - i) for i, d in enumerate(order)]
        measures = {nDCG@10: "nDCG@10", R@5: "Recall@5", R@10: "Recall@10",
                    R@100: "Recall@100", RR@10: "MRR@10", Success@1: "Hit@1", Success@5: "Hit@5"}
        external = ir_measures.calc_aggregate(list(measures), qrels, run)
        for measure, name in measures.items():
            self.assertAlmostEqual(actual[name], external[measure], places=12)
        self.assertEqual(actual["Recall@5"], .75)
        self.assertEqual(actual["Hit@5"], 1.)

    def test_empty_results_have_zero_metrics(self):
        self.assertTrue(all(x == 0 for x in ev.metrics([], {"a"}).values()))

    def test_rank_ties_use_preordered_document_id(self):
        self.assertEqual(ev.ranked(np.array([.5, 1., .5])).tolist(), [1, 0, 2])

    def test_nested_pools_keep_all_gold_and_are_input_order_independent(self):
        docs = [{"_id": str(i)} for i in range(20)]
        gold = {"q": {"2", "17"}}
        def pool(ds, n):
            return {ds[i]["_id"] for i in ev.pool_indices(ds, gold, n)}
        small, large = pool(docs, 5), pool(docs, 10)
        self.assertTrue(gold["q"] <= small < large)
        self.assertEqual(small, pool(list(reversed(docs)), 5))

    def test_bm25_no_match_does_not_add_arbitrary_fusion_votes(self):
        ds = np.array([2, 0, 1])
        bs = np.array([0, 1, 2])
        fused = ev.fuse(ds, bs, np.zeros(3), 3)
        self.assertEqual(fused.tolist(), ds.tolist())

    def test_bm25_term_frequency_and_length_normalization(self):
        model = ev.BM25(["ssh ssh", "ssh unrelated unrelated unrelated unrelated", "dns"])
        scores = model.scores("ssh")
        self.assertGreater(scores[0], scores[1])
        self.assertEqual(scores[2], 0)
        np.testing.assert_array_equal(scores, model.scores("SSH ssh"))


if __name__ == "__main__":
    unittest.main()
