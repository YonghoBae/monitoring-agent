import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval_recent_vector_control import body_text


class RecentSourceTextTests(unittest.TestCase):
    def test_source_code_and_error_text_survive_html_extraction(self):
        body = '<p>Permission denied &amp; retry</p><pre><code>if x &lt; 3:\n  print("a &gt; b")\n</code></pre><p>next</p>'
        actual = body_text(body)
        self.assertIn('Permission denied & retry', actual)
        self.assertIn('if x < 3:\n  print("a > b")', actual)
        self.assertLess(actual.index('Permission denied'), actual.index('if x'))
        self.assertLess(actual.index('if x'), actual.index('next'))
        self.assertNotIn('<code>', actual)


if __name__ == '__main__':
    unittest.main()
