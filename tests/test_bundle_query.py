import json
import sys
from pathlib import Path

import pytest

from tools import bundle_query

EXAMPLE_BUNDLE = Path(__file__).parents[1] / "examples" / "incidents" / "inc-example"


def run_query(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, *args: str) -> str:
    monkeypatch.setattr(sys, "argv", ["bundle_query", *args])
    bundle_query.main()
    return capsys.readouterr().out.strip()


def test_metrics_subcommand(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    result = json.loads(
        run_query(
            monkeypatch,
            capsys,
            "metrics",
            "--bundle",
            str(EXAMPLE_BUNDLE),
            "--metric",
            "p99_ms",
        )
    )
    assert result[0]["p99_ms"] == 101.83


def test_logs_subcommand(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    result = json.loads(
        run_query(
            monkeypatch,
            capsys,
            "logs",
            "--bundle",
            str(EXAMPLE_BUNDLE),
            "--pattern",
            '"status":500',
            "--limit",
            "1",
        )
    )
    assert len(result) == 1
    assert '"status":500' in result[0]


def test_deploy_subcommand(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    result = json.loads(run_query(monkeypatch, capsys, "deploy", "--bundle", str(EXAMPLE_BUNDLE)))
    assert result["subject"] == "perf: memoize price lookups for checkout"


def test_metrics_subcommand_reports_bad_metric(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    result = run_query(
        monkeypatch,
        capsys,
        "metrics",
        "--bundle",
        str(EXAMPLE_BUNDLE),
        "--metric",
        "not_a_metric",
    )
    assert result.startswith("error: unknown metric")
