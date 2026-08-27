import urllib.error

import pytest

from tools.loadgen import read_rss_mb


def test_read_rss_mb_returns_none_for_failed_scrape(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args, **_kwargs):
        raise urllib.error.URLError("scrape unavailable")

    monkeypatch.setattr("urllib.request.urlopen", fail)

    assert read_rss_mb("http://127.0.0.1:8000/metrics") is None
