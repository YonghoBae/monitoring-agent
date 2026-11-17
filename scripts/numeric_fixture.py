"""Run a private real Prometheus over explicit, numeric scenario time series.

No production endpoint is contacted. Docker must already have the pinned image.
The stdio protocol owns the session until close, EOF, or process termination.
"""
import argparse
import bisect
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import uuid

IMAGE = "prom/prometheus:v2.53.0"
METRIC = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*\Z")
LABEL = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*\Z")
MAX_SPAN_SECONDS = 7 * 24 * 3600
MAX_SAMPLES = 1_000_000


def _number(value, description):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(description + " must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(description + " must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(description + " must be a finite number")
    return result


def render_openmetrics(scenario):
    """Validate all inputs and expand linear knots without extrapolation.

    Each series retains every supplied knot and adds samples at step intervals
    from its first knot. Metric names are written exactly as provided, including
    counter suffixes; no TYPE hints perform implicit metric-name rewriting.
    """
    if not isinstance(scenario, dict) or not isinstance(scenario.get("world"), dict):
        raise ValueError("scenario.world must be an object")
    world = scenario["world"]
    when = world.get("evaluation_time")
    if not isinstance(when, str):
        raise ValueError("world.evaluation_time must be an ISO timestamp")
    try:
        clock = datetime.fromisoformat(when.replace("Z", "+00:00"))
        if clock.tzinfo is None or clock.utcoffset() is None:
            raise ValueError("timezone required")
        epoch = clock.timestamp()
    except (ValueError, OverflowError) as exc:
        raise ValueError("world.evaluation_time must be an ISO timestamp with timezone") from exc
    step = _number(world.get("step_seconds", 60), "world.step_seconds")
    if step <= 0:
        raise ValueError("world.step_seconds must be positive")
    series = world.get("series")
    if not isinstance(series, list) or (not series and world.get("allow_empty_series") is not True):
        raise ValueError("world.series must be a nonempty list, unless allow_empty_series=true for an explicitly log-only world")
    identities = set()
    output = []
    earliest, latest = math.inf, -math.inf
    for item in series:
        if not isinstance(item, dict):
            raise ValueError("each series must be an object")
        name, labels, samples = item.get("metric"), item.get("labels", {}), item.get("samples")
        if not isinstance(name, str) or not METRIC.fullmatch(name):
            raise ValueError("invalid metric name")
        if not isinstance(labels, dict) or any(
            not isinstance(k, str) or not LABEL.fullmatch(k) or k == "__name__"
            or not isinstance(v, str) for k, v in labels.items()
        ):
            raise ValueError("labels must contain valid label names and string values, without __name__")
        identity = (name, tuple(sorted(labels.items())))
        if identity in identities:
            raise ValueError("duplicate series")
        identities.add(identity)
        if not isinstance(samples, list) or not samples:
            raise ValueError("series.samples must be a nonempty list")
        knots = {}
        for sample in samples:
            if not isinstance(sample, (list, tuple)) or len(sample) != 2:
                raise ValueError("samples must be [offset_seconds, value] pairs")
            offset = _number(sample[0], "sample offset")
            value = _number(sample[1], "sample value")
            if offset in knots:
                raise ValueError("duplicate sample timestamp")
            # TSDB stores millisecond timestamps. Reject sub-ms collisions instead
            # of silently dropping user observations during import.
            if not math.isfinite(epoch + offset):
                raise ValueError("sample timestamp out of range")
            knots[offset] = value
        offsets = sorted(knots)
        earliest, latest = min(earliest, offsets[0]), max(latest, offsets[-1])
        if latest - earliest > MAX_SPAN_SECONDS:
            raise ValueError("world series may cover at most seven days")
        expansion_size = (offsets[-1] - offsets[0]) / step
        if not math.isfinite(expansion_size) or expansion_size > MAX_SAMPLES:
            raise ValueError("fixture exceeds sample limit")
        count = int(expansion_size)
        if count + len(knots) + len(output) > MAX_SAMPLES:
            raise ValueError("fixture exceeds sample limit")
        expanded = set(offsets)
        expanded.update(offsets[0] + i * step for i in range(count + 1))
        rendered_labels = ",".join(k + '="' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
                                   for k, v in sorted(labels.items()))
        selector = name + ("{" + rendered_labels + "}" if labels else "")
        prior_ms = None
        for offset in sorted(expanded):
            timestamp = epoch + offset
            millis = round(timestamp * 1000)
            if millis == prior_ms:
                raise ValueError("sample timestamps must be distinct at millisecond precision")
            prior_ms = millis
            if offset in knots:
                value = knots[offset]
            else:
                right = bisect.bisect_right(offsets, offset)
                left_offset, right_offset = offsets[right - 1], offsets[right]
                fraction = (offset - left_offset) / (right_offset - left_offset)
                value = knots[left_offset] * (1 - fraction) + knots[right_offset] * fraction
            output.append(f"{selector} {value:.17g} {millis / 1000:.3f}\n")
    return "".join(output) + "# EOF\n", clock.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _docker(*args, timeout=120):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("docker " + args[0] + " failed: " + result.stderr.strip()[-3000:])
    return result.stdout.strip()


class FixtureSession:
    """Own exactly one temporary fixture container and its imported TSDB."""
    def __init__(self, scenario):
        self.openmetrics, self.evaluation_time = render_openmetrics(scenario)
        self.prometheus_url = None
        self.container_name = "monitoring-numeric-fixture-" + uuid.uuid4().hex
        self._temporary = None
        self._started = False
        self._import_started = False

    def __enter__(self):
        if self._temporary is not None:
            raise RuntimeError("fixture session already open")
        self._temporary = tempfile.TemporaryDirectory(prefix="monitoring-numeric-fixture-")
        try:
            root = Path(self._temporary.name)
            (root / "data").mkdir()
            (root / "samples.om").write_text(self.openmetrics, encoding="utf-8")
            (root / "prometheus.yml").write_text("global:\n  scrape_interval: 60s\nscrape_configs: []\n", encoding="utf-8")
            uid = f"{os.getuid()}:{os.getgid()}"
            common = ["--pull=never", "--user", uid, "--cap-drop=ALL", "--security-opt=no-new-privileges",
                      "--memory=512m", "--cpus=1", "--pids-limit=128"]
            if self.openmetrics != "# EOF\n":
                self._import_started = True
                _docker("run", "--rm", "--name", self.container_name + "-import", "--network=none", *common,
                        "-v", str(root / "samples.om") + ":/fixture/samples.om:ro",
                        "-v", str(root / "data") + ":/fixture/data", "--entrypoint=/bin/promtool", IMAGE,
                        "tsdb", "create-blocks-from", "openmetrics", "/fixture/samples.om", "/fixture/data")
                self._import_started = False
            # Mark ownership before launch so interrupted or failed runs also
            # remove a container Docker may already have created.
            self._started = True
            _docker("run", "-d", "--name", self.container_name, *common,
                    "--label", "monitoring-agent.numeric-fixture=true",
                    "-p", "127.0.0.1::9090", "-v", str(root / "data") + ":/prometheus",
                    "-v", str(root / "prometheus.yml") + ":/etc/prometheus/prometheus.yml:ro", IMAGE,
                    "--config.file=/etc/prometheus/prometheus.yml", "--storage.tsdb.path=/prometheus",
                    "--storage.tsdb.retention.time=3650d", "--web.listen-address=0.0.0.0:9090")
            ports = json.loads(_docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", self.container_name))
            binding = ports["9090/tcp"][0]
            if binding["HostIp"] != "127.0.0.1":
                raise RuntimeError("fixture must bind only to loopback")
            self.prometheus_url = "http://127.0.0.1:" + binding["HostPort"]
            deadline = time.monotonic() + 30
            while True:
                try:
                    with urlopen(self.prometheus_url + "/-/ready", timeout=1) as response:
                        if response.status == 200:
                            return self
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("fixture Prometheus failed readiness: " + _docker("logs", self.container_name)[-2000:])
                time.sleep(0.1)
        except BaseException:
            self.close()
            raise

    def close(self):
        try:
            for flag, name in [("_started", self.container_name),
                               ("_import_started", self.container_name + "-import")]:
                if getattr(self, flag):
                    try:
                        _docker("rm", "-f", name, timeout=20)
                    except RuntimeError as exc:
                        if "No such container" not in str(exc):
                            raise
                    setattr(self, flag, False)
        finally:
            if self._temporary is not None:
                self._temporary.cleanup()
                self._temporary = None

    def __exit__(self, *_):
        self.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdio", action="store_true", required=True)
    parser.parse_args()

    def terminate(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        line = sys.stdin.readline()
        request = json.loads(line)
        if request.get("action") != "open":
            raise ValueError("first request must have action=open")
        with FixtureSession(request["scenario"]) as fixture:
            print(json.dumps({"status": "ready", "prometheus_url": fixture.prometheus_url,
                              "evaluation_time": fixture.evaluation_time}), flush=True)
            for line in sys.stdin:
                request = json.loads(line)
                if request.get("action") != "close":
                    raise ValueError("expected action=close")
                break
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), flush=True)
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
