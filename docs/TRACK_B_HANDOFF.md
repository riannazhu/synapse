# Track B handoff to A and C

The analysis signature requires entry_date and revision as keyword-only args.
The result version is analysis-v4; inspect analysis.schema.json and its examples.
Fixture IDs are readable strings; production IDs follow A's UUID schema.

## Track A

1. Derive identity from authentication. Configure build_models(mode) once at
   server startup. Fixture is default; live is explicit, never an error fallback.
2. Implement AnalysisRepository and CaptureRepository in server/jobs/handlers
   against your persistent database/worker. Read only owned, live approved current
   revisions; extracted media is never approval.
3. Before publication, atomically lock entry and topic registry and check the
   current unexpired lease token, revision and tombstone. Reconcile latest
   aliases/redirects before creating topics. Do not create person name aliases.
4. Persist revision-bound passages, embedding version/dimension, mentions with
   exact quotes and passage IDs, and pending goal proposals. Apply user overrides;
   edits flag stale overrides for review. Goal labels are not confirmed goals.
5. Replace analysis idempotently, increment corpus_version, persist new layout,
   invalidate reports/insights, and enqueue a deduplicated refresh transactionally.
   Increment topic_version for registry changes and layout_version for explicit
   reorganization. MemoryRepository's refresh_keys are not a durable queue.
6. Run inference outside DB locks. ProviderError.retryable classifies transient
   provider failures; ValueError is terminal validation failure. A owns lease
   renewals, backoff/jitter, cancellation, rate limits and source invalidation.
7. Materialize an authorized consistent snapshot for GraphService: topics,
   entries, mentions, optional goal_events and version counters. Entry rows have
   id/user_id/revision/entry_date/text/approved/deleted/analysis_status. Mentions
   have id/user_id/entry_id/revision/topic_id/start/end/quote. Topics have
   id/user_id/label/kind, optional aliases/hidden/merged_into, and persisted x/y.
8. Expose graph/comparison/evidence/trend/timeline and correction routes; paginate
   supporting entries at the API boundary. Apply correction transforms under
   version checks and registry locks. Generate split-target layout before reads.
9. Revalidate source evidence when needed on read. Never trust client ownership,
   approval, revision or media metadata. A validates signatures/decoded duration,
   authorizes private media, and handles deletion/invalidation. C requires review.
10. Temporary Gemini upload deletion is attempted in finally; monitor redacted
    cleanup warnings and retry cleanup. No journal text or keys belong in logs.

The memory fixture demonstrates revision/pipeline idempotency. Explicit same-
revision reanalysis after a correction must mark analysis queued first. A's
production generation key and transaction supersede the in-process fixture.
No migration or persistent worker runtime is implemented by B.

## Track C

Run python3 -m server.demo for JSON fixtures. graph_three_entries.json contains
the exact LLD counts; graph.json contains five entries; comparison.json supplies
synchronized panels. Evidence, trends, goals and capture-review fixtures are in
the same directory.

Edges use shared_entry_count, not weight. Shares use analyzed_entries; show
pending_entries/failed_entries. Zero-count nodes have brightness=0 and should be
outlined; empty-period shares are null. Do not recompute layout on date changes.

Capture tokens are explicit mocks, not playable audio/images. Unknown topic IDs
stay null until A creates or resolves them. Offsets are Unicode code points;
JavaScript indices are UTF-16, so use Array.from(text) or equivalent conversion.

## Integration acceptance

Connect authenticated save → worker → graph → evidence, then real capture review.
Evaluate actual model faithfulness, false merges, identity, dates, noisy audio,
and illegible handwriting. Offline passes are plumbing checks, not provider
quality or proof of production access isolation. Shared Track D adds check-ups,
confirmed goal-state transitions and Wrapped over these evidence/metric inputs.
