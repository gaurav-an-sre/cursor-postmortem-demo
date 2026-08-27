# Publish the postmortem to Notion

You have the Notion MCP server available. Publish the finished postmortem for incident $incident_id.

The source of truth is the rendered markdown at $postmortem_path. Publish it as written: do not
re-analyze the incident, do not re-derive metrics, do not rewrite the root cause, and do not add
content that is not in that file.

Steps:

1. Read $postmortem_path.
2. Create a new Notion page whose parent is the page with id $parent_page_id.
3. Title the page with the postmortem's own H1 heading text.
4. Reproduce the document structure: headings, paragraphs, bulleted lists, and tables. Render every
   row of the action items table as an unchecked to_do (checkbox) block, keeping the owner and the
   due date in the block text.
5. If the content is too large for a single request, append it across several requests rather than
   truncating it. Never drop a section.
6. Retrieve the page after creation to confirm it exists.

Reply with strict JSON and nothing else:

{"page_id": "<id of the created page>", "page_url": "<url of the created page>", "blocks_written": <integer>}
