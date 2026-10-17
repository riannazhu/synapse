BEGIN;
-- Global project budget, deliberately not journal/user content.
CREATE TABLE provider_budget (
 model text PRIMARY KEY, last_request_at timestamptz NOT NULL,
 quota_day date NOT NULL, requests integer NOT NULL DEFAULT 0
);
ALTER TABLE provider_budget ENABLE ROW LEVEL SECURITY;
ALTER TABLE provider_budget FORCE ROW LEVEL SECURITY;
REVOKE ALL ON provider_budget FROM PUBLIC, anon, authenticated;
COMMIT;
