import json
from pathlib import Path

import pytest

from postmortem_agent.notion import chunk_blocks, markdown_to_blocks, publish_markdown
from postmortem_agent.runner import MockAgent, run_workflow, should_run_remediation
from postmortem_agent.tools import BundleTools
from postmortem_agent.validation import ValidationError, validate_rca

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_rca() -> dict:
    return json.loads((FIXTURES / "mock_rca.json").read_text())


def test_rca_validator_accepts_fixture_and_rejects_missing_key() -> None:
    validate_rca(fixture_rca())
    invalid = fixture_rca()
    del invalid["evidence"]
    with pytest.raises(ValidationError, match="missing required key"):
        validate_rca(invalid)


def test_rca_validator_checks_enum_and_minimum_counts() -> None:
    invalid = fixture_rca()
    invalid["severity"] = "SEV0"
    invalid["evidence"] = invalid["evidence"][:2]
    with pytest.raises(ValidationError) as error:
        validate_rca(invalid)
    assert "severity must be SEV1" in str(error.value)
    assert "evidence must contain at least 4 items" in str(error.value)


def test_severity_gate() -> None:
    assert should_run_remediation("SEV1")
    assert should_run_remediation("SEV2")
    assert not should_run_remediation("SEV3")
    assert not should_run_remediation("SEV2", no_remediation=True)


def test_custom_tools_and_errors(tmp_path: Path) -> None:
    (tmp_path / "metrics.csv").write_text(
        "ts,rps,p50_ms,p95_ms,p99_ms,error_rate,rss_mb\n10,1,2,3,4,0,20\n",
        encoding="utf-8",
    )
    (tmp_path / "app.log").write_text('{"status":500}\n', encoding="utf-8")
    (tmp_path / "deploy.json").write_text('{"subject":"deploy"}', encoding="utf-8")
    tools = BundleTools(tmp_path)
    assert json.loads(tools.query_metrics({"metric": "p99_ms", "from_ts": 0, "to_ts": 20})) == [
        {"ts": 10.0, "p99_ms": 4.0}
    ]
    assert "unknown metric" in tools.query_metrics(
        {"metric": "not_a_metric", "from_ts": 0, "to_ts": 20}
    )
    assert "malformed regex" in tools.search_logs({"pattern": "[", "limit": 2})
    assert json.loads(tools.search_logs({"pattern": "500", "limit": 2})) == ['{"status":500}']


def test_markdown_conversion_and_chunking() -> None:
    markdown = (
        "# Heading\n\nParagraph\n\n- One\n- Two\n\n"
        "| | Action | Type |\n|---|---|---|\n| ☐ | Fix cache | fix |\n\n"
        "```python\nprint('ok')\n```\n"
    )
    blocks = markdown_to_blocks(markdown)
    assert [block["type"] for block in blocks] == [
        "heading_1",
        "paragraph",
        "bulleted_list_item",
        "bulleted_list_item",
        "to_do",
        "code",
    ]
    assert list(chunk_blocks([{}] * 201, size=100)) == [[{}] * 100, [{}] * 100, [{}]]


def test_notion_publisher_chunks_requests() -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"id": "page-id"}

    class Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def post(self, url: str, **kwargs):
            self.calls.append((url, kwargs))
            return Response()

        def patch(self, url: str, **kwargs):
            self.calls.append((url, kwargs))
            return Response()

    markdown = "\n".join(f"## Heading {index}" for index in range(205))
    session = Session()
    assert publish_markdown(markdown, "parent-id", "secret", session=session) == "page-id"
    assert len(session.calls) == 3
    assert all(len(call[1]["json"]["children"]) <= 100 for call in session.calls)


def test_repair_run_fires_exactly_once(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "bundle.json").write_text(
        json.dumps({"incident_id": "inc-repair", "service": "checkout_svc"}), encoding="utf-8"
    )
    (bundle_dir / "alert.json").write_text("{}", encoding="utf-8")
    (bundle_dir / "timeline.json").write_text("[]", encoding="utf-8")
    (bundle_dir / "metrics.csv").write_text("ts,p99_ms\n1,2\n", encoding="utf-8")
    (bundle_dir / "app.log").write_text("", encoding="utf-8")
    (bundle_dir / "deploy.json").write_text("{}", encoding="utf-8")
    valid_rca = (FIXTURES / "mock_rca.json").read_text().replace("fixture-incident", "inc-repair")
    narrative = (FIXTURES / "mock_narrative.json").read_text()
    agent = MockAgent(["not json", valid_rca, narrative])
    output = run_workflow(
        bundle_dir,
        tmp_path / "out",
        Path(__file__).resolve().parents[1],
        no_remediation=True,
        agent_factory=lambda _repo, _key, _tools: agent,
    )
    assert output.exists()
    assert len(agent.sent) == 3
    assert (output.parent / "rca_repair.jsonl").exists()
