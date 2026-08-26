"""Three-run Cursor SDK workflow for one incident."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from string import Template
from types import SimpleNamespace
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .tools import BundleTools
from .validation import ValidationError, validate_narrative, validate_rca


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "to_json"):
        return value.to_json()
    if hasattr(value, "__dict__"):
        return {key: _jsonable(item) for key, item in value.__dict__.items()}
    return value


def _message_text(message: Any) -> str:
    direct = getattr(message, "text", "")
    if direct:
        return str(direct)
    content = getattr(getattr(message, "message", None), "content", ())
    return "".join(getattr(block, "text", "") for block in content)


def _event_field(message: Any, *names: str) -> Any:
    for name in names:
        value = getattr(message, name, None)
        if value is not None:
            return value
        raw = _jsonable(message)
        if isinstance(raw, dict) and name in raw:
            return raw[name]
    return None


def strip_json_fence(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def stream_run(run: Any, name: str, output_dir: Path) -> tuple[str, str, dict[str, Any]]:
    events_path = output_dir / f"{name}.jsonl"
    started = time.perf_counter()
    assistant_text = ""
    with events_path.open("w", encoding="utf-8") as events_file:
        for message in run.stream():
            event = _jsonable(message)
            events_file.write(json.dumps(event, default=str) + "\n")
            message_type = getattr(message, "type", "event")
            text = _message_text(message)
            if message_type == "assistant":
                assistant_text += text
                print(f"[{name}] assistant: {text}", flush=True)
            elif message_type == "thinking":
                print(f"[{name}] thinking: {text}", flush=True)
            elif message_type == "tool_call":
                tool_name = _event_field(message, "tool_name", "name") or "unknown"
                status = _event_field(message, "status") or "unknown"
                print(f"[{name}] tool_call: {tool_name} ({status})", flush=True)
            elif message_type == "status":
                status = _event_field(message, "status", "value") or text or "unknown"
                print(f"[{name}] status: {status}", flush=True)
            elif message_type == "usage":
                usage = _jsonable(_event_field(message, "usage")) or _jsonable(message)
                if isinstance(usage, dict):
                    total = usage.get("total_tokens", usage.get("totalTokens", "unknown"))
                else:
                    total = "unknown"
                print(f"[{name}] usage: {total} total tokens", flush=True)
    result = run.wait()
    final_text = getattr(result, "result", "") or assistant_text
    usage = _jsonable(getattr(result, "usage", None)) or {}
    duration_ms = getattr(result, "duration_ms", None)
    if not duration_ms:
        duration_ms = round((time.perf_counter() - started) * 1000)
    print(f"[{name}] complete: duration={duration_ms}ms usage={usage}", flush=True)
    return str(final_text), str(getattr(result, "id", getattr(run, "run_id", ""))), usage


def render_prompt(name: str, variables: dict[str, str]) -> str:
    prompt_path = Path(__file__).parent / "prompts" / name
    return Template(prompt_path.read_text(encoding="utf-8")).safe_substitute(**variables)


def ensure_branch(repo: Path, branch: str) -> None:
    existing = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo
    )
    if existing.returncode == 0:
        subprocess.run(["git", "switch", branch], cwd=repo, check=True)
    else:
        subprocess.run(["git", "switch", "-c", branch], cwd=repo, check=True)


def create_sdk_agent(repo: Path, api_key: str, bundle_tools: BundleTools) -> Any:
    from cursor_sdk import Agent, LocalAgentOptions

    return Agent.create(
        model="composer-2.5",
        api_key=api_key,
        local=LocalAgentOptions(cwd=str(repo), custom_tools=bundle_tools.custom_tools()),
    )


@dataclass
class MockMessage:
    type: str
    text: str


class MockRun:
    def __init__(self, run_id: str, text: str) -> None:
        self.run_id = run_id
        self._text = text

    def stream(self):
        yield MockMessage("status", "mock run started")
        yield MockMessage("assistant", self._text)

    def wait(self) -> Any:
        return SimpleNamespace(result=self._text, run_id=self.run_id, duration_ms=1, usage={})


class MockAgent:
    """Fixture-backed SDK substitute for offline demos and tests."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.sent: list[str] = []
        self.closed = False

    def __enter__(self) -> MockAgent:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True

    def send(self, prompt: str) -> MockRun:
        self.sent.append(prompt)
        index = min(len(self.sent) - 1, len(self.responses) - 1)
        return MockRun(f"mock-run-{len(self.sent)}", self.responses[index])


def should_run_remediation(severity: str, no_remediation: bool = False) -> bool:
    return not no_remediation and severity in {"SEV1", "SEV2"}


def fixture_agent(incident_id: str) -> MockAgent:
    fixture_dir = Path(__file__).parents[1] / "tests" / "fixtures"
    rca = (
        (fixture_dir / "mock_rca.json")
        .read_text(encoding="utf-8")
        .replace("fixture-incident", incident_id)
    )
    narrative = (fixture_dir / "mock_narrative.json").read_text(encoding="utf-8")
    remediation = (fixture_dir / "mock_remediation.txt").read_text(encoding="utf-8")
    return MockAgent([rca, remediation, narrative])


