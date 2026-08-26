"""Command-line entry point for the postmortem workflow."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .notion import publish_markdown
from .runner import run_workflow


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mock-agent", action="store_true")
    parser.add_argument("--no-remediation", action="store_true")
    parser.add_argument("--notion-parent", default=os.getenv("NOTION_PARENT_PAGE_ID"))
    parser.add_argument("--out", type=Path, default=Path("out"))
    args = parser.parse_args()

    postmortem = run_workflow(
        args.bundle.resolve(),
        args.out,
        Path.cwd(),
        no_remediation=args.no_remediation,
        mock_agent=args.mock_agent,
    )
    token = os.getenv("NOTION_TOKEN")
    dry_run = args.dry_run or not token
    if dry_run:
        print(f"Notion dry-run: wrote {postmortem}")
        return
    if not args.notion_parent:
        raise SystemExit("NOTION_PARENT_PAGE_ID or --notion-parent is required for publishing")
    rca = json.loads((postmortem.parent / "rca.json").read_text(encoding="utf-8"))
    page_id = publish_markdown(
        postmortem.read_text(encoding="utf-8"),
        args.notion_parent,
        token,
        title=rca["title"],
        incident_id=rca["incident_id"],
    )
    print(f"Published Notion page: {page_id}")


if __name__ == "__main__":
    main()
