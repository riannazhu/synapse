BEGIN;
CREATE TABLE user_state (
 user_id uuid PRIMARY KEY REFERENCES auth.users(id), timezone text NOT NULL DEFAULT 'UTC',
 corpus_version bigint NOT NULL DEFAULT 0, topic_version bigint NOT NULL DEFAULT 0,
 layout_version bigint NOT NULL DEFAULT 0
);
CREATE TABLE entries (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES auth.users(id),
 entry_date date NOT NULL, mode text NOT NULL CHECK(mode IN ('text','chat','voice','handwriting')),
 draft_version integer NOT NULL DEFAULT 1, blocks jsonb NOT NULL DEFAULT '[]',
 current_revision integer, deleted_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE(user_id,id)
);
CREATE TABLE entry_revisions (
 user_id uuid NOT NULL, entry_id uuid NOT NULL, revision integer NOT NULL,
 approved_text text NOT NULL CHECK(length(approved_text) BETWEEN 1 AND 50000),
 content_hash text NOT NULL, entry_date date NOT NULL, blocks jsonb NOT NULL,
 source_modes text[] NOT NULL, analysis_status text NOT NULL DEFAULT 'queued'
 CHECK(analysis_status IN ('queued','running','succeeded','failed')),
 pipeline_version text NOT NULL, analysis_result jsonb,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(entry_id,revision),
 UNIQUE(user_id,entry_id,revision), FOREIGN KEY(user_id,entry_id) REFERENCES entries(user_id,id) ON DELETE CASCADE
);
CREATE TABLE attachments (
 id uuid PRIMARY KEY, user_id uuid NOT NULL, entry_id uuid NOT NULL,
 object_key text NOT NULL UNIQUE, mime_type text NOT NULL, byte_size bigint NOT NULL,
 checksum text NOT NULL, state text NOT NULL DEFAULT 'uploading',
 upload_token_hash text, upload_expires_at timestamptz, extraction_version integer NOT NULL DEFAULT 1,
 extraction jsonb, error_code text, deleted_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(user_id,id), FOREIGN KEY(user_id,entry_id) REFERENCES entries(user_id,id) ON DELETE CASCADE
);
CREATE TABLE jobs (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES auth.users(id), type text NOT NULL,
 entry_id uuid, revision integer, attachment_id uuid, payload jsonb NOT NULL DEFAULT '{}',
 dedupe_key text NOT NULL, status text NOT NULL DEFAULT 'queued'
 CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
 attempt integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
 lease_until timestamptz, lease_token uuid, progress_stage text NOT NULL DEFAULT 'queued',
 error_code text, result jsonb, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(user_id,dedupe_key), UNIQUE(user_id,id),
 FOREIGN KEY(user_id,entry_id) REFERENCES entries(user_id,id) ON DELETE CASCADE,
 FOREIGN KEY(user_id,attachment_id) REFERENCES attachments(user_id,id) ON DELETE CASCADE
);
CREATE TABLE idempotency (
 user_id uuid NOT NULL REFERENCES auth.users(id), route text NOT NULL, key text NOT NULL,
 body_hash text NOT NULL, status integer NOT NULL, response jsonb,
 PRIMARY KEY(user_id,route,key)
);
CREATE TABLE topics (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES auth.users(id), label text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('topic','person')), aliases jsonb NOT NULL DEFAULT '[]',
 hidden boolean NOT NULL DEFAULT false, merged_into uuid, x double precision, y double precision,
 UNIQUE(user_id,id), FOREIGN KEY(user_id,merged_into) REFERENCES topics(user_id,id)
);
CREATE TABLE topic_overrides (
 user_id uuid NOT NULL, entry_id uuid NOT NULL, topic_id uuid NOT NULL,
 action text NOT NULL CHECK(action IN ('include','exclude')), source_revision integer NOT NULL,
 review_needed boolean NOT NULL DEFAULT false, PRIMARY KEY(user_id,entry_id,topic_id),
 FOREIGN KEY(user_id,entry_id) REFERENCES entries(user_id,id) ON DELETE CASCADE,
 FOREIGN KEY(user_id,topic_id) REFERENCES topics(user_id,id)
);
CREATE TABLE derived_documents (
 id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES auth.users(id), kind text NOT NULL,
 status text NOT NULL, corpus_version bigint NOT NULL, topic_version bigint NOT NULL,
 payload jsonb NOT NULL DEFAULT '{}', UNIQUE(user_id,id)
);
CREATE INDEX entries_owner_date ON entries(user_id,entry_date,id) WHERE deleted_at IS NULL;
CREATE INDEX attachments_entry ON attachments(user_id,entry_id);
CREATE INDEX jobs_claim ON jobs(status,available_at,lease_until);
CREATE INDEX revisions_owner ON entry_revisions(user_id,entry_id,revision);
-- API sets app.user_id inside each transaction. auth.uid() supports direct authenticated access.
CREATE FUNCTION public.synapse_owner() RETURNS uuid LANGUAGE sql STABLE AS $$
 SELECT coalesce(nullif(current_setting('app.user_id',true),'' )::uuid, auth.uid())
$$;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['user_state','entries','entry_revisions','attachments','jobs','idempotency','topics','topic_overrides','derived_documents'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY owner_scope ON %I USING (user_id = public.synapse_owner()) WITH CHECK (user_id = public.synapse_owner())',t);
  -- Browser clients use HTTP API, never mutate internal records through PostgREST.
  EXECUTE format('REVOKE ALL ON %I FROM anon, authenticated',t);
 END LOOP;
END $$;
INSERT INTO storage.buckets(id,name,public,file_size_limit)
VALUES ('journal-media','journal-media',false,26214400)
ON CONFLICT(id) DO UPDATE SET public=false;
COMMIT;
