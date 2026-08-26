# Cursor Postmortem Demo

This repository is a local-only SRE incident showcase. The checkout service,
load generator, and incident watchdog run with Python on macOS; no Docker,
Prometheus, GCP, or external service is required.

The showcase has two halves: **Notion is the surface and the context, Cursor is
the agent engine**. The first half creates an observable local incident and
freezes the evidence. The second half gives a Cursor SDK agent read-only tools
for that evidence, produces a structured RCA, and renders a postmortem for
Notion.

## Local setup

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

The optional Notion publisher uses `NOTION_TOKEN` and
`NOTION_PARENT_PAGE_ID`. A live Cursor run additionally requires
`CURSOR_API_KEY`; without those credentials the commands remain local.

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

The default run uses 20 requests per second for up to 80 seconds. The
thresholds are deterministic, so the cache regression should produce a
visible latency/error transition on a laptop:

```text
INCIDENT_RPS=20 INCIDENT_DURATION=80 make incident
```

Latency is expected to cross the warning threshold before the pricing budget
starts returning errors. `rss_mb` is current process RSS, so the mitigation
restart is visible as a drop rather than a high-water mark.

## Run the postmortem agent

After `make incident`, run the offline fixture-backed demo:

```sh
python -m postmortem_agent --bundle incidents/<incident_id> \
  --mock-agent --dry-run
```

With `CURSOR_API_KEY` set, omit `--mock-agent` to use the Cursor SDK. The
default is a Notion dry run whenever `NOTION_TOKEN` is absent:

```sh
python -m postmortem_agent --bundle incidents/<incident_id>
```

One local Cursor `Agent` represents one incident thread. The RCA, remediation,
and narrative are three sequential `Run`s on that same agent, so the
conversation state carries across the workflow. The accepted RCA is frozen to
`rca.json`; the rendered document uses that persisted JSON rather than
recomputing incident numbers.

The agent receives only three custom tools backed by the selected bundle:
`query_metrics`, `search_logs`, and `get_deploy_diff`. Complete SDK event
streams are written as JSONL under `out/<incident_id>/`, while assistant text,
thinking, tool calls, status, and usage are shown in the terminal. Remediation
runs for SEV1 and SEV2 create `postmortem/<incident_id>`; SEV3 is advisory-only
and skips that run. Use `--no-remediation` to skip it explicitly.

Incident evidence is immutable. `.cursor/hooks.json` installs a pre-tool-use
hook that denies write, edit, delete, and shell targets under `incidents/` and
`examples/incidents/`.

## Example evidence

`examples/incidents/inc-example/` is a committed bundle produced by a real
local run. Generated bundles under `incidents/` remain ignored so repeated
demos do not dirty git.
