The root cause analysis for incident `${incident_id}` is settled, and the follow-up code changes
are already made. Both are reproduced below as authoritative input. Treat every number, time,
and code location in them as final: do not recompute, re-investigate, or restate them with
different values. If something in them looks wrong, say so plainly in a `reviewer_note` field
rather than quietly correcting it.

<rca_json>
${rca_json}
</rca_json>

<remediation_summary>
${remediation_summary}
</remediation_summary>

You are writing the narrative sections of the blameless postmortem that will be published to
Notion. The document's factual sections — impact numbers, action items, evidence, timeline
entries, code locations — are rendered mechanically from the JSON above, so **do not repeat them
as prose**. Your job is only the parts a template cannot generate: the reasoning, the honest
assessment, and what the team should learn.

## Audience and voice

Written for an engineer who was not on call, reading this three months from now, possibly during a
similar incident. Blameless: describe systems, changes, and decisions — never people, never
"someone forgot". Direct and specific. No hedging, no filler, no congratulating the team.
Avoid the phrases "unfortunately", "as we all know", and "at the end of the day".

## Output

Your final message must be a single JSON object and nothing else — no prose before or after, no
markdown code fence:

{
  "schema_version": 1,
  "narrative": "3-5 paragraphs of markdown telling the story of the incident: what the system was doing, what the change intended to do, why the failure mode was not obvious, how it manifested to users, and how it was mitigated. Explain the mechanism in plain language that a reader unfamiliar with this service can follow. Reference the code by name where it helps, but do not paste the diff.",
  "why_it_took_this_long_to_detect": "1-2 paragraphs of markdown on the detection story specifically: what the monitoring did see, what it could not see, and why the gap existed. Be concrete about the signal that was missing.",
  "what_went_well": ["2-4 items, each one sentence, each grounded in something that actually happened during this incident"],
  "what_went_poorly": ["2-4 items, each one sentence, each naming a system or process weakness, not a person"],
  "where_we_got_lucky": ["1-3 items on what made this less bad than it could have been, or an empty list if nothing applies"],
  "lessons": ["2-4 items, each one sentence, generalizable beyond this incident and non-obvious. Do not write platitudes such as 'we should test more' or 'monitoring is important'."],
  "reviewer_note": "string, empty if nothing to flag: anything you believe is wrong, missing, or unsupported in the inputs above"
}

If the RCA's `root_cause.confidence` is not `high`, `narrative` must say so explicitly and name
what is still unproven. Never present a low-confidence cause as settled fact.
