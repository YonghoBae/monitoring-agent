# Numeric synthetic evaluation fixtures

`src/test/resources/eval-dataset-v3.yml` retains all 38 v2 scenario IDs, original alerts and playbooks.
All numeric samples are constructed synthetic fixtures, not measurements from a production incident.
The original v2 file and historical scores remain unchanged; v3 scores must be reported separately.

Every scene has an isolated logical clock at `2026-08-15T12:00:00Z`, a 60-second replay step,
numeric Prometheus series with relative-time knots, exact log targets and an explicit running-container
inventory. Replay linearly interpolates numeric samples onto its minute grid. CPU and other counters are
monotonic. Bytes use decimal GB unless a metric explicitly uses MiB; DCGM framebuffer metrics use MiB,
GPU utilization uses percent and temperature uses Celsius. `http_request_duration_seconds` in the network
scenario is a summary quantile series, not a histogram. The label-attribution and client-source gauges
in the storage/security scenes are explicit synthetic diagnostic metrics, not implied exporter defaults.

`expected.required_facts` is the authoritative semantic gold. Each fact cites actual numeric metrics,
reachable Docker logs or an indexed historical RAG document. `verify:status` is the one non-telemetry
reference: a STALE alert may stop immediately without a compulsory metric query. Recommendations,
uncertainty and observations are distinct. There is no compulsory query order or universal root cause.
`validation_probes` are deterministic replay checks, not prescribed agent queries. They must be evaluated
against actual Prometheus; the accompanying Python tests only check the fixture contract.

The current log API selects Docker logs. Host journal records are preserved as synthetic world data but
cannot satisfy required facts: SSH ban state, kernel OOM victim, daemon shutdown and exact NTP failure
remain unknown where only host evidence would establish them. An empty or missing series is distinct
from zero. Redis key purpose, replica state, inference success and Promtail positions-file state remain
unknown. CouchDB's 39 GB size difference is an estimate, not guaranteed reclamation. Websocket recovery
reaches 39 of 41 connections, with precise 67-second timing supplied by timestamped Docker log entries;
minute-resolution series alone cannot establish that duration. PostgreSQL's skipped vacuum is supported
by a lock-error log and is not attributed to write overload.

Read-only evaluation forbids execution events, including both immediately executing and requesting
approval to execute commands. A safe written recommendation may describe future investigation or
remediation without issuing a command. No LLM request or production fault is needed to validate this data.
