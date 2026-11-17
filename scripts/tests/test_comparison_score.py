import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_harness_comparison import score

class ComparisonScoreTest(unittest.TestCase):
    def test_guessed_correct_value_without_observation_is_not_grounded(self):
        row={'id':'x','arm':'pi','rep':0,'error':'','answer':'{"facts":{"cpu":92}}','trace':{'observations':[]},'elapsedMs':1}
        scene={'gold':[{'key':'cpu','value':92,'tolerance':.1,'evidence_targets':['node_cpu_seconds_total']}]}
        self.assertEqual(score(row,scene)['score'],0)
        row['trace']['observations']=[{'source':'prometheus','target':'node_cpu_seconds_total','status':'empty','data':[]}]
        self.assertEqual(score(row,scene)['score'],0)
        row['trace']['observations'][0].update(status='ok',data={'value':92})
        self.assertEqual(score(row,scene)['score'],100)
        row['answer']='{"facts":{"cpu":0.92}}'
        self.assertEqual(score(row,scene)['score'],0)
    def test_unavailable_is_evidence_of_uncertainty_not_health(self):
        row={'id':'x','arm':'pi','rep':0,'error':'','answer':'{"facts":{"empty":"unknown"}}','trace':{'observations':[{'source':'docker_inventory','target':'containers','status':'unavailable','data':'API unavailable'}]},'elapsedMs':1}
        scene={'gold':[{'key':'empty','value':'unknown','tolerance':0,'evidence_targets':['docker_inventory']}]}
        self.assertEqual(score(row,scene)['score'],100)
        scene['gold'][0]['value']='yes';row['answer']='{"facts":{"empty":"yes"}}'
        self.assertEqual(score(row,scene)['score'],0)
    def test_wrong_metric_suffix_and_partial_causal_evidence_do_not_pass(self):
        row={'id':'x','arm':'pi','rep':0,'error':'','answer':'{"facts":{"cpu":92}}','trace':{'observations':[{'source':'prometheus','target':'node_cpu_seconds_total_wrong','status':'ok','data':[92]}]},'elapsedMs':1}
        scene={'gold':[{'key':'cpu','value':92,'tolerance':.1,'evidence_targets':['node_cpu_seconds_total']}]}
        self.assertEqual(score(row,scene)['score'],0)
        row['trace']['observations'][0]['target']='rate(node_cpu_seconds_total{mode="idle"}[5m])'
        scene['gold'][0].update(evidence_targets=['node_cpu_seconds_total','docker_inspect'],evidence_all=True)
        self.assertEqual(score(row,scene)['score'],0)
