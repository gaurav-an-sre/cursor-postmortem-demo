"""Read-only custom tools backed by one incident bundle."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from cursor_sdk import CustomTool

METRICS = {"ts", "rps", "p50_ms", "p95_ms", "p99_ms", "error_rate", "rss_mb"}


class BundleTools:
    def __init__(self, bundle_dir: Path) -> None:
        self.bundle_dir = bundle_dir

    def query_metrics(self, arguments: dict[str, Any]) -> str:
        metric = arguments.get("metric")
        from_ts = arguments.get("from_ts")
        to_ts = arguments.get("to_ts")
        if metric not in METRICS:
            return f"error: unknown metric {metric!r}; choose from {sorted(METRICS)}"
        try:
            start = float(from_ts)
            end = float(to_ts)
        except (TypeError, ValueError):
            return "error: from_ts and to_ts must be numeric Unix timestamps"
        if start > end:
            return "error: from_ts must not be greater than to_ts"
        try:
            with (self.bundle_dir / "metrics.csv").open(newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
        except OSError as exc:
            return f"error: unable to read metrics.csv: {exc}"
        values = []
        try:
            for row in rows:
                timestamp = float(row["ts"])
                value = float(row[metric])
                if start <= timestamp <= end:
                    values.append({"ts": timestamp, metric: value})
        except (KeyError, TypeError, ValueError) as exc:
            return f"error: malformed metrics.csv row: {exc}"
        return json.dumps(values)

    def search_logs(self, arguments: dict[str, Any]) -> str:
        pattern = arguments.get("pattern")
        limit = arguments.get("limit")
        if not isinstance(pattern, str):
            return "error: pattern must be a string"
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            return "error: limit must be a positive integer"
        try:
            matcher = re.compile(pattern)
        except re.error as exc:
            return f"error: malformed regex: {exc}"
        try:
            lines = (self.bundle_dir / "app.log").read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return f"error: unable to read app.log: {exc}"
        return json.dumps([line for line in lines if matcher.search(line)][:limit])

    def get_deploy_diff(self, _arguments: dict[str, Any] | None = None) -> str:
        try:
            return (self.bundle_dir / "deploy.json").read_text(encoding="utf-8")
        except OSError as exc:
            return f"error: unable to read deploy.json: {exc}"

    def custom_tools(self) -> dict[str, CustomTool]:
        return {
            "query_metrics": CustomTool(
                execute=lambda args, _ctx: self.query_metrics(dict(args)),
                description="Query one metrics.csv column over a Unix timestamp window.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string"},
                        "from_ts": {"type": "number"},
                        "to_ts": {"type": "number"},
                    },
                    "required": ["metric", "from_ts", "to_ts"],
                },
            ),
            "search_logs": CustomTool(
                execute=lambda args, _ctx: self.search_logs(dict(args)),
                description="Search app.log with a regular expression.",
                input_schema={
                    "type": "object",
                    "properties": {"pattern": {"type": "string"}, "limit": {"type": "integer"}},
                    "required": ["pattern", "limit"],
                },
            ),
            "get_deploy_diff": CustomTool(
                execute=lambda args, _ctx: self.get_deploy_diff(dict(args)),
                description="Read deploy.json, including the deploy diff.",
                input_schema={"type": "object", "properties": {}},
            ),
        }
