"""Validators for the authored RCA and narrative contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ValidationError(ValueError):
    """Raised when an agent response does not match its authored schema."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _require(mapping: Mapping[str, Any], key: str, errors: list[str], path: str = "") -> Any:
    if key not in mapping:
        errors.append(f"missing required key: {path}{key}")
        return None
    return mapping[key]


def _mapping(value: Any, path: str, errors: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        errors.append(f"{path} must be an object")
        return {}
    return value


def _string(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str):
        errors.append(f"{path} must be a string")


def _list(value: Any, path: str, errors: list[str], minimum: int = 0) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{path} must be a list")
        return []
    if len(value) < minimum:
        errors.append(f"{path} must contain at least {minimum} items")
    return value


def validate_rca(value: Any) -> None:
    errors: list[str] = []
    root = _mapping(value, "response", errors)
    for key in (
        "schema_version",
        "incident_id",
        "service",
        "severity",
        "title",
        "summary",
        "detected_at",
        "started_at",
        "resolved_at",
        "time_to_detect_seconds",
        "trigger",
        "root_cause",
        "evidence",
        "ruled_out",
        "impact",
        "contributing_factors",
        "detection_gap",
        "action_items",
    ):
        _require(root, key, errors)
    if root.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if root.get("severity") not in {"SEV1", "SEV2", "SEV3"}:
        errors.append("severity must be SEV1, SEV2, or SEV3")
    for key in (
        "incident_id",
        "service",
        "title",
        "summary",
        "detected_at",
        "started_at",
        "resolved_at",
    ):
        if key in root:
            _string(root[key], key, errors)

    trigger = _mapping(root.get("trigger"), "trigger", errors)
    for key in ("kind", "commit_sha", "commit_subject", "description"):
        _require(trigger, key, errors, "trigger.")
    if trigger.get("kind") not in {"deploy", "config_change", "traffic", "dependency", "unknown"}:
        errors.append("trigger.kind has an invalid enum value")
    for key in ("commit_sha", "commit_subject", "description"):
        if key in trigger and trigger[key] is not None:
            _string(trigger[key], f"trigger.{key}", errors)

    cause = _mapping(root.get("root_cause"), "root_cause", errors)
    for key in ("mechanism", "code_locations", "confidence", "confidence_rationale"):
        _require(cause, key, errors, "root_cause.")
    if cause.get("confidence") not in {"high", "medium", "low"}:
        errors.append("root_cause.confidence has an invalid enum value")
    for index, location in enumerate(
        _list(cause.get("code_locations"), "root_cause.code_locations", errors)
    ):
        location_map = _mapping(location, f"root_cause.code_locations[{index}]", errors)
        for key in ("path", "lines", "why"):
            _require(location_map, key, errors, f"root_cause.code_locations[{index}].")
            if key in location_map:
                _string(location_map[key], f"root_cause.code_locations[{index}].{key}", errors)

    evidence = _list(root.get("evidence"), "evidence", errors, minimum=4)
    evidence_sources = set()
    for index, item in enumerate(evidence):
        item_map = _mapping(item, f"evidence[{index}]", errors)
        for key in ("source", "observation", "supports"):
            _require(item_map, key, errors, f"evidence[{index}].")
            if key in item_map:
                _string(item_map[key], f"evidence[{index}].{key}", errors)
        evidence_sources.add(item_map.get("source"))
        if item_map.get("source") not in {"metrics", "logs", "code", "git", "alert"}:
            errors.append(f"evidence[{index}].source has an invalid enum value")
    for source in ("metrics", "logs", "code"):
        if source not in evidence_sources:
            errors.append(f"evidence must cover {source}")

    ruled_out = _list(root.get("ruled_out"), "ruled_out", errors, minimum=2)
    for index, item in enumerate(ruled_out):
        item_map = _mapping(item, f"ruled_out[{index}]", errors)
        for key in ("hypothesis", "refuted_by"):
            _require(item_map, key, errors, f"ruled_out[{index}].")
            if key in item_map:
                _string(item_map[key], f"ruled_out[{index}].{key}", errors)

    impact = _mapping(root.get("impact"), "impact", errors)
    for key in (
        "user_facing",
        "routes_affected",
        "failed_requests",
        "peak_p99_ms",
        "duration_seconds",
    ):
        _require(impact, key, errors, "impact.")
    detection_gap = _mapping(root.get("detection_gap"), "detection_gap", errors)
    for key in ("description", "missing_signal"):
        _require(detection_gap, key, errors, "detection_gap.")

    action_items = _list(root.get("action_items"), "action_items", errors, minimum=1)
    action_kinds = set()
    for index, item in enumerate(action_items):
        item_map = _mapping(item, f"action_items[{index}]", errors)
        for key in ("title", "kind", "priority", "rationale", "suggested_owner_role"):
            _require(item_map, key, errors, f"action_items[{index}].")
        action_kinds.add(item_map.get("kind"))
        if item_map.get("kind") not in {"fix", "test", "monitoring", "process"}:
            errors.append(f"action_items[{index}].kind has an invalid enum value")
        if item_map.get("priority") not in {"P0", "P1", "P2"}:
            errors.append(f"action_items[{index}].priority has an invalid enum value")
    for kind in ("fix", "test", "monitoring"):
        if kind not in action_kinds:
            errors.append(f"action_items must include a {kind} item")
    if errors:
        raise ValidationError(errors)


def validate_narrative(value: Any) -> None:
    errors: list[str] = []
    root = _mapping(value, "response", errors)
    for key in (
        "schema_version",
        "narrative",
        "why_it_took_this_long_to_detect",
        "what_went_well",
        "what_went_poorly",
        "where_we_got_lucky",
        "lessons",
        "reviewer_note",
    ):
        _require(root, key, errors)
    if root.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    for key in ("what_went_well", "what_went_poorly", "lessons"):
        _list(root.get(key), key, errors, minimum=2)
    _list(root.get("where_we_got_lucky"), "where_we_got_lucky", errors)
    if errors:
        raise ValidationError(errors)
