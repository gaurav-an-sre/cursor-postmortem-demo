# Cursor Postmortem Demo

This repository is a local-only SRE incident showcase. The checkout service,
load generator, and incident watchdog run with Python on macOS; no Docker,
Prometheus, GCP, or external service is required.

## Local setup

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

Run the healthy service with:

```sh
uvicorn checkout_svc.app:app --host 127.0.0.1 --port 8000
```

## Incident bundle contract

The harness writes `incidents/<incident_id>/` with this stable schema
(`schema_version` is `1`):

* `alert.json` — a Cloud Monitoring-shaped alert payload.
* `metrics.csv` — five-second load windows with `ts`, `rps`, `p50_ms`,
  `p95_ms`, `p99_ms`, `error_rate`, and `rss_mb`.
* `app.log` — JSON request logs covering the alert window.
* `deploy.json` — the most recent deploy commit's SHA, metadata, changed files,
  and unified diff.
* `timeline.json` — ordered deploy, load, breach, alert, error, close, and
  mitigation events.
* `bundle.json` — manifest containing the incident ID, service, environment,
  relative artifact paths, and schema version.

## Run a local incident

After installing the development dependencies, run the complete deterministic
demo:

```sh
make incident
```

The command starts a fresh SQLite database, runs local load and watchdog
processes, restarts the service as mitigation, closes the alert, and prints
the resulting incident bundle path.
