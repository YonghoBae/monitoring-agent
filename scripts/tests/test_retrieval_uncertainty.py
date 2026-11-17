import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retrieval_uncertainty import relevance_clusters, paired_cluster_interval


class RetrievalUncertaintyTests(unittest.TestCase):
    def test_translations_and_shared_targets_form_one_cluster(self):
        qs = [{'id': 'a', 'source_id': 'original-a', 'gold': ['d1']},
              {'id': 'a-ko', 'source_id': 'original-a', 'gold': ['d1']},
              {'id': 'b', 'source_id': 'original-b', 'gold': ['d1', 'd2']},
              {'id': 'c', 'source_id': 'original-c', 'gold': ['d2']},
              {'id': 'z', 'source_id': 'original-z', 'gold': ['d3']}]
        c = relevance_clusters(qs)
        self.assertEqual(len({c[q] for q in ['a', 'a-ko', 'b', 'c']}), 1)
        self.assertNotEqual(c['a'], c['z'])

    def test_repeating_one_topic_does_not_create_independent_evidence(self):
        deltas = {str(i): .5 for i in range(100)}
        deltas['negative'] = -.5
        clusters = {str(i): 'same-topic' for i in range(100)}
        clusters['negative'] = 'different-topic'
        result = paired_cluster_interval(deltas, clusters)
        self.assertEqual(result['clusters'], 2)
        self.assertAlmostEqual(result['mean'], 49.5 / 101)
        self.assertEqual(result['ci95'], [-.5, .5])


if __name__ == '__main__':
    unittest.main()
