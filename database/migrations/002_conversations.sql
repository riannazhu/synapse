BEGIN;
CREATE TABLE conversations (
 id uuid PRIMARY KEY, user_id uuid NOT NULL, entry_id uuid NOT NULL,
 history_enabled boolean NOT NULL DEFAULT false, retain_transcript boolean NOT NULL DEFAULT false,
 UNIQUE(user_id,id), FOREIGN KEY(user_id,entry_id) REFERENCES entries(user_id,id) ON DELETE CASCADE
);
CREATE TABLE messages (
 id uuid PRIMARY KEY, user_id uuid NOT NULL, session_id uuid NOT NULL,
 role text NOT NULL CHECK(role IN ('user','assistant')), text text NOT NULL,
 sequence integer NOT NULL, client_message_id uuid, UNIQUE(session_id,sequence),
 UNIQUE(user_id,session_id,client_message_id),
 FOREIGN KEY(user_id,session_id) REFERENCES conversations(user_id,id) ON DELETE CASCADE
);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['conversations','messages'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY owner_scope ON %I USING(user_id=public.synapse_owner()) WITH CHECK(user_id=public.synapse_owner())',t);
  EXECUTE format('REVOKE ALL ON %I FROM anon,authenticated',t);
 END LOOP;
END $$;
COMMIT;
