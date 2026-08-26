#!/usr/bin/env python3
"""Deny agent tools that could mutate immutable incident evidence."""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any


def target_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(target_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(target_text(item) for item in value)
    return ""


def protected_path(path_text: str, cwd: str) -> bool:
    path = Path(path_text)
    if not path.is_absolute():
        path = Path(cwd) / path
    try:
        relative = path.resolve().relative_to(Path(cwd).resolve())
    except ValueError:
        return False
    parts = relative.parts
    return parts[0:1] == ("incidents",) or parts[:2] == ("examples", "incidents")


def protected(path_text: str, cwd: str) -> bool:
    candidates = [path_text]
    try:
        candidates.extend(shlex.split(path_text))
    except ValueError:
        pass
    return any(protected_path(candidate.strip("'\";,()"), cwd) for candidate in candidates)


def shell_mutates(command: str) -> bool:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return True
    commands = {"rm", "mv", "cp", "truncate", "dd", "chmod"}
    if any(token in commands for token in tokens):
        return True
    quoted: str | None = None
    escaped = False
    for character in command:
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif quoted:
            if character == quoted:
                quoted = None
        elif character in {"'", '"'}:
            quoted = character
        elif character == ">":
            return True
    for index, token in enumerate(tokens):
        if token == "sed" and index + 1 < len(tokens) and tokens[index + 1].startswith("-i"):
            return True
        if token == "git" and any(
            command in tokens[index + 1 :] for command in {"checkout", "apply", "restore"}
        ):
            return True
    return False


def main() -> None:
    payload = json.load(sys.stdin)
    tool_name = str(payload.get("tool_name", "")).lower()
    tool_input = payload.get("tool_input", {})
    cwd = payload.get("cwd") or os.getcwd()
    target = target_text(tool_input)
    denied = False
    if tool_name in {"write", "edit", "delete"}:
        denied = protected(target, cwd)
    elif tool_name == "shell":
        denied = protected(target, cwd) and shell_mutates(
            str(tool_input.get("command", target)) if isinstance(tool_input, dict) else target
        )
    if denied:
        print(
            json.dumps(
                {
                    "permission": "deny",
                    "agent_message": (
                        "Incident evidence is immutable; do not write, edit, delete, or "
                        "shell-target files under incidents/ or examples/incidents."
                    ),
                    "user_message": "Blocked access to immutable incident evidence.",
                }
            )
        )
    else:
        print(json.dumps({"permission": "allow"}))


if __name__ == "__main__":
    main()
