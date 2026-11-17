import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("resolution_drill", Path(__file__).parents[1] / "resolution_drill.py")
drill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drill)


class RunnerCleanupTest(unittest.TestCase):
    def test_timed_out_live_runner_is_named_bounded_and_removed(self):
        result = {"success": 1, "duration": "0.01", "time": "2026-11-03T00:00:00Z"}
        app = {"Config": {"Env": ["SPRING_DATASOURCE_USERNAME=test", "SPRING_DATASOURCE_PASSWORD=secret"]}}

        def execute(command, **kwargs):
            if command[:2] == ["docker", "run"]:
                raise subprocess.TimeoutExpired(command, 180)
            return subprocess.CompletedProcess(command, 0)

        with patch("sys.argv", ["resolution_drill.py", "--execute"]), \
                patch.object(drill, "docker", return_value="fixture") as docker, \
                patch.object(drill, "inspect", return_value=app), \
                patch.object(drill, "ip", return_value="127.0.0.1"), \
                patch.object(drill, "wait_success", return_value=result), \
                patch.object(drill, "probe", return_value={**result, "success": 0}), \
                patch.object(drill.subprocess, "run", side_effect=execute) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.TimeoutExpired):
                drill.main()
        launch = run.call_args_list[0]
        self.assertEqual(launch.kwargs.get("timeout"), 180)
        command = launch.args[0]
        self.assertIn("--name", command)
        runner = command[command.index("--name") + 1]
        self.assertTrue(any(call.args[0] == ["docker", "rm", "-f", runner] for call in run.call_args_list[1:]))
        self.assertTrue(any(call.args[:2] == ("rm", "-f") for call in docker.call_args_list))


if __name__ == "__main__":
    unittest.main()
