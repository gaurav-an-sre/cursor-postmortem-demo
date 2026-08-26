"""Evaluate local load metrics and assemble an incident bundle."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import signal
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WINDOW_SECONDS = 5


def sustained_breach(
    rows: list[dict[str, str]], field: str, threshold: float, duration_s: float = 30
) -> tuple[bool, float | None, float | None]:
    """Return whether the latest consecutive breach lasted for duration_s."""
    breaches = [float(row[field]) > threshold for row in rows]
    if not breaches or not breaches[-1]:
        return False, None, None
    end = len(rows) - 1
    start = end
    while start > 0 and breaches[start - 1]:
        start -= 1
    elapsed = float(rows[end]["ts"]) - float(rows[start]["ts"])
    if elapsed < duration_s:
        return False, float(rows[start]["ts"]), float(rows[end][field])
    return True, float(rows[start]["ts"]), float(rows[end][field])


def evaluate_warning(rows: list[dict[str, str]]) -> dict[str, Any] | None:
    """Return the sustained latency warning, if any."""
    fired, started, observed = sustained_breach(rows, "p99_ms", 150, duration_s=20)
    if not fired:
        return None
    return {
        "condition_name": "Checkout p99 latency > 150ms for 20s",
        "breach_started_at": started,
        "observed_value": observed,
        "paged": False,
    }


def evaluate_rules(rows: list[dict[str, str]]) -> dict[str, Any] | None:
    """Return the CRIT rule, including any preceding warning."""
    warning = evaluate_warning(rows)
    fired, started, observed = sustained_breach(rows, "error_rate", 0.05, duration_s=20)
    if not fired:
        return None
    return {
        "severity": "CRIT",
        "condition_name": "Checkout error rate > 5% for 20s",
        "threshold": 0.05,
        "field": "error_rate",
        "breach_started_at": started,
        "observed_value": observed,
        "preceding_warnings": [warning] if warning else [],
    }


def iso_timestamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


def read_rows(metrics_path: Path) -> list[dict[str, str]]:
    if not metrics_path.exists():
        return []
    with metrics_path.open(newline="", encoding="utf-8") as metrics_file:
        return list(csv.DictReader(metrics_file))


def latest_deploy(repo: Path, deploy_path: Path = Path("checkout_svc")) -> dict[str, Any]:
    deploy_path = Path(deploy_path)
    sha = subprocess.check_output(
        ["git", "log", "-1", "--format=%H", "--", str(deploy_path)], cwd=repo, text=True
    ).strip()
    metadata = (
        subprocess.check_output(
            ["git", "show", "-s", "--format=%an%x00%cI%x00%s", sha], cwd=repo, text=True
        )
        .rstrip("\n")
        .split("\x00")
    )
    files = subprocess.check_output(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha], cwd=repo, text=True
    ).splitlines()
    diff = subprocess.check_output(["git", "show", "--format=", sha], cwd=repo, text=True)
    return {
        "sha": sha,
        "author": metadata[0],
        "committed_at": metadata[1],
        "subject": metadata[2],
        "files_changed": files,
        "diff": diff,
    }


def copy_log(log_path: Path, destination: Path, started_at: float, ended_at: float) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as output:
        if not log_path.exists():
            return
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                timestamp = float(json.loads(line)["ts"])
            except (KeyError, ValueError, json.JSONDecodeError):
                continue
            if started_at <= timestamp <= ended_at:
                output.write(line + "\n")


def assemble_bundle(
    bundle_root: Path,
    incident_id: str,
    alert: dict[str, Any],
    metrics_path: Path,
    log_path: Path,
    repo: Path,
    timeline: list[dict[str, str]],
    deploy_path: Path = Path("checkout_svc"),
) -> Path:
    bundle_dir = bundle_root / incident_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "alert.json").write_text(json.dumps(alert, indent=2) + "\n", encoding="utf-8")
    metrics_destination = bundle_dir / "metrics.csv"
    metrics_destination.write_text(metrics_path.read_text(encoding="utf-8"), encoding="utf-8")
    copy_log(
        log_path,
        bundle_dir / "app.log",
        _parse_timestamp(alert["started_at"]) - 120,
        _parse_timestamp(alert["ended_at"]) + 60,
    )
    (bundle_dir / "deploy.json").write_text(
        json.dumps(latest_deploy(repo, deploy_path), indent=2) + "\n", encoding="utf-8"
    )
    (bundle_dir / "timeline.json").write_text(
        json.dumps(timeline, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "incident_id": incident_id,
        "service": "checkout_svc",
        "environment": "local",
        "schema_version": 1,
        "artifacts": {
            "alert": "alert.json",
            "metrics": "metrics.csv",
            "app_log": "app.log",
            "deploy": "deploy.json",
            "timeline": "timeline.json",
        },
    }
    (bundle_dir / "bundle.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return bundle_dir


def _parse_timestamp(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def restart_service(pid: int, command: str) -> tuple[subprocess.Popen[str], float]:
    mitigation_at = time.time()
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    time.sleep(1)
    process = subprocess.Popen(shlex.split(command), text=True)
    return process, mitigation_at


def wait_for_health(url: str, timeout: float = 10) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (TimeoutError, urllib.error.URLError):
            time.sleep(0.2)
    raise RuntimeError("service did not become healthy after mitigation")


def watch(
    metrics_path: Path,
    log_path: Path,
    bundle_root: Path,
    repo: Path,
    service_pid: int,
    restart_command: str,
    health_url: str,
    incident_id: str,
    load_started_at: float,
    mitigation_seconds: float,
    deploy_path: Path,
) -> Path:
    while True:
        rows = read_rows(metrics_path)
        rule = evaluate_rules(rows)
        if rule:
            break
        time.sleep(1)

    alert_started_at = time.time()
    deploy = latest_deploy(repo, deploy_path)
    preceding_warnings = [
        {
            **warning,
            "breach_started_at": iso_timestamp(warning["breach_started_at"]),
        }
        for warning in rule["preceding_warnings"]
    ]
    alert = {
        "incident_id": incident_id,
        "condition_name": rule["condition_name"],
        "policy_name": "checkout-local-regression",
        "state": "open",
        "breach_started_at": iso_timestamp(rule["breach_started_at"]),
        "started_at": iso_timestamp(alert_started_at),
        "ended_at": None,
        "resource": {"type": "local_service", "labels": {"service_name": "checkout_svc"}},
        "resource_labels": {"service_name": "checkout_svc", "environment": "local"},
        "threshold": rule["threshold"],
        "observed_value": rule["observed_value"],
        "preceding_warnings": preceding_warnings,
        "summary": f"{rule['severity']}: {rule['condition_name']}",
    }
    mitigation_process, mitigation_at = restart_service(service_pid, restart_command)
    wait_for_health(health_url)
    time.sleep(mitigation_seconds)
    ended_at = time.time()
    alert["state"] = "closed"
    alert["ended_at"] = iso_timestamp(ended_at)
    alert["observed_value"] = rule["observed_value"]
    first_500 = None
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("status", 0) >= 500:
            first_500 = float(record["ts"])
            break
    timeline = [
        {
            "ts": deploy["committed_at"],
            "event": "deploy",
            "detail": f"{deploy['subject']} ({deploy['sha'][:7]})",
        },
        {
            "ts": iso_timestamp(load_started_at),
            "event": "load start",
            "detail": "closed-loop load generator",
        },
        {
            "ts": (
                preceding_warnings[0]["breach_started_at"]
                if preceding_warnings
                else iso_timestamp(rule["breach_started_at"])
            ),
            "event": "first threshold breach",
            "detail": (
                preceding_warnings[0]["condition_name"]
                if preceding_warnings
                else rule["condition_name"]
            ),
        },
        {"ts": alert["started_at"], "event": "alert open", "detail": alert["condition_name"]},
    ]
    if first_500 is not None:
        timeline.append(
            {
                "ts": iso_timestamp(first_500),
                "event": "first 500",
                "detail": "checkout request failed",
            }
        )
    timeline.extend(
        [
            {
                "ts": iso_timestamp(mitigation_at),
                "event": "mitigation",
                "detail": "restart checkout service",
            },
            {
                "ts": alert["ended_at"],
                "event": "alert close",
                "detail": "service healthy after restart",
            },
        ]
    )
    mitigation_process.terminate()
    return assemble_bundle(
        bundle_root,
        incident_id,
        alert,
        metrics_path,
        log_path,
        repo,
        sorted(timeline, key=lambda x: _parse_timestamp(x["ts"])),
        deploy_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, default=Path("var/metrics.csv"))
    parser.add_argument("--log", type=Path, default=Path("var/app.log"))
    parser.add_argument("--bundle-root", type=Path, default=Path("incidents"))
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--deploy-path", type=Path, default=Path("checkout_svc"))
    parser.add_argument("--service-pid", type=int, required=True)
    parser.add_argument("--restart-command", required=True)
    parser.add_argument("--health-url", default="http://127.0.0.1:8000/healthz")
    parser.add_argument("--incident-id", default=f"inc-{int(time.time())}")
    parser.add_argument("--load-started-at", type=float, required=True)
    parser.add_argument("--mitigation-seconds", type=float, default=8)
    args = parser.parse_args()
    bundle = watch(
        args.metrics,
        args.log,
        args.bundle_root,
        args.repo,
        args.service_pid,
        args.restart_command,
        args.health_url,
        args.incident_id,
        args.load_started_at,
        args.mitigation_seconds,
        args.deploy_path,
    )
    print(bundle)


if __name__ == "__main__":
    main()