def _execute_workflow(
    bundle_dir: Path,
    out_root: Path,
    repo: Path,
    no_remediation: bool,
    agent: Any,
) -> Path:
    bundle = json.loads((bundle_dir / "bundle.json").read_text(encoding="utf-8"))
    incident_id = bundle["incident_id"]
    output_dir = out_root / incident_id
    output_dir.mkdir(parents=True, exist_ok=True)
    service = bundle["service"]
    run_ids: list[str] = []
    rca_prompt = render_prompt(
        "rca.md",
        {"service": service, "incident_id": incident_id, "bundle_dir": str(bundle_dir.resolve())},
    )
    raw_rca, run_id, _ = stream_run(agent.send(rca_prompt), "rca", output_dir)
    run_ids.append(run_id)
    try:
        rca = json.loads(strip_json_fence(raw_rca))
        validate_rca(rca)
    except (json.JSONDecodeError, ValidationError) as exc:
        repair_prompt = render_prompt("repair_json.md", {"error": str(exc)})
        repaired, repair_id, _ = stream_run(agent.send(repair_prompt), "rca_repair", output_dir)
        run_ids.append(repair_id)
        try:
            rca = json.loads(repaired)
            validate_rca(rca)
        except (json.JSONDecodeError, ValidationError) as repair_exc:
            (output_dir / "rca.raw.txt").write_text(repaired, encoding="utf-8")
            raise SystemExit(f"RCA repair response was invalid: {repair_exc}") from repair_exc
    (output_dir / "rca.json").write_text(json.dumps(rca, indent=2) + "\n", encoding="utf-8")
    frozen_rca = (output_dir / "rca.json").read_text(encoding="utf-8")

    severity = rca["severity"]
    remediation_summary = "Remediation skipped: advisory-only SEV3 posture."
    if should_run_remediation(severity, no_remediation):
        branch = f"postmortem/{incident_id}"
        ensure_branch(repo, branch)
        remediation_prompt = render_prompt(
            "remediation.md",
            {"incident_id": incident_id, "rca_json": frozen_rca, "branch": branch},
        )
        remediation_summary, remediation_id, _ = stream_run(
            agent.send(remediation_prompt), "remediation", output_dir
        )
        run_ids.append(remediation_id)
    (output_dir / "remediation_summary.txt").write_text(remediation_summary, encoding="utf-8")

    narrative_prompt = render_prompt(
        "narrative.md",
        {
            "incident_id": incident_id,
            "rca_json": frozen_rca,
            "remediation_summary": remediation_summary,
        },
    )
    raw_narrative, narrative_id, _ = stream_run(
        agent.send(narrative_prompt), "narrative", output_dir
    )
    run_ids.append(narrative_id)
    try:
        narrative = json.loads(strip_json_fence(raw_narrative))
        validate_narrative(narrative)
    except (json.JSONDecodeError, ValidationError) as exc:
        (output_dir / "narrative.raw.txt").write_text(raw_narrative, encoding="utf-8")
        raise SystemExit(f"Narrative response was invalid: {exc}") from exc
    (output_dir / "narrative.json").write_text(
        json.dumps(narrative, indent=2) + "\n", encoding="utf-8"
    )

    timeline = json.loads((bundle_dir / "timeline.json").read_text(encoding="utf-8"))
    template_dir = Path(__file__).parent / "templates"
    environment = Environment(loader=FileSystemLoader(template_dir))
    document = environment.get_template("postmortem.md.j2").render(
        rca=json.loads(frozen_rca),
        narrative=narrative,
        timeline=timeline,
        remediation_summary=remediation_summary,
        run_ids=run_ids,
    )
    postmortem_path = output_dir / "postmortem.md"
    postmortem_path.write_text(document, encoding="utf-8")
    return postmortem_path


def run_workflow(
    bundle_dir: Path,
    out_root: Path,
    repo: Path,
    no_remediation: bool = False,
    mock_agent: bool = False,
    agent_factory: Callable[[Path, str, BundleTools], Any] | None = None,
) -> Path:
    bundle = json.loads((bundle_dir / "bundle.json").read_text(encoding="utf-8"))
    bundle_tools = BundleTools(bundle_dir)
    api_key = os.getenv("CURSOR_API_KEY", "")
    if mock_agent:
        agent = fixture_agent(bundle["incident_id"])
    else:
        if not api_key and agent_factory is None:
            raise SystemExit(
                "CURSOR_API_KEY is required; use --mock-agent for an offline fixture run"
            )
        agent = (agent_factory or create_sdk_agent)(repo, api_key, bundle_tools)
    with agent:
        return _execute_workflow(bundle_dir, out_root, repo, no_remediation, agent)
