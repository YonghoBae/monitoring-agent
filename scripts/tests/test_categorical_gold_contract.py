import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from categorical_gold_contract import assert_categorical_log_support


class CategoricalGoldContractTest(unittest.TestCase):
    def scene(self, label, line, source='docker'):
        return {'id': 'jellyfin', 'gold': [{'key': 'encoding', 'value': label,
                'evidence_targets': ['log:docker:jellyfin']}], 'world': {'logs': [
                    {'source': source, 'name': 'jellyfin', 'entries': [
                        {'offset_seconds': -60, 'line': line}]}]}}

    def test_transcode_codec_does_not_prove_software_encoder(self):
        scene = self.scene('software', 'INFO transcode start: HEVC -> H264')
        with self.assertRaises(AssertionError):
            assert_categorical_log_support(scene)
        scene['gold'][0]['value'] = 'unknown'
        self.assertEqual(assert_categorical_log_support(scene), ['encoding'])

    def test_explicit_encoder_must_be_reachable(self):
        scene = self.scene('software', 'ffmpeg encoder=libx264')
        self.assertEqual(assert_categorical_log_support(scene), ['encoding'])
        hidden = copy.deepcopy(scene)
        hidden['world']['logs'][0]['source'] = 'host'
        with self.assertRaises(AssertionError):
            assert_categorical_log_support(hidden)
        scene['gold'][0]['value'] = 'unknown'
        with self.assertRaises(AssertionError):
            assert_categorical_log_support(scene)
