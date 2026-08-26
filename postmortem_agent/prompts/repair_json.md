Your previous message was expected to be a single JSON object matching the schema you were given,
but it could not be used:

<error>
${error}
</error>

Re-emit the same content, corrected, as a single JSON object and nothing else — no prose before or
after, no markdown code fence, no trailing commentary. Do not change any of your findings,
numbers, or conclusions; only fix the structure so it validates. If a required field genuinely has
no supported value, use `"unknown"` for strings, `0` for numbers, and `[]` for lists rather than
omitting the field or inventing a value.
