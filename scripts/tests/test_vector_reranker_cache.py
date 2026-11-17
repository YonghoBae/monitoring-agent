import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import eval_cached_vector_reranker as cache


class FakeModel:
    calls = 0

    def __init__(self, alias, precision):
        self.alias = alias

    def rerank(self, queries, documents):
        FakeModel.calls += len(queries)
        offset = 1 if self.alias == 'bge-reranker' else 2
        return np.array([offset + .01 * len(q) + .001 * len(d) for q, d in zip(queries, documents)], dtype=np.float32)

    def close(self):
        pass


class PairCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'cache').mkdir()
        (self.root / 'model-sources.json').write_text(json.dumps([
            {'model_id': cache.MODELS[name], 'revision': name} for name in ['bge-reranker', 'qwen-reranker']]))
        self.patches = [patch.object(cache, 'BASE', self.root), patch.object(cache, 'Candidate', FakeModel),
                        patch.object(cache, 'profile', return_value={'selected': {'precision': 'float32', 'batch_size': 2}})]
        for p in self.patches:
            p.start()
        FakeModel.calls = 0

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_same_pair_reuses_score_but_other_model_and_fresh_latency_do_not(self):
        model = cache.CachedReranker('bge-reranker')
        first, a = model.score('query', ['document'])
        second, b = model.score('query', ['document'])
        self.assertEqual(first, second)
        self.assertEqual((a['new_pairs'], b['cached_pairs'], FakeModel.calls), (1, 1, 1))
        _, fresh = model.score('query', ['document'], use_cache=False)
        self.assertEqual((fresh['new_pairs'], fresh['cached_pairs'], FakeModel.calls), (1, 0, 2))
        model.close()
        other = cache.CachedReranker('qwen-reranker')
        different, c = other.score('query', ['document'])
        self.assertNotEqual(first, different)
        self.assertEqual(c['cached_pairs'], 0)
        other.close()

    def test_query_document_boundaries_cannot_collide(self):
        model = cache.CachedReranker('bge-reranker')
        first, _ = model.score('a\0b', ['c'])
        second, status = model.score('a', ['b\0c'])
        self.assertNotEqual(first, second)
        self.assertEqual(status['cached_pairs'], 0)
        model.close()


if __name__ == '__main__':
    unittest.main()
