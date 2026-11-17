import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_vector_duplicate_links import components, same_component


class DuplicateLinkTests(unittest.TestCase):
    def test_unjudged_sibling_can_share_a_known_canonical_question(self):
        graph = components([('question', 'canonical'), ('sibling', 'canonical'), ('other', 'different')])
        self.assertTrue(same_component('question', 'sibling', graph))
        self.assertFalse(same_component('question', 'other', graph))
        self.assertFalse(same_component('missing', 'also-missing', graph))
        # This flag supplements the gold list; it does not silently expand it.
        self.assertNotIn('sibling', ['canonical'])


if __name__ == '__main__':
    unittest.main()
