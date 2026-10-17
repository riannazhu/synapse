"""Durable queue runtime. Handler calls run outside DB locks and must be side-effect free.

Handlers: callable(context) -> JSON dict. Register with runtime.register(type, handler).
Runtime alone publishes results after checking ownership, revision and lease.
"""
import importlib
import json
import os
import random
import threading
import time
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from server.config import Settings
from server.repositories.postgres import Repository, DomainError
from server.media import MediaStore

class RetryableError(Exception):
    """B raises only for transient provider/network failures. Message is never logged."""
    def __init__(self, *, retry_after=None):
        super().__init__('Transient provider failure')
        self.retry_after=retry_after

class Runtime:
    def __init__(self, settings, repository=None, media=None):
        self.settings=settings
        self.repo=repository or Repository(settings.database_url)
        self.media=media or MediaStore(settings)
        self.handlers={}
        self.register('PURGE_OBJECT',lambda ctx: self._purge_object(ctx))
        self.register('PURGE_ENTRY',lambda ctx: self._purge_entry(ctx))

    def register(self, kind, handler):
        if kind in self.handlers: raise ValueError('Handler already registered')
        self.handlers[kind]=handler

    def claim(self):
        # Queue dispatcher needs a trusted table-owner/BYPASSRLS connection to select
        # across accounts. Every handler read/publication then establishes owner scope.
        with psycopg.connect(self.settings.database_url,row_factory=dict_row) as db:
            db.execute('SELECT pg_advisory_xact_lock(72813619)')
            active=db.execute("SELECT count(*) AS n FROM jobs WHERE status='running' AND lease_until>now()").fetchone()['n']
            if active>=int(os.getenv('GLOBAL_JOB_CONCURRENCY','8')): return None
            row=db.execute("""SELECT j.* FROM jobs j WHERE
                ((j.status='queued' AND j.available_at<=now()) OR (j.status='running' AND j.lease_until<now()))
                AND (SELECT count(*) FROM jobs a WHERE a.user_id=j.user_id AND a.status='running' AND a.lease_until>now())<2
                ORDER BY j.available_at,j.created_at FOR UPDATE SKIP LOCKED LIMIT 1""").fetchone()
            if row is None: return None
            token=uuid4()
            db.execute("UPDATE jobs SET status='running',attempt=attempt+1,lease_token=%s,lease_until=now()+interval '90 seconds',progress_stage='running' WHERE id=%s",(token,row['id']))
            row.update(lease_token=token,status='running',attempt=row['attempt']+1)
            return row

    def renew(self,job):
        with psycopg.connect(self.settings.database_url) as db:
            return db.execute("UPDATE jobs SET lease_until=now()+interval '90 seconds' WHERE user_id=%s AND id=%s AND lease_token=%s AND status='running' AND lease_until>now()",(job['user_id'],job['id'],job['lease_token'])).rowcount==1

    def context(self,job):
        owner=job['user_id']
        with self.repo.transaction(owner) as db:
            ctx={'job':job,'media':self.media}
            if job['type'].startswith('PURGE'): return ctx
            if job['entry_id']:
                e=self.repo.entry(db,owner,job['entry_id'])
                if job['revision'] and e['current_revision']!=job['revision']:
                    raise DomainError(409,'stale_revision','Revision changed')
                ctx['entry']=e
            if job['revision']:
                ctx['revision']=db.execute('SELECT * FROM entry_revisions WHERE user_id=%s AND entry_id=%s AND revision=%s',(owner,job['entry_id'],job['revision'])).fetchone()
                ctx['topics']=db.execute('SELECT * FROM topics WHERE user_id=%s',(owner,)).fetchall()
                # UUIDs converted for Track B’s strict string ID validation.
                ctx['topics']=json.loads(json.dumps(ctx['topics'],default=str))
                db.execute("UPDATE entry_revisions SET analysis_status='running' WHERE user_id=%s AND entry_id=%s AND revision=%s",(owner,job['entry_id'],job['revision']))
            if job['attachment_id']: ctx['attachment']=self.repo.attachment(db,owner,job['attachment_id'])
            if job['type'] in ('CHAT_REPLY','CHAT_DRAFT'):
                sid=job['payload']['session_id']
                session=db.execute('SELECT * FROM conversations WHERE user_id=%s AND id=%s',(owner,sid)).fetchone()
                if not session: raise ValueError('Conversation removed')
                ctx['conversation']=session
                through=job['payload'].get('through_sequence',2147483647)
                ctx['messages']=db.execute('SELECT id,role,text,sequence FROM messages WHERE user_id=%s AND session_id=%s AND sequence<=%s ORDER BY sequence',(owner,sid,through)).fetchall()
                if job['type']=='CHAT_DRAFT': ctx['messages']=[m for m in ctx['messages'] if m['role']=='user']
                # No history is retrieved here. B must explicitly request scoped retrieval
                # through a future bounded adapter when history_enabled is true.

            return ctx

    def finish(self,job,result=None,error=None):
        owner=job['user_id']
        with self.repo.transaction(owner) as db:
            live=db.execute("SELECT * FROM jobs WHERE user_id=%s AND id=%s AND status='running' AND lease_token=%s AND lease_until>now() FOR UPDATE",(owner,job['id'],job['lease_token'])).fetchone()
            if not live: return False
            stale=False
            if not job['type'].startswith('PURGE') and job['entry_id']:
                e=db.execute('SELECT * FROM entries WHERE user_id=%s AND id=%s AND deleted_at IS NULL',(owner,job['entry_id'])).fetchone()
                stale=not e or (job['revision'] and e['current_revision']!=job['revision'])
            if not stale and job['attachment_id']:
                a=db.execute('SELECT * FROM attachments WHERE user_id=%s AND id=%s AND deleted_at IS NULL',(owner,job['attachment_id'])).fetchone()
                stale=not a
            if stale:
                db.execute("UPDATE jobs SET status='cancelled',lease_token=NULL,lease_until=NULL WHERE id=%s AND user_id=%s",(job['id'],owner))
                return False
            if error is not None:
                retry=isinstance(error,RetryableError) and job['attempt']<=3
                delay=[5,30,120][min(job['attempt']-1,2)]+random.uniform(0,1)
                if isinstance(error,RetryableError) and error.retry_after is not None:
                    delay=max(delay,min(max(error.retry_after,0),86400))
                code='provider_transient' if isinstance(error,RetryableError) else 'handler_failed'
                db.execute("UPDATE jobs SET status=%s,error_code=%s,progress_stage=%s,available_at=now()+(%s * interval '1 second'),lease_token=NULL,lease_until=NULL WHERE user_id=%s AND id=%s",('queued' if retry else 'failed',code,'retry_wait' if retry else 'failed',delay,owner,job['id']))
                if job['revision']: db.execute('UPDATE entry_revisions SET analysis_status=%s WHERE user_id=%s AND entry_id=%s AND revision=%s',('queued' if retry else 'failed',owner,job['entry_id'],job['revision']))
                if job['attachment_id']: db.execute('UPDATE attachments SET state=%s,error_code=%s WHERE user_id=%s AND id=%s',('processing' if retry else 'failed',code,owner,job['attachment_id']))
                return True
            if job['type'] in ('CHAT_REPLY','CHAT_DRAFT'):
                sid=job['payload']['session_id']
                session=db.execute('SELECT id FROM conversations WHERE user_id=%s AND id=%s',(owner,sid)).fetchone()
                if not session:
                    db.execute("UPDATE jobs SET status='cancelled',lease_token=NULL,lease_until=NULL WHERE user_id=%s AND id=%s",(owner,job['id']))
                    return False
                if job['type']=='CHAT_REPLY':
                    if not isinstance(result,dict) or not isinstance(result.get('text'),str): raise ValueError('Reply requires text')
                    seq=db.execute('SELECT coalesce(max(sequence),0)+1 AS n FROM messages WHERE user_id=%s AND session_id=%s',(owner,sid)).fetchone()['n']
                    db.execute("INSERT INTO messages(id,user_id,session_id,role,text,sequence) VALUES (%s,%s,%s,'assistant',%s,%s)",(uuid4(),owner,sid,result['text'],seq))
                else:
                    if not isinstance(result,dict) or not isinstance(result.get('draft_text'),str) or not isinstance(result.get('user_message_ids'),list): raise ValueError('Invalid draft')
                    ids={str(m['id']) for m in db.execute("SELECT id FROM messages WHERE user_id=%s AND session_id=%s AND role='user' AND sequence<=%s",(owner,sid,job['payload']['through_sequence'])).fetchall()}
                    if not set(result['user_message_ids'])<=ids: raise ValueError('Assistant/foreign summary evidence')
                    result={**result,'source_sequence':job['payload']['through_sequence']}
            if job['type']=='ANALYZE_ENTRY':
                self.publish_analysis(db,job,result)
            elif job['type']=='EXTRACT_MEDIA':
                if not isinstance(result,dict) or not isinstance(result.get('text'),str):
                    raise ValueError('Extraction handler requires text')
                db.execute("UPDATE attachments SET state='needs_review',extraction=%s,error_code=NULL WHERE user_id=%s AND id=%s",(Jsonb(result),owner,job['attachment_id']))
            db.execute("UPDATE jobs SET status='succeeded',result=%s,progress_stage='succeeded',error_code=NULL,lease_token=NULL,lease_until=NULL WHERE user_id=%s AND id=%s",(Jsonb(result),owner,job['id']))
            return True

    def publish_analysis(self,db,job,result):
        from server.analysis.service import _spans
        owner=job['user_id']
        r=db.execute('SELECT * FROM entry_revisions WHERE user_id=%s AND entry_id=%s AND revision=%s',(owner,job['entry_id'],job['revision'])).fetchone()
        if not isinstance(result,dict) or result.get('entry_id')!=str(job['entry_id']): raise ValueError('Invalid analysis entry ID')
        if result.get('revision')!=job['revision'] or result.get('entry_date')!=r['entry_date'].isoformat(): raise ValueError('Analysis revision/date mismatch')
        if result.get('pipeline_version')!=r['pipeline_version']: raise ValueError('Pipeline version mismatch')
        if not isinstance(result.get('topics'),list) or not isinstance(result.get('goal_events'),list) or not isinstance(result.get('passages'),list): raise ValueError('Invalid analysis lists')
        text=r['approved_text']
        for p in result['passages']:
            _spans([{'start':p['start'],'end':p['end'],'quote':p['text']}],text)
        topics=db.execute('SELECT * FROM topics WHERE user_id=%s',(owner,)).fetchall()
        by_id={str(t['id']):t for t in topics}
        aliases={}
        for t in topics:
            if t['merged_into'] or t['kind']=='person': continue
            for alias in [t['label'],*t['aliases']]: aliases.setdefault(alias.strip().casefold(),set()).add(str(t['id']))
        overrides=db.execute('SELECT * FROM topic_overrides WHERE user_id=%s AND entry_id=%s',(owner,job['entry_id'])).fetchall()
        excluded={str(o['topic_id']) for o in overrides if o['action']=='exclude' and not o['review_needed'] and o['source_revision']==job['revision']}
        assignments=[]
        for candidate in result['topics']:
            _spans(candidate['evidence_spans'],text)
            if candidate.get('kind') not in ('topic','person') or not isinstance(candidate.get('label'),str) or not candidate['label'].strip(): raise ValueError('Invalid topic')
            tid=candidate.get('topic_id')
            if tid:
                seen=set()
                while tid in by_id and by_id[tid]['merged_into']:
                    if tid in seen: raise ValueError('Topic redirect cycle')
                    seen.add(tid); tid=str(by_id[tid]['merged_into'])
                if tid not in by_id or by_id[tid]['kind']!=candidate['kind']: raise ValueError('Foreign or incompatible topic')
            else:
                matches=aliases.get(candidate['label'].strip().casefold(),set()) if candidate['kind']=='topic' else set()
                if len(matches)==1: tid=next(iter(matches))
                else:
                    tid=str(uuid4())
                    db.execute('INSERT INTO topics(id,user_id,label,kind) VALUES (%s,%s,%s,%s)',(tid,owner,candidate['label'],candidate['kind']))
                    if candidate['kind']=='topic': aliases.setdefault(candidate['label'].strip().casefold(),set()).add(tid)
            if tid not in excluded: assignments.append({**candidate,'topic_id':tid})
        for event in result['goal_events']:
            if event.get('review_status')!='pending' or event.get('type') not in ('intention','practice','milestone'): raise ValueError('Invalid goal proposal')
            _spans(event['evidence_spans'],text)
        result={**result,'topics':assignments}
        db.execute("UPDATE entry_revisions SET analysis_status='succeeded',analysis_result=%s WHERE user_id=%s AND entry_id=%s AND revision=%s",(Jsonb(result),owner,job['entry_id'],job['revision']))
        db.execute('UPDATE user_state SET corpus_version=corpus_version+1 WHERE user_id=%s',(owner,))
        db.execute("UPDATE derived_documents SET status='stale' WHERE user_id=%s",(owner,))

    def run_once(self):
        job=self.claim()
        if not job: return False
        stop=threading.Event()
        def heartbeat():
            while not stop.wait(20):
                try:
                    if not self.renew(job): return
                except Exception: return
        thread=threading.Thread(target=heartbeat,daemon=True); thread.start()
        try:
            if job['attempt']>4: raise ValueError('Retry budget exhausted')
            ctx=self.context(job)
            handler=self.handlers.get(job['type'])
            if handler is None: raise ValueError('No handler registered')
            result=handler(ctx)
            self.finish(job,result=result)
        except Exception as exc:
            self.finish(job,error=exc)
        finally:
            stop.set(); thread.join(timeout=1)
        return True

    def cleanup_abandoned(self):
        # No journal text fetched by dispatcher. Each cleanup uses scoped locks.
        with psycopg.connect(self.settings.database_url,row_factory=dict_row) as db:
            rows=db.execute("SELECT user_id,id FROM attachments WHERE deleted_at IS NULL AND state='uploading' AND created_at<now()-interval '24 hours' LIMIT 100").fetchall()
        for row in rows:
            with self.repo.transaction(row['user_id']) as db:
                a=db.execute("SELECT * FROM attachments WHERE user_id=%s AND id=%s AND deleted_at IS NULL AND state='uploading' FOR UPDATE",(row['user_id'],row['id'])).fetchone()
                if not a: continue
                db.execute("UPDATE attachments SET deleted_at=now(),upload_token_hash=NULL WHERE user_id=%s AND id=%s",(row['user_id'],row['id']))
                self.repo.enqueue(db,row['user_id'],'PURGE_OBJECT',f'abandoned:{row["id"]}',payload={'object_key':a['object_key']})
        return len(rows)

    def _purge_object(self,ctx):
        try: self.media.delete(ctx['job']['payload']['object_key'])
        except Exception as exc: raise RetryableError() from exc
        return {'purged':True}

    def _purge_entry(self,ctx):
        j=ctx['job']; owner=j['user_id']
        with self.repo.transaction(owner) as db:
            attachments=db.execute('SELECT object_key FROM attachments WHERE user_id=%s AND entry_id=%s',(owner,j['entry_id'])).fetchall()
        for a in attachments:
            try: self.media.delete(a['object_key'])
            except Exception as exc: raise RetryableError() from exc
        with self.repo.transaction(owner) as db:
            db.execute('DELETE FROM conversations WHERE user_id=%s AND entry_id=%s',(owner,j['entry_id']))
            db.execute('DELETE FROM entry_revisions WHERE user_id=%s AND entry_id=%s',(owner,j['entry_id']))
            db.execute("UPDATE jobs SET payload='{}',result=NULL WHERE user_id=%s AND entry_id=%s",(owner,j['entry_id']))
            # Idempotent responses may retain an upload capability, never journal text.
            db.execute('DELETE FROM idempotency WHERE user_id=%s AND route LIKE %s',(owner,f'%{j["entry_id"]}%'))
            db.execute("UPDATE attachments SET extraction=NULL,checksum='',upload_token_hash=NULL WHERE user_id=%s AND entry_id=%s",(owner,j['entry_id']))
        return {'purged':True}


def register_analysis(runtime):
    from server.analysis import analyze_entry
    def analyze(ctx):
        r=ctx['revision']
        return analyze_entry(str(r['entry_id']),r['approved_text'],ctx['topics'],entry_date=r['entry_date'].isoformat(),revision=r['revision'])
    runtime.register('ANALYZE_ENTRY',analyze)


def main():
    runtime=Runtime(Settings.load())
    register_analysis(runtime)
    if os.getenv('HANDLER_MODULE'):
        importlib.import_module(os.environ['HANDLER_MODULE']).register(runtime)
    # Separate processes can safely run this loop; DB enforces shared concurrency.
    last_cleanup=0
    try:
        while True:
            if time.monotonic()-last_cleanup>3600:
                runtime.cleanup_abandoned(); last_cleanup=time.monotonic()
            if not runtime.run_once(): time.sleep(1)
    except KeyboardInterrupt: return

if __name__=='__main__': main()
