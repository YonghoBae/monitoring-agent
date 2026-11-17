import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from numeric_fixture import render_openmetrics

class EmptyNumericWorldTest(unittest.TestCase):
    def test_explicit_empty_world_adds_no_fake_metrics(self):
        world={'evaluation_time':'2026-11-16T15:17:00Z','series':[],'allow_empty_series':True}
        rendered,clock=render_openmetrics({'world':world})
        self.assertEqual('# EOF\n',rendered)
        self.assertEqual('2026-11-16T15:17:00Z',clock)
        for flag in [False,'true',1,None]:
            with self.subTest(flag=flag),self.assertRaises(ValueError):
                render_openmetrics({'world':dict(world,allow_empty_series=flag)})
    def test_empty_world_still_checks_clock_and_step(self):
        for overrides in [{'evaluation_time':'bad'},{'step_seconds':0},{'series':None}]:
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):
                render_openmetrics({'world':dict({'evaluation_time':'2026-11-16T15:17:00Z','series':[],'allow_empty_series':True},**overrides)})
if __name__=='__main__':unittest.main()
