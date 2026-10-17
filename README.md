# Synapse — Track B

## Current progress

- Implemented: updated function signature with required entry date and revision, passage segmentation, exact evidence
  validation, exact topic aliases, pending goal proposals, Gemini structured
  extraction, one output-repair attempt, and provider error classification.
- Added: ten fictional manual-review cases and 33 passing offline tests.
- Not yet verified: live Gemini responses or extraction quality. A key is needed.
- Added: prototype RAG question answering with four explicit retrieval strategies,
  Gemini answer generation, citations, and an embedding adapter.
- Still to build: semantic topic matching, graph aggregation and evidence
  lookup, Track A worker integration, and media/chat adapters.

This step uses only Python's standard library; no pip installation is needed.

## Run the fictional example

1. Create your local environment file:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env`, setting `GEMINI_API_KEY` to your own key. The model is configurable
   through `GEMINI_MODEL`; the template uses `gemini-2.5-flash`. Check availability
   and quota for your account in AI Studio.
3. Load your locally edited environment and run:
   ```bash
   set -a
   source .env
   set +a
   python3 -m server.analysis.demo
   ```

`.env` and `.env.*` are ignored by Git; the placeholder-only `.env.example`
is intentionally trackable. Python does not automatically load `.env`.
Use fictional entries for free-tier development; review provider data handling
before processing personal journals. The demo prints its fictional result.

## How to explain this step

1. Track A passes saved, approved text and owner-scoped existing topics.
2. We preserve the original text and split it into passages with exact offsets.
3. The Gemini adapter sends the full entry with instructions and a JSON Schema.
   The schema defines topics, people, goal-event categories, and evidence quotes.
   Journal content is treated as data, never system instructions.
4. Gemini returns JSON. We parse and validate every field and find each exact
   quote in the original text. Python calculates Unicode offsets. A zero-based
   occurrence disambiguates repeated quotes, including overlapping matches.
5. Invalid structure or evidence gets one regeneration attempt. Persistent
   invalid output raises an error. Network/rate-limit errors are classified for
   Track A's worker to retry; this adapter does not schedule retries.
6. The analysis service rechecks spans, reuses exact unambiguous topic aliases,
   and returns goal events with `review_status: "pending"`.

The LLM extracts meaning; Python checks structure and provenance. Matching a
quote does not prove the interpretation is correct. Negation, hypothetical,
quotation, and prompt-injection examples in `fixtures/extraction_review.json`
require manual live-model review. Those annotations are not claims of measured
accuracy. Exact aliases resolve in Python. Unresolved general topics are compared
with the small existing registry in two separate Gemini matching calls.

For Track A startup:

```python
from server.analysis import analyze_entry, configure_extractor

from server.models.gemini import GeminiExtractor

configure_extractor(GeminiExtractor())  # once at process startup
result = analyze_entry(
    entry_id, approved_text, existing_topics,
    entry_date="2026-10-17", revision=1,
)
```

The extractor implements `extract(text, passages, *, entry_date) -> dict`. Gemini returns
quotes and occurrences internally; the adapter converts them to the offset
contract illustrated in `fixtures/typed_entry.json`. No extractor is silently
selected by default.

## Proposed handoff to Track A

The required date/revision arguments are now implemented. Track A must update
its caller; old calls without them raise TypeError. The following dictionary fields are
proposed for review before integration:

- Input topics: `{id, label, kind: "topic" | "person", aliases?: list[str], merged_into?: str}`.
- Output: `{entry_id, entry_date, revision, pipeline_version, passages, topics, goal_events}`.
- Passage: `{start, end, text}`.
- Topic assignment: `{topic_id: str | None, label, kind, evidence_spans, resolution}`.
- Goal proposal: `{type, goal_label, event_date, date_source, evidence_spans, review_status: "pending"}`.
- Evidence span: `{start, end, quote}`. Offsets are absolute Unicode code points,
  with an exclusive end, into the exact approved input text.

Track A supplies owner-scoped topics and approved current revision text. It must
associate results with that revision and recheck ownership, revision, deletion,
lease token, aliases, and user overrides in its persistence transaction. This
function performs no database writes and cannot verify those conditions from
the agreed arguments. A null topic ID is a candidate, not authorization to
create a registry record. Hidden topics still participate in identity matching.

Unambiguous exact topic aliases resolve first, followed by grounded semantic
matching when the extractor supports it. People never
resolve on name alone. Quotes establish provenance; they do not prove that a
model interpretation is correct. Live semantic quality
evaluation, embedding-based candidate retrieval, and corrections remain for subsequent steps.

## Verification

Run `python3 -m unittest discover -s tests -v`.

## Next steps

1. Run the fictional example with your key and review the ten annotated cases.
2. Pass a small existing-topic registry to a grounded semantic matching step.
   Add embedding retrieval after the basic flow works.
3. Add deterministic graph aggregation and supporting entry IDs. Give Track C
   a sample graph, then run five entries through extraction → graph → evidence.
4. Connect analysis handlers to Track A's worker/repository interfaces when
   available; then add speech, handwriting, and conversational adapters.

Provider credentials remain server-side. Check-ups and Wrapped belong to shared
Track D after the typed-entry path.

API reference: https://ai.google.dev/gemini-api/docs/generate-content/structured-output

## Date and revision contract

```python
def analyze_entry(
    entry_id: str,
    text: str,
    existing_topics: list,
    *,
    entry_date: str,  # YYYY-MM-DD, user-selected journal calendar date
    revision: int,  # positive integer identifying this approved text version
) -> dict:
    ...
