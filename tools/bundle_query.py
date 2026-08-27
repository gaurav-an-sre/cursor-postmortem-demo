"""Query an incident bundle from the command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from postmortem_agent.tools import BundleTools


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    metrics = subparsers.add_parser("metrics")
    metrics.add_argument("--bundle", type=Path, required=True)
    metrics.add_argument("--metric", required=True)
    metrics.add_argument("--from-ts", type=float)
    metrics.add_argument("--to-ts", type=float)

    logs = subparsers.add_parser("logs")
    logs.add_argument("--bundle", type=Path, required=True)
    logs.add_argument("--pattern", required=True)
    logs.add_argument("--limit", type=int, default=20)

    deploy = subparsers.add_parser("deploy")
    deploy.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    tools = BundleTools(args.bundle)

    if args.command == "metrics":
        from_ts = args.from_ts if args.from_ts is not None else float("-inf")
        to_ts = args.to_ts if args.to_ts is not None else float("inf")
        result = tools.query_metrics({"metric": args.metric, "from_ts": from_ts, "to_ts": to_ts})
    elif args.command == "logs":
        result = tools.search_logs({"pattern": args.pattern, "limit": args.limit})
    else:
        result = tools.get_deploy_diff({})
    print(result)


if __name__ == "__main__":
    main()
