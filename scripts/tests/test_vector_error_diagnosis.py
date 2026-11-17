import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyze_vector_improvement_errors import diagnose


class ErrorDiagnosisTests(unittest.TestCase):
    def test_union_can_supply_a_relevant_document_absent_from_dense_candidates(self):
        query = {'id': 'q', 'source_id': 'source', 'group': 'test_en', 'gold': ['gold']}
        ranks = {m: {'q': order} for m, order in {
            'baseline': ['a', 'b', 'gold'], 'selected_encoder': ['a', 'b', 'gold'],
            'bm25': ['gold', 'b', 'a'], 'selected_pipeline': ['a', 'gold', 'b'],
        }.items()}
        lock = {'reranker': 'test', 'candidate_depth': 2, 'candidate_mode': 'union'}
        row = diagnose(query, ranks, lock)
        self.assertTrue(row['candidate_hit'])
        self.assertEqual(row['bottleneck_for_hit1'], 'ranking_miss')
        lock['candidate_mode'] = 'dense'
        row = diagnose(query, ranks, lock)
        self.assertFalse(row['candidate_hit'])
        self.assertEqual(row['bottleneck_for_hit1'], 'candidate_miss')


if __name__ == '__main__':
    unittest.main()
