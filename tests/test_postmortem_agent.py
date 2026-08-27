import json
import subprocess
import sys
from pathlib import Path

import pytest

import postmortem_agent.__main__ as cli
from postmortem_agent.notion import chunk_blocks, markdown_to_blocks, publish_markdown
from postmortem_agent.runner import (
    MockAgent,
    _execute_workflow,
    create_sdk_agent,
    remediation_skip_summary,
    run_workflow,
    should_run_remediation,
    strip_json_fence,
)
from postmortem_agent.tools import BundleTools
from postmortem_agent.validation import ValidationError, validate_publish, validate_rca

FIXTURES = Path(__file__).parent / "fixtures"
HOOK = Path(__file__).parents[1] / ".cursor" / "hooks" / "deny_incident_writes.py"


def fixture_rca() -> dict:
    return json.loads((FIXTURES / "mock_rca.json").read_text())


def run_hook(tmp_path: Path, tool_name: str, tool_input: dict) -> dict:
    result = subprocess.run(
        [str(HOOK)],
        input=json.dumps({"cwd": str(tmp_path), "tool_name": tool_name, "tool_input": tool_input}),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_immutable_evidence_hook_allows_reads_and_blocks_mutations(tmp_path: Path) -> None:
    assert (
        run_hook(tmp_path, "Write", {"path": "incidents/inc-1/metrics.csv"})["permission"] == "deny"
    )
    assert (
        run_hook(tmp_path, "Shell", {"command": "rm examples/incidents/inc-1/metrics.csv"})[
            "permission"
        ]
        == "deny"
    )
    assert (
        run_hook(tmp_path, "Read", {"path": "incidents/inc-1/metrics.csv"})["permission"] == "allow"
    )
    assert (
        run_hook(tmp_path, "Shell", {"command": "grep p99 incidents/inc-1/metrics.csv"})[
            "permission"
        ]
        == "allow"
    )
    assert run_hook(tmp_path, "Write", {"path": "out/result.md"})["permission"] == "allow"


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


def test_publish_validator_checks_required_fields_and_integer_count() -> None:
    valid = {"page_id": "page-id", "page_url": "https://notion.so/page-id", "blocks_written": 12}
    validate_publish(valid)
    for invalid in (
        {"page_id": "page-id", "blocks_written": 12},
        {"page_id": "page-id", "page_url": "url", "blocks_written": "12"},
    ):
        with pytest.raises(ValidationError):
            validate_publish(invalid)


def test_severity_gate() -> None:
    assert should_run_remediation("SEV1")
    assert should_run_remediation("SEV2")
    assert not should_run_remediation("SEV3")
    assert not should_run_remediation("SEV2", no_remediation=True)


def test_remediation_skip_reasons_are_distinct() -> None:
    assert remediation_skip_summary("SEV2", no_remediation=True) == (
        "Remediation skipped by explicit operator request for SEV2 incident."
    )
    assert remediation_skip_summary("SEV3") == "Remediation skipped: advisory-only SEV3 posture."


def test_json_fence_is_removed_without_changing_unfenced_text() -> None:
    assert strip_json_fence('```json\n{"ok": true}\n```') == '{"ok": true}'
    assert strip_json_fence('{"ok": true}') == '{"ok": true}'


def test_sdk_agent_mcp_config_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    import cursor_sdk

    calls: list[tuple[tuple, dict]] = []

    class FakeAgent:
        @staticmethod
        def create(*args, **kwargs):
            calls.append((args, kwargs))
            return object()

    monkeypatch.setattr(cursor_sdk, "Agent", FakeAgent)
    bundle_tools = BundleTools(FIXTURES)
    create_sdk_agent(Path("."), "api-key", bundle_tools)
    assert "mcp_servers" not in calls[0][1]

    create_sdk_agent(Path("."), "api-key", bundle_tools, "notion-secret")
    options = calls[1][1]["options"]
    assert options.mcp_servers["notion"].command == "npx"
    assert options.mcp_servers["notion"].args == ["-y", "@notionhq/notion-mcp-server"]
    assert options.mcp_servers["notion"].env == {"NOTION_TOKEN": "notion-secret"}


def test_mcp_prepends_notion_context_and_runs_publish(tmp_path: Path) -> None:
    bundle_dir = Path(__file__).parents[1] / "examples" / "incidents" / "inc-example"
    rca = (FIXTURES / "mock_rca.json").read_text().replace("fixture-incident", "inc-1787761269")
    narrative = (FIXTURES / "mock_narrative.json").read_text()
    publish = json.dumps(
        {"page_id": "page-id", "page_url": "https://notion.so/page-id", "blocks_written": 10}
    )
    agent = MockAgent([rca, narrative, publish])
    output = _execute_workflow(
        bundle_dir,
        tmp_path / "out",
        Path(__file__).parents[1],
        no_remediation=True,
        agent=agent,
        notion_mcp_token="notion-secret",
        notion_parent_page_id="parent-id",
    )
    assert output.exists()
    assert agent.sent[0].startswith("## Workspace context (Notion MCP)")
    assert len(agent.sent) == 3
    assert json.loads((output.parent / "publish.json").read_text())["page_id"] == "page-id"

    local_agent = MockAgent([rca, narrative])
    _execute_workflow(
        bundle_dir,
        tmp_path / "local-out",
        Path(__file__).parents[1],
        no_remediation=True,
        agent=local_agent,
    )
    assert not local_agent.sent[0].startswith("## Workspace context (Notion MCP)")


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--dry-run", "--notion-mode", "mcp"], "--dry-run cannot be used"),
        (["--mock-agent", "--notion-mode", "mcp"], "--mock-agent cannot be used"),
    ],
)
def test_mcp_mode_flag_conflicts(
    monkeypatch: pytest.MonkeyPatch, flags: list[str], message: str, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["postmortem-agent", "--bundle", str(Path("examples/incidents/inc-example")), *flags],
    )
    with pytest.raises(SystemExit):
        cli.main()
    assert message in capsys.readouterr().err


