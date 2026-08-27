"""Closed-loop HTTP load generator for the checkout service."""

from __future__ import annotations

import argparse
import csv
import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

WINDOW_SECONDS = 5


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return ordered[index]


def request_once(url: str, request_number: int) -> tuple[float, int]:
    payload = {
        "user_id": f"load-user-{request_number % 100}",
        "items": [{"sku": "coffee", "qty": 1}],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", "x-request-id": f"load-{request_number}"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            status = response.status
            response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (TimeoutError, urllib.error.URLError):
        status = 599
    return (time.perf_counter() - started) * 1000, status


def read_rss_mb(metrics_url: str) -> float | None:
    try:
        with urllib.request.urlopen(metrics_url, timeout=3) as response:
            text = response.read().decode()
    except (TimeoutError, urllib.error.URLError):
        return None
    for line in text.splitlines():
        if line.startswith("process_resident_memory_bytes "):
            try:
                return float(line.rsplit(" ", 1)[1]) / 1024 / 1024
            except ValueError:
                return None
    return None


def run_load(url: str, rps: float, duration: float, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    records: list[tuple[float, float, int]] = []
    records_lock = threading.Lock()
    stop = threading.Event()
    counter = 0
    counter_lock = threading.Lock()
    workers = max(4, min(64, int(rps) + 2))

    def worker(worker_id: int) -> None:
        nonlocal counter
        interval = workers / rps
        while not stop.is_set():
            started = time.perf_counter()
            with counter_lock:
                request_number = counter
                counter += 1
            latency_ms, status = request_once(url, worker_id * 1_000_000 + request_number)
            with records_lock:
                records.append((time.time(), latency_ms, status))
            stop.wait(max(0.0, interval - (time.perf_counter() - started)))

    started_at = time.time()
    end_at = started_at + duration
    with output.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["ts", "rps", "p50_ms", "p95_ms", "p99_ms", "error_rate", "rss_mb"],
        )
        writer.writeheader()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(worker, worker_id) for worker_id in range(workers)]
            window_start = started_at
            while time.time() < end_at:
                time.sleep(max(0.0, window_start + WINDOW_SECONDS - time.time()))
                window_end = min(time.time(), end_at)
                with records_lock:
                    window = [
                        record for record in records if window_start <= record[0] < window_end
                    ]
                latencies = [record[1] for record in window]
                errors = sum(record[2] >= 500 for record in window)
                rss_mb = read_rss_mb(url.removesuffix("/checkout") + "/metrics")
                writer.writerow(
                    {
                        "ts": f"{window_end:.3f}",
                        "rps": f"{len(window) / max(window_end - window_start, 0.001):.2f}",
                        "p50_ms": f"{percentile(latencies, 0.50):.2f}",
                        "p95_ms": f"{percentile(latencies, 0.95):.2f}",
                        "p99_ms": f"{percentile(latencies, 0.99):.2f}",
                        "error_rate": f"{errors / max(len(window), 1):.4f}",
                        "rss_mb": "" if rss_mb is None else f"{rss_mb:.2f}",
                    }
                )
                csv_file.flush()
                window_start = window_end
            stop.set()
            for future in futures:
                future.cancel()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/checkout")
    parser.add_argument("--rps", type=float, default=8)
    parser.add_argument("--duration", type=float, default=80)
    parser.add_argument("--output", type=Path, default=Path("var/metrics.csv"))
    args = parser.parse_args()
    if args.rps <= 0 or args.duration <= 0:
        raise SystemExit("rps and duration must be positive")
    run_load(args.url, args.rps, args.duration, args.output)


if __name__ == "__main__":
    main()
