import json
from pathlib import Path

from tools.watchdog import assemble_bundle


def test_bundle_assembly_matches_schema(tmp_path: Path) -> None:
    metrics = tmp_path / "metrics.csv"
    metrics.write_text(
        "ts,rps,p50_ms,p95_ms,p99_ms,error_rate,rss_mb\n1000,20,10,20,600,0.1,30\n",
        encoding="utf-8",
    )
    logs = tmp_path / "app.log"
    logs.write_text(
        '{"ts":900,"status":200}\n{"ts":1001,"status":500}\n{"ts":1200,"status":200}\n',
        encoding="utf-8",
    )
    repo = Path(__file__).resolve().parents[1]
    alert = {
        "incident_id": "inc-test",
        "condition_name": "Checkout p99 latency > 500ms for 30s",
        "policy_name": "checkout-local-regression",
        "state": "closed",
        "started_at": "1970-01-01T00:16:40+00:00",
        "ended_at": "1970-01-01T00:18:00+00:00",
        "resource": {"type": "local_service", "labels": {"service_name": "checkout_svc"}},
        "resource_labels": {"service_name": "checkout_svc", "environment": "local"},
        "threshold": 500,
        "observed_value": 600,
        "summary": "WARN: checkout latency",
    }
    timeline = [{"ts": alert["started_at"], "event": "alert open", "detail": "test"}]
    bundle = assemble_bundle(
        tmp_path / "incidents", "inc-test", alert, metrics, logs, repo, timeline
    )

    manifest = json.loads((bundle / "bundle.json").read_text())
    assert manifest["schema_version"] == 1
    assert manifest["incident_id"] == "inc-test"
    assert manifest["environment"] == "local"
    for filename in ("alert.json", "metrics.csv", "app.log", "deploy.json", "timeline.json"):
        assert (bundle / filename).exists()
    assert json.loads((bundle / "alert.json").read_text())["state"] == "closed"
    assert '"status":500' in (bundle / "app.log").read_text()
    deploy = json.loads((bundle / "deploy.json").read_text())
    assert "checkout_svc/" in "\n".join(deploy["files_changed"])
    assert deploy["subject"]
