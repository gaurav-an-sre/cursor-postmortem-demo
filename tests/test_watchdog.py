from tools.watchdog import evaluate_rules, sustained_breach


def rows(field: str, values: list[float]) -> list[dict[str, str]]:
    return [
        {"ts": str(index * 5), "p99_ms": "100", "error_rate": "0", field: str(value)}
        for index, value in enumerate(values)
    ]


def test_breach_is_not_alert_until_sustained() -> None:
    metrics = rows("p99_ms", [160, 170, 180, 190])
    fired, started, observed = sustained_breach(metrics, "p99_ms", 150, duration_s=20)
    assert not fired
    assert started == 0
    assert observed == 190
    assert evaluate_rules(metrics) is None


def test_warning_is_recorded_when_critical_fires() -> None:
    metrics = rows("p99_ms", [160, 170, 180, 190, 200, 220])
    for metric in metrics:
        metric["error_rate"] = "0.1"
    rule = evaluate_rules(metrics)
    assert rule is not None
    assert rule["severity"] == "CRIT"
    assert rule["preceding_warnings"][0]["condition_name"] == (
        "Checkout p99 latency > 150ms for 20s"
    )
    assert rule["preceding_warnings"][0]["paged"] is False
    assert rule["breach_started_at"] == 0


def test_critical_alert_requires_sustained_errors() -> None:
    metrics = rows("error_rate", [0.1, 0.1, 0.1, 0.1])
    rule = evaluate_rules(metrics)
    assert rule is None
