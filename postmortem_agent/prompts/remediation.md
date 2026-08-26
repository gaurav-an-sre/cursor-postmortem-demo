The root cause analysis for incident `${incident_id}` is settled. It is reproduced below as
authoritative input. Do not re-derive it, do not re-investigate the incident, and do not
contradict it — if you find something that genuinely contradicts it, stop and say so in your
final message instead of silently changing course.

<rca_json>
${rca_json}
</rca_json>

You are now implementing the follow-up work on branch `${branch}`, which is already checked out.

## What to change

1. **The fix.** Correct the mechanism described in `root_cause`. Keep the change minimal and
   surgical: the smallest diff that removes the defect. Preserve the public behavior of
   `POST /checkout` — same request and response shape, same totals for the same inputs. If the
   defective code was trying to achieve something legitimate (for example, caching for speed),
   either implement it correctly with a bounded, correctly-keyed structure, or remove it
   entirely and say why in your summary. Do not refactor unrelated code, rename things, reformat
   files, or "improve" anything the RCA did not implicate.

2. **The regression test.** Add a test that fails against the defective code and passes against
   your fix, in the repository's existing pytest layout and style. It must assert on the
   mechanism, not on wall-clock timing: a test that sleeps or measures elapsed time is flaky and
   will be rejected. Assert on the observable invariant that the defect violated — for example,
   that the structure the RCA implicated stays bounded across many requests. Include a comment
   line referencing `${incident_id}` so a future reader can find this postmortem.

3. **The missing alert.** `detection_gap.missing_signal` names a signal that did not exist.
   Add it as an alert rule in the same declarative form the existing rules use — find how the
   watchdog defines its rules and extend that, do not invent a parallel mechanism. Choose a
   threshold and a sustain window that would have fired earlier than the alert in `alert.json`
   did, and state in your summary what the earlier detection time would have been and why that
   threshold will not fire during normal operation.

## Constraints

- Do not touch the files in `incidents/` — the bundle is immutable evidence.
- Do not edit any file whose only relation to the incident is that it is nearby.
- The repository's checks must pass. Run them yourself before you finish: `ruff check .`,
  `ruff format --check .`, and `pytest`. Fix what you break.
- Verify your regression test actually catches the defect: confirm it fails on the pre-fix code
  (for example by temporarily reverting your fix, or by reasoning it through against the
  original implementation, then re-applying) and report which method you used.
- Commit your work in focused commits with conventional-commit subjects. Do not push.

## Output

End with a plain-text summary, no JSON, covering:

- what you changed, file by file, and why each change is necessary;
- how you verified the regression test catches the defect;
- the new alert rule, its threshold and sustain window, how much earlier it would have fired, and
  its false-positive risk during normal traffic;
- anything in the RCA you could not act on, and why.
