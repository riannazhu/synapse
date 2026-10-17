from datetime import date, datetime, timedelta, timezone
import base64
import importlib
import hashlib
import json
import os
import secrets
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException
from psycopg.types.json import Jsonb
from server.config import Settings
from server.repositories.postgres import Repository, DomainError, fail
from server.media import MediaStore, validate_media
from .auth import SessionVerifier
from .contracts import CreateEntry, Draft, Commit, Upload, Complete


def create_app(settings=None, repository=None, verifier=None, media=None, services=None):
    settings = settings or Settings.load()
    repo = repository or Repository(settings.database_url)
    verify = verifier or SessionVerifier(settings)
    store = media or MediaStore(settings)
    app = FastAPI(title='Synapse Track A',version='0.1.0')
    app.add_middleware(CORSMiddleware,allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173,http://localhost:3000').split(','),
                       allow_methods=['GET','POST','PATCH','PUT','DELETE'],allow_headers=['Authorization','Content-Type','Idempotency-Key'])

    @app.middleware('http')
    async def request_id(request, call_next):
        request.state.request_id=str(uuid4())
        response=await call_next(request)
        response.headers['X-Request-ID']=request.state.request_id
        return response

    def error(request,status,code,message,retryable=False):
        return JSONResponse(status_code=status,content={'error':{'code':code,'message':message,'retryable':retryable},'request_id':getattr(request.state,'request_id',str(uuid4()))})

    @app.exception_handler(DomainError)
    async def domain_error(request,exc):
        return error(request,exc.status,exc.code,exc.message,exc.retryable)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        return error(request,422,'invalid_request','Request fields do not match the API contract')

    @app.exception_handler(HTTPException)
    async def http_error(request,exc):
        return error(request,exc.status_code,'http_error','Request cannot be served')

    @app.exception_handler(Exception)
    async def internal_error(request,exc):
        # Do not return/log exception text: DB/provider errors may contain journal content.
        return error(request,500,'internal_error','Request failed',True)

    def mutate(owner,request,key,body,operation):
        status,result=repo.mutate(owner,request.url.path,key,body,operation)
        return Response(status_code=204) if status==204 else JSONResponse(status_code=status,content=result)

    def check_version(entry,expected):
        if entry['draft_version']!=expected:
            fail(409,'draft_conflict','Draft changed; reload and merge before saving')

    def validate_blocks(db,owner,entry_id,blocks):
        for b in blocks:
            if b.get('attachment_id'):
                a=repo.attachment(db,owner,b['attachment_id'])
                if str(a['entry_id'])!=str(entry_id):
                    fail(404,'not_found','Attachment not found')

    @app.post('/api/v1/entries')
    def create(body:CreateEntry,request:Request,owner:UUID=Depends(verify),key:str|None=Header(None,alias='Idempotency-Key')):
        def op(db):
            eid=uuid4()
            db.execute('INSERT INTO entries(id,user_id,entry_date,mode) VALUES (%s,%s,%s,%s)',(eid,owner,body.entry_date,body.mode))
            return 201,{'id':str(eid),'draft_version':1,'state':'draft'}
        return mutate(owner,request,key,body.model_dump(mode='json'),op)

    @app.patch('/api/v1/entries/{entry_id}/draft')
    def draft(entry_id:UUID,body:Draft,request:Request,owner:UUID=Depends(verify),key:str|None=Header(None,alias='Idempotency-Key')):
        def op(db):
            e=repo.entry(db,owner,entry_id); check_version(e,body.expected_draft_version)
            blocks=[b.model_dump(mode='json') for b in body.blocks]
            validate_blocks(db,owner,entry_id,blocks)
            db.execute('UPDATE entries SET blocks=%s,entry_date=%s,draft_version=draft_version+1,updated_at=now() WHERE user_id=%s AND id=%s',
                       (Jsonb(blocks),body.entry_date,owner,entry_id))
            return 200,{'draft_version':e['draft_version']+1}
        return mutate(owner,request,key,body.model_dump(mode='json'),op)

    @app.post('/api/v1/entries/{entry_id}/commit')
    def commit(entry_id:UUID,body:Commit,request:Request,owner:UUID=Depends(verify),key:str|None=Header(None,alias='Idempotency-Key')):
        def op(db):
            e=repo.entry(db,owner,entry_id); check_version(e,body.expected_draft_version)
            selected={str(i) for i in body.included_block_ids}
            blocks=[b for b in e['blocks'] if b['id'] in selected]
            if len(selected)!=len(body.included_block_ids) or len(blocks)!=len(selected):
                fail(422,'invalid_blocks','Included blocks must exist and be unique')
            validate_blocks(db,owner,entry_id,blocks)
            sources=set()
            for b in blocks:
                if not b.get('included',True):
                    fail(422,'excluded_block','Excluded block cannot be committed')
                if b['source_kind']!='text' and not b['reviewed']:
                    fail(422,'review_required','Review extracted and conversational text before approval')
                aid=b.get('attachment_id')
                if aid and aid in sources:
                    fail(422,'duplicate_representation','Choose one representation per attachment')
                if aid:
                    source=repo.attachment(db,owner,aid)
                    if source['state'] not in ('needs_review','ready'):
                        fail(422,'extraction_not_ready','Use a text block for manual text while extraction is unavailable')
                    sources.add(aid)
            text='\n\n'.join(b['text'] for b in blocks)
            if not text.strip() or len(text)>50000:
                fail(422,'invalid_text','Approved text must contain 1–50000 characters')
            # Exact media offsets are deliberately omitted after user editing.
            offset=0
            for b in blocks:
                b['start']=offset; b['end']=offset+len(b['text']); offset=b['end']+2
            db.execute("UPDATE jobs SET result=NULL,payload='{}' WHERE user_id=%s AND entry_id=%s AND type IN ('CHAT_REPLY','CHAT_DRAFT') AND payload->>'session_id' IN (SELECT id::text FROM conversations WHERE user_id=%s AND entry_id=%s AND NOT retain_transcript)",(owner,entry_id,owner,entry_id))
            db.execute("DELETE FROM conversations WHERE user_id=%s AND entry_id=%s AND NOT retain_transcript",(owner,entry_id))
            revision=(e['current_revision'] or 0)+1
            repo.invalidate(db,owner,entry_id)
            db.execute('INSERT INTO entry_revisions(user_id,entry_id,revision,approved_text,content_hash,entry_date,blocks,source_modes,pipeline_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (owner,entry_id,revision,text,hashlib.sha256(text.encode()).hexdigest(),e['entry_date'],Jsonb(blocks),sorted({b['source_kind'] for b in blocks}),settings.pipeline_version))
            db.execute('UPDATE entries SET current_revision=%s,draft_version=draft_version+1,updated_at=now() WHERE user_id=%s AND id=%s',(revision,owner,entry_id))
            job=repo.enqueue(db,owner,'ANALYZE_ENTRY',f'analysis:{entry_id}:{revision}:{settings.pipeline_version}',entry_id,revision,payload={'pipeline_version':settings.pipeline_version})
            return 202,{'revision':revision,'draft_version':e['draft_version']+1,'analysis_status':'queued','job_id':job}
        return mutate(owner,request,key,body.model_dump(mode='json'),op)

    @app.get('/api/v1/entries/{entry_id}')
    def get_entry(entry_id:UUID,owner:UUID=Depends(verify)):
        with repo.transaction(owner) as db:
            e=repo.entry(db,owner,entry_id)
            e['attachments']=db.execute('SELECT id,mime_type,byte_size,state,extraction_version,error_code FROM attachments WHERE user_id=%s AND entry_id=%s AND deleted_at IS NULL',(owner,entry_id)).fetchall()
            rev=db.execute('SELECT approved_text,entry_date,blocks,analysis_status FROM entry_revisions WHERE user_id=%s AND entry_id=%s AND revision=%s',(owner,entry_id,e['current_revision'])).fetchone()
            e['saved']=rev; e['analysis_status']=rev['analysis_status'] if rev else None
            return e

    @app.get('/api/v1/entries')
    def entries(from_date:date|None=Query(None,alias='from'),to_date:date|None=Query(None,alias='to'),cursor:str|None=None,limit:int=Query(50,ge=1,le=100),owner:UUID=Depends(verify)):
        if from_date and to_date and from_date>=to_date: fail(422,'invalid_range','from must precede to')
        after=None
        if cursor:
            try: after=UUID(base64.urlsafe_b64decode(cursor).decode())
            except Exception: fail(422,'invalid_cursor','Invalid cursor')
        with repo.transaction(owner) as db:
            rows=db.execute('''SELECT id,entry_date,draft_version,current_revision,created_at FROM entries WHERE user_id=%s AND deleted_at IS NULL
                AND (%s::date IS NULL OR entry_date >= %s) AND (%s::date IS NULL OR entry_date < %s)
                AND (%s::uuid IS NULL OR id > %s) ORDER BY id LIMIT %s''',(owner,from_date,from_date,to_date,to_date,after,after,limit+1)).fetchall()
            return {'items':rows[:limit],'next_cursor':base64.urlsafe_b64encode(str(rows[limit-1]['id']).encode()).decode() if len(rows)>limit else None}

    @app.delete('/api/v1/entries/{entry_id}')
    def delete_entry(entry_id:UUID,request:Request,owner:UUID=Depends(verify),key:str|None=Header(None,alias='Idempotency-Key')):
        def op(db):
            repo.entry(db,owner,entry_id); repo.invalidate(db,owner,entry_id)
            db.execute('UPDATE entries SET deleted_at=now(),blocks=\'[]\' WHERE user_id=%s AND id=%s',(owner,entry_id))
            db.execute('UPDATE attachments SET deleted_at=now(),extraction=NULL WHERE user_id=%s AND entry_id=%s',(owner,entry_id))
            repo.enqueue(db,owner,'PURGE_ENTRY',f'purge:{entry_id}',entry_id)
            return 204,None
        return mutate(owner,request,key,{},op)

    @app.post('/api/v1/entries/{entry_id}/uploads')
    def upload(entry_id:UUID,body:Upload,request:Request,owner:UUID=Depends(verify),key:str|None=Header(None,alias='Idempotency-Key')):
        def op(db):
            repo.entry(db,owner,entry_id)
            image=body.mime_type.startswith('image/')
            if image and body.byte_size>10*1024*1024: fail(413,'media_limit','Images must be at most 10 MB')
            count=db.execute("SELECT count(*) AS n FROM attachments WHERE user_id=%s AND entry_id=%s AND deleted_at IS NULL AND (mime_type LIKE 'image/%%')=%s",(owner,entry_id,image)).fetchone()['n']
            if count >= (10 if image else 1): fail(413,'media_limit','Attachment count limit reached')
            aid=uuid4(); token=secrets.token_urlsafe(32); expires=datetime.now(timezone.utc)+timedelta(minutes=10)
            db.execute('INSERT INTO attachments(id,user_id,entry_id,object_key,mime_type,byte_size,checksum,upload_token_hash,upload_expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                       (aid,owner,entry_id,f'{owner}/{uuid4()}',body.mime_type,body.byte_size,body.checksum,hashlib.sha256(token.encode()).hexdigest(),expires))
            return 201,{'attachment_id':str(aid),'upload_url':f'{settings.public_url}/api/v1/attachments/{aid}/upload?token={token}','expires_at':expires,'method':'PUT'}
        return mutate(owner,request,key,body.model_dump(mode='json'),op)

    @app.put('/api/v1/attachments/{attachment_id}/upload')
    async def upload_bytes(attachment_id:UUID,request:Request,token:str,owner:UUID=Depends(verify)):
        with repo.transaction(owner) as db:
            a=repo.attachment(db,owner,attachment_id)
        if a['state']!='uploading' or a['upload_expires_at']<=datetime.now(timezone.utc) or not secrets.compare_digest(a['upload_token_hash'] or '',hashlib.sha256(token.encode()).hexdigest()):
            fail(409,'upload_expired','Upload authorization is expired or already used')
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>a['byte_size']: fail(413,'media_limit','Upload exceeds declared size')
        validate_media(bytes(data),a)
        # Store outside DB transaction; completion rechecks tombstones and bytes.
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(store.write,a['object_key'],bytes(data),a['mime_type'])
        with repo.transaction(owner) as db:
            live=db.execute('SELECT a.id FROM attachments a JOIN entries e ON e.id=a.entry_id WHERE a.user_id=%s AND a.id=%s AND a.deleted_at IS NULL AND e.deleted_at IS NULL',(owner,attachment_id)).fetchone()
            if not live:
                repo.enqueue(db,owner,'PURGE_OBJECT',f'late-upload:{attachment_id}:{uuid4()}',payload={'object_key':a['object_key']})
            else:
                db.execute("UPDATE attachments SET state='uploaded',upload_token_hash=NULL WHERE user_id=%s AND id=%s",(owner,attachment_id))
        if not live: fail(404,'not_found','Attachment was removed')
        return Response(status_code=204)

    @app.post('/api/v1/attachments/{attachment_id}/complete')
    def complete(attachment_id:UUID,body:Complete,request:Request,owner:UUID=Depends(verify),key:str|None=Header(None,alias='Idempotency-Key')):
        # Verify stored object before durable extraction enqueue; no unreviewed text is committed.
        with repo.transaction(owner) as db: a=repo.attachment(db,owner,attachment_id)
        if body.checksum!=a['checksum']: fail(422,'checksum_mismatch','Checksum differs from upload authorization')
        if a['state'] not in ('uploaded','processing','needs_review','ready'): fail(409,'upload_incomplete','Upload bytes before completion')
        validate_media(store.read_private(a['object_key']),a)
        def op(db):
            a=repo.attachment(db,owner,attachment_id)
            job=repo.enqueue(db,owner,'EXTRACT_MEDIA',f'extract:{attachment_id}:{a["extraction_version"]}',a['entry_id'],attachment_id=attachment_id)
            if a['state']=='uploaded': db.execute("UPDATE attachments SET state='processing' WHERE user_id=%s AND id=%s",(owner,attachment_id))
            return 202,{'state':a['state'] if a['state']!='uploaded' else 'processing','job_id':job}
        return mutate(owner,request,key,body.model_dump(),op)

    @app.get('/api/v1/attachments/{attachment_id}')
    def attachment(attachment_id:UUID,owner:UUID=Depends(verify)):
        with repo.transaction(owner) as db:
            a=repo.attachment(db,owner,attachment_id)
            return {k:a[k] for k in ('id','state','extraction','extraction_version','error_code')}

    @app.get('/api/v1/attachments/{attachment_id}/content')
    def content(attachment_id:UUID,owner:UUID=Depends(verify)):
        with repo.transaction(owner) as db:
            a=repo.attachment(db,owner,attachment_id)
            if a['state']=='uploading': fail(409,'upload_incomplete','No uploaded media')
            # Sign while owner lock is held so deletion cannot race authorization.
            return {'url':store.sign_read(a['object_key']),'expires_at':datetime.now(timezone.utc)+timedelta(seconds=60)}

    @app.post('/api/v1/attachments/{attachment_id}/retry')
    def retry_attachment(attachment_id:UUID,request:Request,owner:UUID=Depends(verify),key:str|None=Header(None,alias='Idempotency-Key')):
        def op(db):
            a=repo.attachment(db,owner,attachment_id)
            if a['state']!='failed': fail(409,'not_failed','Only failed extraction can be retried')
            version=a['extraction_version']+1
            db.execute("UPDATE attachments SET state='processing',error_code=NULL,extraction_version=%s WHERE user_id=%s AND id=%s",(version,owner,attachment_id))
            job=repo.enqueue(db,owner,'EXTRACT_MEDIA',f'extract:{attachment_id}:{version}',a['entry_id'],attachment_id=attachment_id)
            return 202,{'job_id':job}
        return mutate(owner,request,key,{},op)

    @app.delete('/api/v1/attachments/{attachment_id}')
    def delete_attachment(attachment_id:UUID,request:Request,owner:UUID=Depends(verify),key:str|None=Header(None,alias='Idempotency-Key')):
        def op(db):
            a=repo.attachment(db,owner,attachment_id); e=repo.entry(db,owner,a['entry_id'])
            # Explicitly require client review/commit before removing approved source media.
            if e['current_revision']:
                r=db.execute('SELECT blocks FROM entry_revisions WHERE user_id=%s AND entry_id=%s AND revision=%s',(owner,a['entry_id'],e['current_revision'])).fetchone()
                if any(b.get('attachment_id')==str(attachment_id) for b in r['blocks']):
                    fail(409,'source_in_use','Commit reviewed text-only or remaining blocks before removing this source')
            db.execute('UPDATE attachments SET deleted_at=now(),extraction=NULL WHERE user_id=%s AND id=%s',(owner,attachment_id))
            db.execute("UPDATE jobs SET status='cancelled',lease_token=NULL WHERE user_id=%s AND attachment_id=%s AND status IN ('queued','running')",(owner,attachment_id))
            db.execute('UPDATE entries SET blocks=%s,draft_version=draft_version+1 WHERE user_id=%s AND id=%s',(Jsonb([b for b in e['blocks'] if b.get('attachment_id')!=str(attachment_id)]),owner,a['entry_id']))
            db.execute("UPDATE derived_documents SET status='stale' WHERE user_id=%s",(owner,))
            repo.enqueue(db,owner,'PURGE_OBJECT',f'purge-media:{attachment_id}',payload={'object_key':a['object_key']})
            return 204,None
        return mutate(owner,request,key,{},op)

    @app.get('/api/v1/jobs/{job_id}')
    def job(job_id:UUID,owner:UUID=Depends(verify)):
        with repo.transaction(owner) as db:
            row=db.execute('SELECT id,status,progress_stage,result,error_code,attempt FROM jobs WHERE user_id=%s AND id=%s',(owner,job_id)).fetchone()
            if not row: fail(404,'not_found','Job not found')
            return row

    @app.post('/api/v1/jobs/{job_id}/retry')
    def retry_job(job_id:UUID,request:Request,owner:UUID=Depends(verify),key:str|None=Header(None,alias='Idempotency-Key')):
        def op(db):
            j=db.execute('SELECT * FROM jobs WHERE user_id=%s AND id=%s',(owner,job_id)).fetchone()
            if not j: fail(404,'not_found','Job not found')
            if j['status']!='failed': fail(409,'not_failed','Only failed jobs can be retried')
            if j['entry_id']:
                e=repo.entry(db,owner,j['entry_id'])
                if j['revision'] and e['current_revision']!=j['revision']: fail(409,'stale_job','Entry revision changed')
            if j['attachment_id']:
                repo.attachment(db,owner,j['attachment_id'])
                db.execute("UPDATE attachments SET state='processing',error_code=NULL WHERE user_id=%s AND id=%s",(owner,j['attachment_id']))
            db.execute("UPDATE jobs SET status='queued',attempt=0,error_code=NULL,available_at=now(),progress_stage='queued' WHERE user_id=%s AND id=%s",(owner,job_id))
            if j['revision']: db.execute("UPDATE entry_revisions SET analysis_status='queued' WHERE user_id=%s AND entry_id=%s AND revision=%s",(owner,j['entry_id'],j['revision']))
            return 202,{'job_id':str(job_id)}
        return mutate(owner,request,key,{},op)

    from .integration import add_routes
    if services is None and os.getenv('SERVICE_MODULE'):
        services=importlib.import_module(os.environ['SERVICE_MODULE']).services
    add_routes(app,repo,verify,mutate,services or {})
    return app
