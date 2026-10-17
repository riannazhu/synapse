# Track A setup and implementation details

The backend foundation is implemented locally. Supabase provisioning, live
integration verification, and deployment are still pending; Track A is not yet
complete end to end.

### Current progress

- Added PostgreSQL migrations for entries, immutable revisions, attachments,
  persisted jobs, topics, overrides, conversations/messages, idempotency,
  versioned derived documents, and a shared Gemini request budget.
- Added account-scoped repository queries, database row-level policies,
  composite owner foreign keys, and Supabase JWT verification of signature,
  issuer, audience, and expiry. Foreign entry/media/job IDs return 404.
- Added entry create/read/list/delete, version-checked draft updates, and explicit
  approval/commit routes. Commit freezes selected reviewed blocks and enqueues
  analysis in the same transaction; edits invalidate older analysis immediately.
- Added private media upload authorization, byte/checksum/type validation,
  extraction completion/status/retry, short-lived playback URLs, and deletion.
  Upload authorization expires after ten minutes; playback URLs after one minute.
  Audio validation requires `ffprobe`.
- Added a persistent worker with 90-second leases, 20-second renewal, unique lease
  tokens, expired-lease recovery, bounded transient retries, per-user/global
  concurrency limits, and manual retry/status endpoints. Late results cannot
  overwrite a newer revision or restore deleted evidence.
- Added deletion/purge jobs and hourly cleanup of uploads abandoned for 24 hours.
  Removing media used by the current revision requires first committing reviewed
  text-only or remaining blocks, so approved source removal is explicit.
- Added conversation/message persistence and reply/draft jobs. Draft summaries
  receive user messages only and never save an entry automatically. Conversations
  without transcript retention are removed on entry commit.
- Added graph/comparison/topic-detail service hooks and version-checked topic
  rename/hide. Graph calculation remains Track B's responsibility; missing
  services return a visible 503 instead of fabricated graph data.
- Added shared Python/JSON contracts, a checked-in OpenAPI specification, a
  container definition, environment template, and dependency lockfile.

## Setup

1. Create a Supabase project, configure Auth providers and redirects, and use
   ES256/RS256 JWT signing (the API verifies the project's JWKS).
2. Run the three SQL files in `database/migrations` once each, in numeric order.
   The first creates the private `journal-media` bucket. Migrations are not
   automatically applied. Use a trusted database role with BYPASSRLS for the
   cross-account worker dispatcher; all handler operations establish owner scope.
3. Copy `.env.example` to `.env` if needed, preserving any existing local secrets.
   Supply `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
   `API_PUBLIC_URL`, `CORS_ORIGINS`, and `GEMINI_API_KEY`. Use
   `PIPELINE_VERSION=analysis-v4`, `GEMINI_MODEL=gemini-2.5-flash`, and
   `HANDLER_MODULE=server.providers.gemini`. Never commit `.env`.
4. Install Python 3.12 and FFmpeg (`ffprobe` validates audio). Install and run:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.lock.txt
   set -a
   source .env
   set +a
   .venv/bin/uvicorn server.api.app:create_app --factory --no-access-log
   ```

   In another terminal, load the same environment and run
   `.venv/bin/python -m server.jobs.runtime.worker`.
5. Frontend requests use `/api/v1`, a Supabase bearer access token, and a unique
   `Idempotency-Key` per mutation. Retry identical requests with the same key.
   Upload bytes using authenticated PUT to the returned upload URL, then POST
   completion. Open `/docs` for endpoint details.
6. Set `SERVICE_MODULE` to a Python module exporting a `services` dictionary with
   `graph`, `graph_compare`, and `topic_detail` functions. These receive an
   owner-scoped snapshot of revisions, topics, and versions. Adapting this shape
   to B's GraphService and persisting its layout remain follow-up work. Until
   configured, these endpoints return 503. The runtime publication boundary owns
   leases and database writes; B's separate repository-protocol handlers are not
   registered automatically.
7. Deploy API and worker separately; apply migrations first. Configure HTTPS,
   origins, storage/backup retention, and disable access logs containing tokens or
   private URLs. Verify two-account isolation and save/edit/media/delete flows
   with live Supabase and Gemini before exposing the application.

## Gemini free-tier behavior

The backend adapter always calls the configured Gemini model for approved user
content; it never substitutes test fixtures. B's standalone offline demos remain
available separately. Application defaults allow four requests per minute and
20 per day, shared across workers through PostgreSQL. These are conservative
budgets, not Google's quota guarantees; adjust to the project's AI Studio limits.
429/network/provider failures queue bounded retries and then remain visible for
manual retry. No paid-model fallback is used. Large media uses temporary provider
files, deleted best-effort after processing. Precise audio/page coordinates remain
unimplemented. Read Google's free-tier data-use terms before personal journal use.

## Verification and remaining work

Install `requirements-dev.txt`, then run
`.venv/bin/python -m unittest discover -s tests -v`. The combined A/B suite passed
74 tests locally using temporary PostgreSQL and mocked model responses. No live
Supabase/Gemini smoke test was performed.

Analysis is stored in revision JSON. Normalized evidence/embedding persistence,
advanced topic corrections, graph wiring/layout persistence, precise media
provenance, and the shared Track D goal/check-up/report APIs remain unfinished.
