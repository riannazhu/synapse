# Synapse — Track B

Step 1 implements the analysis boundary from the LLD. This is a foundation,
not the completed ML pipeline. No external dependencies are required yet.

```python
from server.analysis import analyze_entry, configure_extractor

configure_extractor(your_extractor)  # once at process startup
result = analyze_entry(entry_id, approved_text, existing_topics)
```

The extractor implements `extract(text, passages) -> dict`, returning `topics`
and `events` as illustrated in `fixtures/typed_entry.json`. The fixture is
fictional test data, not a production model implementation. No extractor is
silently selected by default.

## Proposed handoff to Track A

Only the function signature is agreed. The following dictionary fields are
proposed for review before integration:

- Input topics: `{id, label, kind: "topic" | "person", aliases?: list[str], merged_into?: str}`.
- Output: `{entry_id, pipeline_version, passages, topics, goal_events}`.
- Passage: `{start, end, text}`.
- Topic assignment: `{topic_id: str | None, label, kind, evidence_spans, resolution}`.
- Goal proposal: `{type, goal_label, evidence_spans, review_status: "pending"}`.
- Evidence span: `{start, end, quote}`. Offsets are absolute Unicode code points,
  with an exclusive end, into the exact approved input text.

Track A supplies owner-scoped topics and approved current revision text. It must
associate results with that revision and recheck ownership, revision, deletion,
lease token, aliases, and user overrides in its persistence transaction. This
function performs no database writes and cannot verify those conditions from
the agreed arguments. A null topic ID is a candidate, not authorization to
create a registry record. Hidden topics still participate in identity matching.

Only unambiguous exact topic aliases resolve in this first step. People never
resolve on name alone. Quotes establish provenance; they do not prove that a
model interpretation is correct. Semantic identity decisions, negation and
hypothetical evaluation, schema repair, event dates, embeddings, corrections,
and provider error classification remain for subsequent steps.

## Verification

Run `python3 -m unittest discover -s tests -v`.

## Next steps

1. Add a structured model extractor and one schema-repair attempt, with labeled
   evaluation cases for intentions, negations, quotations, and milestones.
2. Add versioned embeddings and grounded semantic topic resolution.
3. Add deterministic graph aggregation, supporting entries, comparisons, and
   persistent coordinate proposals against the LLD's three-entry fixture.
4. Connect analysis handlers to Track A's worker/repository interfaces when
   available; then add speech, handwriting, and conversational adapters.

Provider credentials remain server-side. Model selection is still open in the
LLD. Check-ups and Wrapped belong to shared Track D after the typed-entry path.