def test_mcp_mode_does_not_call_http_publisher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    postmortem = tmp_path / "postmortem.md"
    postmortem.write_text("# Incident\n", encoding="utf-8")
    (tmp_path / "publish.json").write_text(
        json.dumps(
            {"page_id": "page-id", "page_url": "https://notion.so/page-id", "blocks_written": 3}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOTION_TOKEN", "notion-secret")
    monkeypatch.setenv("NOTION_PARENT_PAGE_ID", "parent-id")
    monkeypatch.setattr(cli, "run_workflow", lambda *_args, **_kwargs: postmortem)
    monkeypatch.setattr(
        cli, "publish_markdown", lambda *_args, **_kwargs: pytest.fail("HTTP publisher called")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "postmortem-agent",
            "--bundle",
            "examples/incidents/inc-example",
            "--notion-mode",
            "mcp",
        ],
    )
    cli.main()
    assert "https://notion.so/page-id" in capsys.readouterr().out


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
    (tmp_path / "metrics.csv").write_text(
        "ts,rps,p50_ms,p95_ms,p99_ms,error_rate,rss_mb\n10,1,2,3,4,0,\n15,1,2,3,5,0,20\n",
        encoding="utf-8",
    )
    assert json.loads(tools.query_metrics({"metric": "rss_mb", "from_ts": 0, "to_ts": 20})) == [
        {"ts": 15.0, "rss_mb": 20.0}
    ]
    assert "unknown metric" in tools.query_metrics(
        {"metric": "not_a_metric", "from_ts": 0, "to_ts": 20}
    )
    assert "malformed regex" in tools.search_logs({"pattern": "[", "limit": 2})
    assert json.loads(tools.search_logs({"pattern": "500", "limit": 2})) == ['{"status":500}']
    (tmp_path / "metrics.csv").write_text(
        "ts,rps,p50_ms,p95_ms,p99_ms,error_rate,rss_mb\nbad,1,2,3,4,0,20\n",
        encoding="utf-8",
    )
    assert "malformed metrics.csv row" in tools.query_metrics(
        {"metric": "p99_ms", "from_ts": 0, "to_ts": 20}
    )


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
    assert (
        publish_markdown(
            markdown, "parent-id", "secret", "Incident title", "inc-1", session=session
        )
        == "page-id"
    )
    assert len(session.calls) == 3
    assert all(len(call[1]["json"]["children"]) <= 100 for call in session.calls)
    title = session.calls[0][1]["json"]["properties"]["title"]["title"]
    assert title[0]["text"]["content"] == "Incident title (inc-1)"


def test_notion_text_is_split_at_api_limit() -> None:
    blocks = markdown_to_blocks("```text\n" + ("x" * 4500) + "\n```")
    rich_text = blocks[0]["code"]["rich_text"]
    assert [len(item["text"]["content"]) for item in rich_text] == [2000, 2000, 500]


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
    assert agent.closed
    assert (output.parent / "rca_repair.jsonl").exists()