```

The result echoes entry_date and revision; pipeline_version is now analysis-v3.
Track A must save these with the result and reject it if the current entry
revision has changed. Echoing a revision alone does not enforce concurrency.
The revision is not needed by Gemini and is not sent to it.

Each goal event has event_date and date_source:

| date_source | Meaning |
|---|---|
| explicit | A calendar date explicitly stated in the text |
| relative | An unambiguous relative date resolved against entry_date |
| entry_date | No clear event date; use the entry's date as a fallback |

For an entry dated 2026-10-17, “Yesterday I practiced piano” should yield
2026-10-16 with source relative. Missing or ambiguous dates fall back to
2026-10-17. A future goal deadline is not the date the intention was expressed.
The system does not use today's server date or need a timezone conversion for
these calendar dates. Track A supplies the user's chosen entry_date.

Python validates calendar dates and fallback consistency. Explicit/relative
interpretations are proposed by the model, not independently verified temporal
facts; review them against the supporting quotes during live evaluation.
Graph date filtering uses entry_date, while the goal timeline can use event_date.
This module returns records; Track A still owns storage and invalidation.

## RAG for journal questions

Entry analysis still uses analyze_entry. Questions use a separate read service:

```python
from server.retrieval import JournalEntry, answer_question
from server.models.rag import GeminiAnswerer, GeminiEmbedder

