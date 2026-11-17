"""Replay every v3 validation probe against isolated real Prometheus worlds.

No LLM or production telemetry is used. Exit nonzero for any broken fixture.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import yaml

from numeric_fixture import FixtureSession


def check_probe(session, probe):
    url = session.prometheus_url + "/api/v1/query?" + urlencode({
        "query": probe["expr"], "time": session.evaluation_time})
    try:
        with urlopen(url, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as exc:
        if probe["expect"] == "error" and exc.code == 400:
            return
        raise
    if payload["status"] != "success":
        raise AssertionError(payload)
    result = payload["data"]["result"]
    if probe["expect"] == "error":
        raise AssertionError("Expected query error")
    if probe["expect"] == "empty":
        if result:
            raise AssertionError(f"Expected empty result: {result}")
        return
    if not result:
        raise AssertionError("Expected nonempty result")
    if "expected_value" in probe:
        if len(result) != 1 or payload["data"]["resultType"] != "vector":
            raise AssertionError(f"Expected one numeric vector value: {result}")
        actual = float(result[0]["value"][1])
        expected = probe["expected_value"]
        if not abs(actual - expected) <= probe.get("tolerance", 1e-6):
            raise AssertionError(f"Expected {expected}, got {actual}")


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "build/eval/dataset-audit.json")
    args = parser.parse_args()
    source = (root / "src/test/resources/eval-dataset-v3.yml").read_bytes()
    dataset = yaml.safe_load(source)
    metadata = {"dataset": "eval-dataset-v3.yml", "sha256": hashlib.sha256(source).hexdigest(),
                "timestamp": datetime.now(timezone.utc).isoformat(), "llm_calls": 0}
    records = []
    for scenario in dataset["scenarios"]:
        record = {"id": scenario["id"], "probes": 0, "failures": []}
        try:
            with FixtureSession(scenario) as session:
                for probe in scenario["validation_probes"]:
                    record["probes"] += 1
                    try:
                        check_probe(session, probe)
                    except Exception as exc:
                        record["failures"].append({"expr": probe["expr"], "error": str(exc)})
        except Exception as exc:
            record["failures"].append({"fixture": str(exc)})
        records.append(record)
        print(json.dumps(record), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({**metadata, "scenarios": records}, indent=2) + "\n")
    failures = sum(bool(r["failures"]) for r in records)
    print(f"Scenarios: {len(records)}, probes: {sum(r['probes'] for r in records)}, failed scenarios: {failures}")
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
