import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from summarize_reviewed_comparison import completion, summarize


class ReviewSummaryTest(unittest.TestCase):
    def test_returned_values_do_not_erase_timeout(self):
        self.assertEqual(completion({'answer': '조사 시간 한도 도달. 현재=92', 'error': ''}), 'timeout')
        self.assertEqual(completion({'answer': '', 'error': 'TimeoutException'}), 'timeout')
        self.assertEqual(completion({'answer': '현재 상태 확인 불가: metric=92', 'error': ''}), 'generic_fallback')
        self.assertEqual(completion({'answer': '거부됨: 허가되지 않은 명령어입니다.', 'error': ''}), 'tool_policy_denial')

    def test_correct_fields_and_normal_completion_are_separate(self):
        row = dict(id='case', arm='production', rep=0, answer='조사 시간 한도 도달. 현재=92',
                   error='', elapsedMs=90000, trace={'observations': []})
        scored = dict(id='case', arm='production', rep=0, score=100,
                      schema_valid=False, unsupported_claims=[], checks=[{'correct_value': True}])
        contract = dict(scored, score=0)
        scenes = {'case': {'task_mode': 'alert', 'provenance': {'kind': 'controlled'}}}
        result = summarize([row], {'rows': [scored]}, {'rows': [contract]}, scenes)['summary']['production']
        self.assertEqual(result['evidence_reviewed_field_score'], 100)
        self.assertEqual(result['output_contract_score'], 0)
        self.assertEqual(result['all_requested_fields_grounded_no_flag_normal_return_count'], 0)
        self.assertEqual(result['completion_counts'], {'timeout': 1})
