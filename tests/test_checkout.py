from pathlib import Path

from fastapi.testclient import TestClient

from checkout_svc import app as checkout_app


def test_price_lookup() -> None:
    assert checkout_app.price_for("coffee") == 12.50


def test_checkout_persists_order(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(checkout_app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(checkout_app, "DB_PATH", tmp_path / "orders.db")
    monkeypatch.setattr(checkout_app, "APP_LOG_PATH", tmp_path / "app.log")

    with TestClient(checkout_app.app) as client:
        response = client.post(
            "/checkout",
            json={
                "user_id": "u-123",
                "items": [
                    {"sku": "coffee", "qty": 2},
                    {"sku": "sticker-pack", "qty": 1},
                ],
            },
        )
        assert response.status_code == 200
        assert response.json()["total"] == 29.0
        assert response.json()["order_id"] == 1
        assert client.get("/healthz").json() == {"status": "ok"}

    assert (tmp_path / "orders.db").exists()
    assert len((tmp_path / "app.log").read_text().splitlines()) == 2


def test_metrics_include_histogram_and_rss(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(checkout_app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(checkout_app, "DB_PATH", tmp_path / "orders.db")
    monkeypatch.setattr(checkout_app, "APP_LOG_PATH", tmp_path / "app.log")

    with TestClient(checkout_app.app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert "checkout_requests_total" in response.text
    assert 'checkout_request_latency_ms_bucket{le="500"}' in response.text
    assert "process_resident_memory_bytes" in response.text
