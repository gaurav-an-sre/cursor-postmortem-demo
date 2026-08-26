"""Minimal Markdown to Notion REST API publisher."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import requests

NOTION_API = "https://api.notion.com/v1"


def _text(content: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": content}}]


def _paragraph(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _text(text)}}


def markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("```"):
            language = line[3:].strip() or "plain text"
            index += 1
            code_lines = []
            while index < len(lines) and not lines[index].startswith("```"):
                code_lines.append(lines[index])
                index += 1
            blocks.append(
                {
                    "object": "block",
                    "type": "code",
                    "code": {"rich_text": _text("\n".join(code_lines)), "language": language},
                }
            )
            index += 1
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            kind = f"heading_{len(heading.group(1))}"
            blocks.append(
                {
                    "object": "block",
                    "type": kind,
                    kind: {"rich_text": _text(heading.group(2))},
                }
            )
            index += 1
            continue
        bullet = re.match(r"^\s*[-*]\s+(.+)$", line)
        if bullet:
            blocks.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": _text(bullet.group(1))},
                }
            )
            index += 1
            continue
        if line.startswith("|"):
            table_lines = []
            while index < len(lines) and lines[index].startswith("|"):
                table_lines.append(lines[index])
                index += 1
            rows = []
            for table_line in table_lines:
                cells = [cell.strip() for cell in table_line.strip("|").split("|")]
                if cells and all(set(cell) <= {"-", ":"} for cell in cells):
                    continue
                rows.append(cells)
            is_action_table = bool(rows and any("Action" in cell for cell in rows[0]))
            for row_index, row in enumerate(rows):
                if is_action_table and row_index:
                    title = row[1] if len(row) > 1 else row[0]
                    blocks.append(
                        {
                            "object": "block",
                            "type": "to_do",
                            "to_do": {"rich_text": _text(title), "checked": False},
                        }
                    )
            if not is_action_table:
                children = [
                    {
                        "object": "block",
                        "type": "table_row",
                        "table_row": {"cells": [_text(cell) for cell in row]},
                    }
                    for row in rows
                ]
                if children:
                    blocks.append(
                        {
                            "object": "block",
                            "type": "table",
                            "table": {
                                "table_width": max(len(row) for row in rows),
                                "has_column_header": True,
                                "has_row_header": False,
                                "children": children,
                            },
                        }
                    )
            continue
        paragraph_lines = [line.strip()]
        index += 1
        while (
            index < len(lines)
            and lines[index].strip()
            and not re.match(r"^(#{1,3})\s+|^\s*[-*]\s+|^```|^\|", lines[index])
        ):
            paragraph_lines.append(lines[index].strip())
            index += 1
        blocks.append(_paragraph("\n".join(paragraph_lines)))
    return blocks


def chunk_blocks(blocks: list[dict[str, Any]], size: int = 100) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(blocks), size):
        yield blocks[index : index + size]


def publish_markdown(
    markdown: str, parent_page_id: str, token: str, session: Any = requests
) -> str:
    blocks = markdown_to_blocks(markdown)
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    chunks = list(chunk_blocks(blocks))
    first = chunks.pop(0) if chunks else []
    response = session.post(
        f"{NOTION_API}/pages",
        headers=headers,
        json={
            "parent": {"page_id": parent_page_id},
            "properties": {"title": {"title": _text("SRE Postmortem")}},
            "children": first,
        },
        timeout=30,
    )
    response.raise_for_status()
    page_id = response.json()["id"]
    for chunk in chunks:
        append = session.patch(
            f"{NOTION_API}/blocks/{page_id}/children",
            headers=headers,
            json={"children": chunk},
            timeout=30,
        )
        append.raise_for_status()
    return page_id
