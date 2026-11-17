#!/usr/bin/env python3
"""Explicit live drill: disposable fault -> recovery -> real resolution service.

Run with --execute. No production service is stopped and no Discord message is sent.
Requires Docker, the local Java 21 image and the existing DB/Ollama containers.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def docker(*args, **kwargs):
    return subprocess.check_output(["docker", *args], text=True, **kwargs).strip()


def inspect(name):
    return json.loads(docker("inspect", name))[0]


def ip(name):
    return next(iter(inspect(name)["NetworkSettings"]["Networks"].values()))["IPAddress"]


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def probe(target):
    query = urllib.parse.urlencode({"module": "http_2xx", "target": target})
    with urllib.request.urlopen("http://localhost:9115/probe?" + query, timeout=12) as response:
        body = response.read().decode()
    success = re.search(r"^probe_success ([01])$", body, re.MULTILINE)
    if not success:
        raise RuntimeError("Blackbox did not return probe_success")
    duration = re.search(r"^probe_duration_seconds ([0-9.e+-]+)$", body, re.MULTILINE)
    return {"success": int(success[1]), "duration": duration[1] if duration else "unknown", "time": now()}


def wait_success(target):
    for _ in range(12):
        result = probe(target)
        if result["success"] == 1:
            return result
        time.sleep(1)
    raise RuntimeError("Fixture did not become healthy")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Opt in to one durable synthetic resolution")
    args = parser.parse_args()
    if not args.execute:
        parser.error("Explicit --execute is required; this writes one synthetic resolution to the real DB")
    drill_id = "resolution-drill-" + uuid.uuid4().hex[:12]
    fixture = "monitoring-" + drill_id
    runner = fixture + "-runner"
    target = "http://" + fixture + ":80/"
    print("DRILL_START " + json.dumps({"id": drill_id, "target": target, "synthetic": True}), flush=True)
    created = False
    try:
        docker("run", "-d", "--name", fixture, "--network", "monitoring-net",
               "--label", "monitoring.synthetic=true", "--memory", "64m", "--cpus", "0.25",
               "--log-opt", "max-size=1m", "--log-opt", "max-file=1", "nginx:alpine")
        created = True
        healthy = wait_success(target)
        docker("stop", "--time", "2", fixture)
        failed = probe(target)
        if failed["success"] != 0:
            raise RuntimeError("No actual outage observed; refusing to write a resolution")
        docker("start", fixture)
        recovered = wait_success(target)
        confirmed = wait_success(target)
        evidence = (f"synthetic=true; drillId={drill_id}; target={target}; "
                    f"healthy=1 at {healthy['time']}; failed=0 at {failed['time']}; "
                    f"action=docker start {fixture}; recovered=1 at {recovered['time']}; "
                    f"recoveryConfirmed=1 at {confirmed['time']}; "
                    f"probeDurationsSeconds={healthy['duration']},{failed['duration']},{recovered['duration']}; "
                    "fixture only; production unchanged")
        print("DRILL_EVIDENCE " + evidence, flush=True)
        app = inspect("monitoring-agent-app")
        env = dict(item.split("=", 1) for item in app["Config"]["Env"] if "=" in item)
        child_env = os.environ.copy()
        child_env.update({
            "DRILL_EXECUTE": "verified-recovery", "DRILL_ID": drill_id,
            "DRILL_EVIDENCE": evidence, "DRILL_FAILURE_TIME": failed["time"],
            "DRILL_DB_URL": "jdbc:postgresql://" + ip("monitoring-agent-db") + ":5432/monitoring_agent",
            "DRILL_DB_USERNAME": env["SPRING_DATASOURCE_USERNAME"],
            "DRILL_DB_PASSWORD": env["SPRING_DATASOURCE_PASSWORD"],
            "DRILL_OLLAMA_URL": "http://" + ip("monitoring-agent-ollama") + ":11434",
        })
        command = ["docker", "run", "--rm", "--name", runner, "--network", "host", "--memory", "2g", "--cpus", "2",
                   "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{ROOT}:/app",
                   "-v", f"{Path.home() / '.gradle'}:/gradle", "-e", "GRADLE_USER_HOME=/gradle", "-w", "/app"]
        for key in child_env:
            if key.startswith("DRILL_"):
                command.extend(["-e", key])
        command.extend(["eclipse-temurin:21-jdk-alpine", "./gradlew", "resolutionDrill", "--no-daemon",
                        "--console=plain", "--max-workers=2", "-Dorg.gradle.jvmargs=-Xmx768m"])
        subprocess.run(command, env=child_env, check=True, timeout=180)
    finally:
        # Killing the Docker client alone does not kill its container.
        try:
            subprocess.run(["docker", "rm", "-f", runner], check=False,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        except subprocess.TimeoutExpired:
            print("DRILL_CLEANUP_WARNING runner cleanup timed out: " + runner, flush=True)
        if created:
            docker("rm", "-f", fixture)
            print("DRILL_CLEANUP removed=" + fixture, flush=True)


if __name__ == "__main__":
    def terminate(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    main()
