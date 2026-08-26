"""Small checkout service used as the incident subject."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from threading import Lock
from typing import Any

import psutil
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("CHECKOUT_DATA_DIR", ROOT / "var"))
DB_PATH = DATA_DIR / "orders.db"
APP_LOG_PATH = DATA_DIR / "app.log"


def build_catalog() -> dict[str, float]:
    """Build the deterministic local catalog."""
    prices = {
        f"sku-{index:04d}": round(5 + ((index * 7919) % 10000) / 100, 2) for index in range(2000)
    }
    prices.update(
        {
            "cursor-hoodie": 75.00,
            "incident-notebook": 18.00,
            "coffee": 12.50,
            "sticker-pack": 4.00,
        }
    )
    return prices


PRICE_LIST = build_catalog()
PRICING_BUDGET_SECONDS = 0.250

METRIC_LOCK = Lock()
REQUEST_COUNT = 0
ERROR_COUNT = 0
LATENCIES_MS: deque[float] = deque(maxlen=10_000)
HISTOGRAM_BUCKETS = (100, 250, 500, 1000)
REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="")
PRICE_CACHE: dict[tuple[str, str], float] = {}

app = FastAPI(title="Checkout Service", version="1.0")


class Item(BaseModel):
    sku: str
    qty: int = Field(gt=0)


class CheckoutRequest(BaseModel):
    user_id: str
    items: list[Item] = Field(min_length=1)


def init_db() -> None:
    """Create the local order table if it does not exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                total REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()


def price_for(sku: str) -> float:
    """Return the local catalog price for a SKU."""
    try:
        return PRICE_LIST[sku]
    except KeyError as exc:
        raise ValueError(f"unknown SKU: {sku}") from exc


def prewarm_prices() -> None:
    """Populate the request's quotes in the shared memoization index."""
    request_id = REQUEST_ID.get()
    for sku, quote in PRICE_LIST.items():
        PRICE_CACHE[(request_id, sku)] = quote


def cached_price_for(sku: str) -> float:
    """Look up a quote by scanning the sorted memoization index."""
    key = (REQUEST_ID.get(), sku)
    for cached_key in sorted(PRICE_CACHE):
        if cached_key == key:
            return PRICE_CACHE[cached_key]
    return price_for(sku)


def current_rss_mb() -> float:
    """Return the current resident set size in MB."""
    return psutil.Process().memory_info().rss / 1024 / 1024


def _log(record: dict[str, Any]) -> None:
    line = json.dumps(record, separators=(",", ":"))
    print(line, flush=True)
    APP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with APP_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(line + "\n")


@app.middleware("http")
async def request_logging(request: Request, call_next):
    global REQUEST_COUNT, ERROR_COUNT

    started = time.perf_counter()
    request_id = request.headers.get("x-request-id", uuid.uuid4().hex)
    status = 500
    request_token = REQUEST_ID.set(request_id)
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        REQUEST_ID.reset(request_token)
        latency_ms = (time.perf_counter() - started) * 1000
        with METRIC_LOCK:
            REQUEST_COUNT += 1
            LATENCIES_MS.append(latency_ms)
            if status >= 500:
                ERROR_COUNT += 1
        _log(
            {
                "ts": time.time(),
                "level": "INFO" if status < 500 else "ERROR",
                "route": request.url.path,
                "status": status,
                "latency_ms": round(latency_ms, 2),
                "request_id": request_id,
                "msg": "request completed",
            }
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app.router.lifespan_context = lifespan


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/checkout")
def checkout(payload: CheckoutRequest) -> dict[str, float | int]:
    pricing_started = time.perf_counter()
    prewarm_prices()
    total = 0.0
    for item in payload.items:
        total += cached_price_for(item.sku) * item.qty
        if time.perf_counter() - pricing_started > PRICING_BUDGET_SECONDS:
            raise HTTPException(status_code=500, detail="pricing budget exceeded")

    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.execute(
            "INSERT INTO orders (user_id, total) VALUES (?, ?)",
            (payload.user_id, total),
        )
        connection.commit()
        order_id = cursor.lastrowid
    return {"order_id": order_id, "total": round(total, 2)}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    with METRIC_LOCK:
        request_count = REQUEST_COUNT
        error_count = ERROR_COUNT
        latencies = list(LATENCIES_MS)

    lines = [
        "# HELP checkout_requests_total Total HTTP requests.",
        "# TYPE checkout_requests_total counter",
        f"checkout_requests_total {request_count}",
        "# HELP checkout_errors_total Total HTTP 5xx responses.",
        "# TYPE checkout_errors_total counter",
        f"checkout_errors_total {error_count}",
        "# HELP checkout_request_latency_ms Request latency histogram.",
        "# TYPE checkout_request_latency_ms histogram",
    ]
    for bucket in HISTOGRAM_BUCKETS:
        lines.append(
            f'checkout_request_latency_ms_bucket{{le="{bucket}"}} '
            f"{sum(latency <= bucket for latency in latencies)}"
        )
    lines.extend(
        [
            f'checkout_request_latency_ms_bucket{{le="+Inf"}} {len(latencies)}',
            f"checkout_request_latency_ms_count {len(latencies)}",
            f"checkout_request_latency_ms_sum {sum(latencies):.2f}",
            "# HELP process_resident_memory_bytes Process RSS.",
            "# TYPE process_resident_memory_bytes gauge",
            f"process_resident_memory_bytes {current_rss_mb() * 1024 * 1024:.0f}",
        ]
    )
    return "\n".join(lines) + "\n"
