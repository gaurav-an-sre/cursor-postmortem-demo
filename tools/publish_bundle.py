"""Publish an incident bundle to a git branch for cloud agents."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_git(repo: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=check,
        text=True,
        capture_output=True,
    )
    if check and result.returncode:
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        raise subprocess.CalledProcessError(
            result.returncode, result.args, output=result.stdout, stderr=result.stderr
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    repo = Path.cwd()
    bundle = args.bundle.resolve()
    try:
        relative_bundle = bundle.relative_to(repo.resolve())
    except ValueError as exc:
        raise SystemExit("--bundle must be inside the repository") from exc
    if relative_bundle.parts[:2] == ("examples", "incidents"):
        raise SystemExit("refusing to publish anything under examples/incidents/")
    manifest = bundle / "bundle.json"
    if not bundle.is_dir() or not manifest.is_file():
        raise SystemExit(f"incident bundle is missing: {bundle}")
    staged = run_git(repo, "diff", "--cached", "--quiet", check=False)
    if staged.returncode != 0:
        raise SystemExit("refusing to continue: staged changes are present")
    try:
        incident_id = json.loads(manifest.read_text(encoding="utf-8"))["incident_id"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid incident bundle manifest: {exc}") from exc
    branch = f"incident/{incident_id}"
    original = run_git(repo, "branch", "--show-current").stdout.strip()
    if not original:
        raise SystemExit("refusing to publish from a detached HEAD")
    switched = False
    try:
        existing = run_git(
            repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False
        )
        if existing.returncode == 0:
            run_git(repo, "switch", branch)
        else:
            run_git(repo, "switch", "-c", branch)
        switched = True
        run_git(repo, "add", "-f", "--", str(relative_bundle))
        run_git(repo, "commit", "-m", f"evidence: publish {incident_id}")
        run_git(repo, "push", "-u", "origin", branch)
    finally:
        if switched:
            run_git(repo, "switch", original)
    print(branch)
