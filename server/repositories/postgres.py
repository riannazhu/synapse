"""All request transactions carry authenticated owner scope; no provider calls inside locks."""
from contextlib import contextmanager
import hashlib
import json
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

class DomainError(Exception):
    def __init__(self, status, code, message, retryable=False):
        self.status, self.code, self.message, self.retryable = status, code, message, retryable

def fail(status, code, message):
    raise DomainError(status, code, message)

class Repository:
    def __init__(self, database_url):
        self.database_url = database_url

    @contextmanager
    def transaction(self, owner):
        with psycopg.connect(self.database_url, row_factory=dict_row) as db:
            db.execute("SELECT set_config('app.user_id', %s, true)", (str(owner),))
            db.execute('INSERT INTO user_state(user_id) VALUES (%s) ON CONFLICT DO NOTHING', (owner,))
            # Serializes mutations/analysis publication within one account, never across accounts.
            db.execute('SELECT * FROM user_state WHERE user_id=%s FOR UPDATE', (owner,))
            yield db

    def entry(self, db, owner, entry_id):
        row = db.execute('SELECT * FROM entries WHERE user_id=%s AND id=%s AND deleted_at IS NULL FOR UPDATE',
                         (owner, entry_id)).fetchone()
        if row is None:
            fail(404, 'not_found', 'Entry not found')
        return row

    def attachment(self, db, owner, attachment_id):
        row = db.execute('SELECT a.* FROM attachments a JOIN entries e ON e.id=a.entry_id AND e.user_id=a.user_id WHERE a.user_id=%s AND a.id=%s AND a.deleted_at IS NULL AND e.deleted_at IS NULL FOR UPDATE OF a',
                         (owner, attachment_id)).fetchone()
        if row is None:
            fail(404, 'not_found', 'Attachment not found')
        return row

    def enqueue(self, db, owner, kind, key, entry_id=None, revision=None, attachment_id=None, payload=None):
        row = db.execute('''INSERT INTO jobs(id,user_id,type,dedupe_key,entry_id,revision,attachment_id,payload)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,dedupe_key)
            DO UPDATE SET dedupe_key=EXCLUDED.dedupe_key RETURNING id''',
            (uuid4(),owner,kind,key,entry_id,revision,attachment_id,Jsonb(payload or {}))).fetchone()
        return str(row['id'])

    def invalidate(self, db, owner, entry_id):
        db.execute('UPDATE user_state SET corpus_version=corpus_version+1 WHERE user_id=%s', (owner,))
        db.execute("UPDATE derived_documents SET status='stale' WHERE user_id=%s", (owner,))
        db.execute('UPDATE topic_overrides SET review_needed=true WHERE user_id=%s AND entry_id=%s', (owner,entry_id))
        db.execute("UPDATE jobs SET status='cancelled',lease_token=NULL,lease_until=NULL WHERE user_id=%s AND entry_id=%s AND status IN ('queued','running') AND type NOT LIKE 'PURGE%%'", (owner,entry_id))

    def mutate(self, owner, route, key, body, operation):
        if not key or len(key) > 200:
            fail(422, 'idempotency_key_required', 'Supply an Idempotency-Key of 1–200 characters')
        digest = hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
        with self.transaction(owner) as db:
            old = db.execute('SELECT * FROM idempotency WHERE user_id=%s AND route=%s AND key=%s', (owner,route,key)).fetchone()
            if old:
                if old['body_hash'] != digest:
                    fail(409,'idempotency_conflict','Key already used with a different body')
                return old['status'], old['response']
            status, result = operation(db)
            # Persist wire representation so retries return exactly the same values.
            result = json.loads(json.dumps(result,default=str)) if result is not None else None
            db.execute('INSERT INTO idempotency VALUES (%s,%s,%s,%s,%s,%s)', (owner,route,key,digest,status,Jsonb(result)))
            return status,result