result = answer_question(
    "How have my priorities changed?",
    entries,  # list[JournalEntry] from Track A's authorized snapshot
    user_id=authenticated_user_id,
    history_enabled=True,
    strategy="broad",
    generator=GeminiAnswerer(),
)
```

| Strategy | Retrieval | Use |
|---|---|---|
| broad (default) | Round-robin passages across calendar quarters and entries | How have my priorities changed? |
| semantic | Gemini query/document embeddings and exact cosine ranking | When have I felt this way? |
| filtered | Canonical topic IDs and half-open entry-date filters | What happened with Maya during a specific summer? |
| counts | Distinct analyzed entry membership; no LLM | What do I mention most? |

Pass embedder=GeminiEmbedder() for semantic retrieval. Pass topic_ids=("maya-id",),
from_date="2026-06-01", to_date="2026-09-01" for filtered retrieval. The caller
chooses the strategy and resolves ambiguous identities and dates; there is no
natural-language routing or automatic interpretation of “last summer” yet.

Broad retrieval uses a bounded sample (default 12 passages). It spreads evidence
across quarters; when quarters exceed the budget it samples evenly through
history. It does not guarantee full coverage or relevance to every broad
question. Coverage metadata identifies the eligible and retrieved entry counts.
Semantic retrieval currently embeds passages on each call: suitable for a small
prototype, but it makes one provider request per passage plus the query. Track A
should persist versioned passage embeddings and supply an owner-filtered vector
repository before scaling this path. No universal similarity cutoff is assumed.

Each returned claim cites evidence IDs. Evidence contains entry_id, revision,
entry_date, start, end, and an exact quote sliced from approved text. Python
rejects unknown citations. Citation validity does not prove that a claim follows
from its sources; live grounded-answer evaluation remains necessary. Empty
retrieval returns insufficient_evidence without calling Gemini.

History retrieval requires history_enabled=True. The service additionally
excludes foreign-user, deleted, unapproved, and stale revisions. Track A must
supply authoritative current_revision/approval/deletion fields, current valid
topic membership (excluding hidden/merged topics for visible counts), and an
authorized consistent database snapshot. It must revalidate revisions/evidence
before serving or persisting results if concurrent edits can occur. These Python
checks complement authentication; callers cannot supply user identity from a
browser request body as authority. In-memory counts must receive the complete
filtered snapshot, not a paginated subset.

Run the fictional broad-question demo after loading .env:

```bash
python3 -m server.retrieval.demo
```

GEMINI_EMBEDDING_MODEL is added to .env.example. Broad, filtered, and count
strategies do not require embedding calls. Live calls have not been tested here;
provider model availability and quota depend on your account.

Embedding API reference: https://ai.google.dev/api/embeddings

## Extraction quality evaluation

After loading .env, run:

```bash
python3 -m server.analysis.evaluate
```

This makes live Gemini calls for the ten fictional entries in
fixtures/extraction_review.json. It checks required event types and people,
rejects forbidden achievements, and writes evaluation/extraction_report.json
with full analyses for inspection. An ambiguous-name case requires manual
review rather than automatically passing. Provider errors are reported
separately from quality failures. The command exits nonzero for either.
The fixed reference entry date is 2026-10-17; no real journal entries are read.
A valid quote and a passing annotation do not prove every extraction correct.
Review extra topics, missing events, dates, and labels in the report before
changing prompts. Reports include model and evaluation timestamp for traceability.

Latest live evaluation: 8 cases passed their automated checks; f9 (ambiguous
names) and f10 (prompt injection) received HTTP 429 rate-limit errors and remain
unevaluated. No quality failures were observed in the eight completed cases.
Observed label variation (Piano, Piano song, Song) reinforces the need for
canonical topic matching next. This is not a precision or safety benchmark.

After the provider quota resets, retry only the unfinished cases:

```bash
python3 -m server.analysis.evaluate --case f9 --case f10 --output evaluation/extraction_retry.json
```

## Canonical topic matching

GeminiExtractor now supplies match_topics in addition to extract. The public
analyze_entry signature is unchanged. Pipeline version is analysis-v3.

1. Validate extracted labels and exact evidence spans.
2. Reuse unambiguous exact topic labels/aliases without provider calls.
3. For unresolved general topics, send candidate labels, evidence, the entry,
   and the small active general-topic registry to Gemini.
4. Make a second independent grounded decision without revealing the first.
   Reuse an ID only if both choose the same active compatible ID. Agreement
   is a heuristic, not proof of correct identity or a confidence score.
5. Return the registry's canonical label. Combine mentions that resolve to one
   ID, preserving distinct evidence spans. New/ambiguous candidates keep a null
   topic_id; people remain candidates pending identity-aware/user resolution.

Example: Playing piano and Piano practice can resolve to existing ID piano,
label Piano. A related concept such as Music should not be merged just because
it is related. Hidden topics still participate; merged source records do not.
Track A must recheck redirects/aliases and user corrections in its registry lock
before persistence. This function creates no topic IDs, aliases, or database rows.
New candidates are not semantically clustered against one another in this step.

No new configuration is needed. Gemini matching is enabled automatically by
configure_extractor(GeminiExtractor()). Fixture extractors without match_topics
continue to use exact matching only. Unresolved candidates plus a nonempty
registry add two API calls per entry (batched across candidates). Provider errors
propagate to Track A; malformed matching responses fail rather than silently
publishing a guessed match. Large registries need embedding retrieval later.
Goal labels are not yet canonical goals and goal-event/topic linking remains open.

Tests cover paraphrase agreement, disagreement, unknown/merged IDs, person
separation, canonical labels, evidence deduplication, and pipeline wiring.
Live semantic quality has not been measured; previous evaluation reports use
older pipeline versions and do not validate this new matching stage.
