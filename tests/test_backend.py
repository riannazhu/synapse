"""Real PostgreSQL integration tests; pgserver supplies an isolated temporary server.
Supabase-managed auth/storage schemas are represented by minimal bootstrap tables.
No external project, credentials, model API, or network is used.
"""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

try:
    import pgserver
    import psycopg
    from fastapi.testclient import TestClient
    from PIL import Image
    from server.api.app import create_app
    from server.config import Settings
    from server.jobs.runtime import Runtime
    from server.jobs.runtime.worker import register_analysis
    from server.analysis import configure_extractor
    AVAILABLE=True
except ImportError:
    AVAILABLE=False


class FakeStore:
    def __init__(self): self.objects={}
    def write(self,key,data,mime): self.objects[key]=data
    def read_private(self,key): return self.objects[key]
    def delete(self,key): self.objects.pop(key,None)
    def sign_read(self,key): return 'https://private.example/'+key

class EmptyExtractor:
    def extract(self,text,passages, *, entry_date): return {'topics':[],'events':[]}


@unittest.skipUnless(AVAILABLE,'Install requirements-dev.txt to run PostgreSQL integration tests')
class BackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=tempfile.TemporaryDirectory(prefix='synapse-test-')
        cls.pg=pgserver.get_server(Path(cls.root.name)/'pgdata')
        cls.url=cls.pg.get_uri()
        with psycopg.connect(cls.url,autocommit=True) as db:
            db.execute('''CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
              CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
              CREATE ROLE anon; CREATE ROLE authenticated; GRANT USAGE ON SCHEMA auth TO authenticated;
              CREATE SCHEMA storage; CREATE TABLE storage.buckets(id text PRIMARY KEY,name text,public boolean,file_size_limit bigint);''')
            for p in sorted((Path(__file__).parents[1]/'database/migrations').glob('*.sql')):
                db.execute(p.read_text())

    @classmethod
    def tearDownClass(cls):
        cls.pg.cleanup()
        cls.root.cleanup()

    def setUp(self):
        with psycopg.connect(self.url) as db:
            db.execute('TRUNCATE auth.users CASCADE')
            self.owner=uuid4(); self.other=uuid4()
            db.execute('INSERT INTO auth.users VALUES (%s),(%s)',(self.owner,self.other))
        self.settings=Settings(self.url,'https://example.supabase.co','test')
        self.media=FakeStore()
        self.client=TestClient(create_app(self.settings,verifier=lambda:self.owner,media=self.media),raise_server_exceptions=False)
        self.runtime=Runtime(self.settings,media=self.media)
        configure_extractor(EmptyExtractor()); register_analysis(self.runtime)

    def post(self,path,body=None,key=None):
        return self.client.post('/api/v1'+path,json=body or {},headers={'Idempotency-Key':key or str(uuid4())})

    def create(self):
        r=self.post('/entries',{'entry_date':'2026-10-17','mode':'text'})
        self.assertEqual(r.status_code,201,r.text)
        return r.json()['id']

    def draft(self,eid,version=1,text='I want to learn piano.',**kwargs):
        block={'id':str(uuid4()),'text':text,**kwargs}
        r=self.client.patch(f'/api/v1/entries/{eid}/draft',json={'expected_draft_version':version,'entry_date':'2026-10-17','blocks':[block]},headers={'Idempotency-Key':str(uuid4())})
        self.assertEqual(r.status_code,200,r.text)
        return block,r.json()['draft_version']

    def commit(self,eid,block,version):
        return self.post(f'/entries/{eid}/commit',{'expected_draft_version':version,'included_block_ids':[block['id']],'approval':True})

    def sql(self,query,args=()):
        with psycopg.connect(self.url) as db:
            return db.execute(query,args).fetchall() if query.strip().upper().startswith('SELECT') else db.execute(query,args).rowcount

    def test_save_analysis_metadata_and_idempotency(self):
        key=str(uuid4()); body={'entry_date':'2026-10-17','mode':'text'}
        first=self.post('/entries',body,key); second=self.post('/entries',body,key)
        self.assertEqual(first.json(),second.json())
        self.assertEqual(self.post('/entries',{**body,'mode':'chat'},key).status_code,409)
        eid=first.json()['id']; block,v=self.draft(eid)
        committed=self.commit(eid,block,v); self.assertEqual(committed.status_code,202,committed.text)
        self.assertTrue(self.runtime.run_once())
        saved=self.client.get(f'/api/v1/entries/{eid}').json()
        self.assertEqual(saved['analysis_status'],'succeeded')
        result=self.sql('SELECT analysis_result FROM entry_revisions WHERE entry_id=%s',(eid,))[0][0]
        self.assertEqual(result['revision'],1); self.assertEqual(result['entry_date'],'2026-10-17')

    def test_revision_and_expired_lease_cannot_publish(self):
        eid=self.create(); b,v=self.draft(eid); self.assertEqual(self.commit(eid,b,v).status_code,202)
        old=self.runtime.claim(); ctx=self.runtime.context(old)
        b2,v=self.draft(eid,v+1,text='A newer entry.'); self.assertEqual(self.commit(eid,b2,v).status_code,202)
        self.assertFalse(self.runtime.finish(old,result=self.runtime.handlers['ANALYZE_ENTRY'](ctx)))
        current=self.runtime.claim(); ctx=self.runtime.context(current)
        self.sql("UPDATE jobs SET lease_until=now()-interval '1 second' WHERE id=%s",(current['id'],))
        reclaimed=self.runtime.claim()
        self.assertNotEqual(current['lease_token'],reclaimed['lease_token'])
        result=self.runtime.handlers['ANALYZE_ENTRY'](ctx)
        self.assertFalse(self.runtime.finish(current,result=result))
        self.assertTrue(self.runtime.finish(reclaimed,result=result))

    def test_owner_scope_and_draft_conflict(self):
        eid=self.create(); self.draft(eid)
        self.assertEqual(self.client.patch(f'/api/v1/entries/{eid}/draft',json={'expected_draft_version':1,'entry_date':'2026-10-17','blocks':[]},headers={'Idempotency-Key':str(uuid4())}).status_code,409)
        self.owner=self.other
        self.assertEqual(self.client.get(f'/api/v1/entries/{eid}').status_code,404)
        self.assertEqual(self.client.get('/api/v1/entries').json()['items'],[])
        self.assertEqual(self.post(f'/entries/{eid}/commit',{'expected_draft_version':2,'included_block_ids':[str(uuid4())],'approval':True}).status_code,404)

    def test_media_review_and_one_representation(self):
        eid=self.create(); image=io.BytesIO(); Image.new('RGB',(4,4)).save(image,format='PNG'); data=image.getvalue()
        checksum=hashlib.sha256(data).hexdigest()
        upload=self.post(f'/entries/{eid}/uploads',{'filename':'page.png','mime_type':'image/png','byte_size':len(data),'checksum':checksum})
        self.assertEqual(upload.status_code,201,upload.text)
        aid=upload.json()['attachment_id']; url=upload.json()['upload_url']
        self.assertEqual(self.client.put(url,content=data).status_code,204)
        completed=self.post(f'/attachments/{aid}/complete',{'checksum':checksum}); self.assertEqual(completed.status_code,202,completed.text)
        self.runtime.register('EXTRACT_MEDIA',lambda ctx:{'text':'Piano practice','uncertain_spans':[]})
        self.assertTrue(self.runtime.run_once())
        self.assertEqual(self.client.get(f'/api/v1/attachments/{aid}').json()['state'],'needs_review')
        b,v=self.draft(eid,source_kind='handwriting',attachment_id=aid,reviewed=False)
        self.assertEqual(self.commit(eid,b,v).status_code,422)
        b,v=self.draft(eid,v,source_kind='handwriting',attachment_id=aid,reviewed=True)
        self.assertEqual(self.commit(eid,b,v).status_code,202)
        self.owner=self.other
        self.assertEqual(self.client.get(f'/api/v1/attachments/{aid}/content').status_code,404)

    def test_delete_cancels_work_and_purges_content(self):
        eid=self.create(); b,v=self.draft(eid); self.commit(eid,b,v)
        old=self.runtime.claim(); ctx=self.runtime.context(old)
        r=self.client.delete(f'/api/v1/entries/{eid}',headers={'Idempotency-Key':str(uuid4())})
        self.assertEqual(r.status_code,204,r.text)
        self.assertEqual(self.client.get(f'/api/v1/entries/{eid}').status_code,404)
        self.assertFalse(self.runtime.finish(old,result=self.runtime.handlers['ANALYZE_ENTRY'](ctx)))
        self.assertTrue(self.runtime.run_once())
        self.assertEqual(self.sql('SELECT * FROM entry_revisions WHERE entry_id=%s',(eid,)),[])

    def test_chat_draft_receives_user_messages_only(self):
        eid=self.create(); sid=self.post('/conversations',{'entry_id':eid}).json()['session_id']
        r=self.post(f'/conversations/{sid}/messages',{'client_message_id':str(uuid4()),'text':'I practiced piano.'})
        self.assertEqual(r.status_code,202,r.text)
        self.runtime.register('CHAT_REPLY',lambda ctx:{'text':'How did it feel?'})
        self.runtime.run_once()
        r=self.post(f'/conversations/{sid}/draft',{'through_sequence':2}); self.assertEqual(r.status_code,202,r.text)
        def summary(ctx):
            self.assertTrue(all(m['role']=='user' for m in ctx['messages']))
            return {'draft_text':'I practiced piano.','user_message_ids':[str(m['id']) for m in ctx['messages']]}
        self.runtime.register('CHAT_DRAFT',summary); self.runtime.run_once()
        self.assertIsNone(self.client.get(f'/api/v1/entries/{eid}').json()['current_revision'])

    def test_default_auth_rejects_missing_session(self):
        client=TestClient(create_app(self.settings),raise_server_exceptions=False)
        r=client.get('/api/v1/entries'); self.assertEqual(r.status_code,401,r.text)
        self.assertIn('request_id',r.json())

    def test_database_rls_and_composite_foreign_key(self):
        eid=self.create()
        with psycopg.connect(self.url) as db:
            db.execute('GRANT SELECT ON entries TO authenticated')
            db.execute('SET LOCAL ROLE authenticated')
            db.execute("SELECT set_config('app.user_id',%s,true)",(str(self.other),))
            self.assertEqual(db.execute('SELECT id FROM entries').fetchall(),[])
            db.execute("SELECT set_config('app.user_id',%s,true)",(str(self.owner),))
            self.assertEqual(len(db.execute('SELECT id FROM entries').fetchall()),1)
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with psycopg.connect(self.url) as db:
                db.execute("INSERT INTO attachments(id,user_id,entry_id,object_key,mime_type,byte_size,checksum) VALUES (%s,%s,%s,%s,'image/png',1,'x')",(uuid4(),self.other,eid,str(uuid4())))

    def test_transient_retry_is_persisted(self):
        from server.jobs.runtime import RetryableError
        eid=self.create(); b,v=self.draft(eid); self.commit(eid,b,v)
        j=self.runtime.claim()
        self.assertTrue(self.runtime.finish(j,error=RetryableError()))
        state=self.sql('SELECT status,attempt,error_code,available_at FROM jobs WHERE id=%s',(j['id'],))[0]
        self.assertEqual(state[:3],('queued',1,'provider_transient'))
        self.assertGreater(state[3],datetime.now(timezone.utc))
        self.sql('UPDATE jobs SET available_at=now() WHERE id=%s',(j['id'],))
        j2=self.runtime.claim(); self.assertEqual(j2['attempt'],2)
        self.assertTrue(self.runtime.finish(j2,error=ValueError('redacted sensitive detail')))
        self.assertEqual(self.client.get(f'/api/v1/jobs/{j["id"]}').json()['error_code'],'handler_failed')

    def test_approved_media_requires_one_representation(self):
        eid=self.create(); aid=uuid4()
        self.sql("INSERT INTO attachments(id,user_id,entry_id,object_key,mime_type,byte_size,checksum,state) VALUES (%s,%s,%s,%s,'image/png',1,'x','needs_review')",(aid,self.owner,eid,str(uuid4())))
        blocks=[{'id':str(uuid4()),'text':'Piano','source_kind':kind,'attachment_id':str(aid),'reviewed':True} for kind in ('handwriting','summary')]
        r=self.client.patch(f'/api/v1/entries/{eid}/draft',json={'expected_draft_version':1,'entry_date':'2026-10-17','blocks':blocks},headers={'Idempotency-Key':str(uuid4())})
        self.assertEqual(r.status_code,200,r.text)
        r=self.post(f'/entries/{eid}/commit',{'expected_draft_version':2,'included_block_ids':[b['id'] for b in blocks],'approval':True})
        self.assertEqual(r.status_code,422,r.text)
        self.assertEqual(r.json()['error']['code'],'duplicate_representation')

    def test_signed_token_verification_checks_signature_expiry_audience_and_issuer(self):
        import jwt
        from unittest.mock import Mock
        from cryptography.hazmat.primitives.asymmetric import rsa
        from server.api.auth import SessionVerifier
        from server.repositories.postgres import DomainError
        verifier=SessionVerifier(self.settings)
        private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        verifier.keys=Mock()
        verifier.keys.get_signing_key_from_jwt.return_value=Mock(key=private.public_key())
        claims={'sub':str(self.owner),'iss':self.settings.supabase_url+'/auth/v1','aud':'authenticated','exp':int(datetime.now(timezone.utc).timestamp())+300}
        def token(c,signer=private): return 'Bearer '+jwt.encode(c,signer,algorithm='RS256')
        self.assertEqual(verifier(token(claims)),self.owner)
        for changed in ({'exp':1},{'aud':'wrong'},{'iss':'https://wrong.example'}):
            with self.assertRaises(DomainError): verifier(token({**claims,**changed}))
        other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        with self.assertRaises(DomainError): verifier(token(claims,other))
