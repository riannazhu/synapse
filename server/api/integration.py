"""Track B service seams: only live, owner-scoped current revisions are supplied."""
from uuid import UUID, uuid4
from datetime import date
from fastapi import Depends, Header, Query, Request
from psycopg.types.json import Jsonb
from server.repositories.postgres import fail
from .contracts import Conversation, Message, ConversationDraft, TopicEdit


def add_routes(app,repo,verify,mutate,services):
    def session(db,owner,sid):
        s=db.execute('SELECT c.* FROM conversations c JOIN entries e ON e.id=c.entry_id AND e.user_id=c.user_id WHERE c.user_id=%s AND c.id=%s AND e.deleted_at IS NULL',(owner,sid)).fetchone()
        if not s: fail(404,'not_found','Conversation not found')
        return s

    @app.post('/api/v1/conversations')
    def conversation(body:Conversation,request:Request,owner:UUID=Depends(verify),key:str|None=Header(None,alias='Idempotency-Key')):
        def op(db):
            repo.entry(db,owner,body.entry_id)
            sid=uuid4()
            db.execute('INSERT INTO conversations(id,user_id,entry_id,history_enabled,retain_transcript) VALUES (%s,%s,%s,%s,%s)',(sid,owner,body.entry_id,body.history_enabled,body.retain_transcript))
            return 201,{'session_id':str(sid)}
        return mutate(owner,request,key,body.model_dump(mode='json'),op)

    @app.get('/api/v1/conversations/{session_id}/messages')
    def messages(session_id:UUID,owner:UUID=Depends(verify)):
        with repo.transaction(owner) as db:
            session(db,owner,session_id)
            return {'items':db.execute('SELECT id,role,text,sequence FROM messages WHERE user_id=%s AND session_id=%s ORDER BY sequence LIMIT 100',(owner,session_id)).fetchall()}

    @app.post('/api/v1/conversations/{session_id}/messages')
    def message(session_id:UUID,body:Message,request:Request,owner:UUID=Depends(verify),key:str|None=Header(None,alias='Idempotency-Key')):
        def op(db):
            s=session(db,owner,session_id)
            old=db.execute('SELECT * FROM messages WHERE user_id=%s AND session_id=%s AND client_message_id=%s',(owner,session_id,body.client_message_id)).fetchone()
            if old:
                if old['text']!=body.text: fail(409,'message_conflict','Client message ID already used')
                mid=old['id']
            else:
                active=db.execute("SELECT count(*) AS n FROM jobs WHERE user_id=%s AND type IN ('CHAT_REPLY','CHAT_DRAFT') AND status IN ('queued','running')",(owner,)).fetchone()['n']
                if active>=2: fail(429,'rate_limited','Wait for active conversation jobs')
                seq=db.execute('SELECT coalesce(max(sequence),0)+1 AS n FROM messages WHERE user_id=%s AND session_id=%s',(owner,session_id)).fetchone()['n']
                if seq>99: fail(413,'conversation_limit','Start a new conversation after 100 messages')
                mid=uuid4()
                db.execute("INSERT INTO messages(id,user_id,session_id,role,text,sequence,client_message_id) VALUES (%s,%s,%s,'user',%s,%s,%s)",(mid,owner,session_id,body.text,seq,body.client_message_id))
            jid=repo.enqueue(db,owner,'CHAT_REPLY',f'chat:{mid}',s['entry_id'],payload={'session_id':str(session_id),'message_id':str(mid)})
            return 202,{'message_id':str(mid),'job_id':jid}
        return mutate(owner,request,key,body.model_dump(mode='json'),op)

    @app.post('/api/v1/conversations/{session_id}/draft')
    def draft(session_id:UUID,body:ConversationDraft,request:Request,owner:UUID=Depends(verify),key:str|None=Header(None,alias='Idempotency-Key')):
        def op(db):
            s=session(db,owner,session_id)
            last=db.execute('SELECT max(sequence) AS n FROM messages WHERE user_id=%s AND session_id=%s',(owner,session_id)).fetchone()['n']
            if last is None or body.through_sequence>last: fail(422,'invalid_sequence','Sequence does not exist')
            jid=repo.enqueue(db,owner,'CHAT_DRAFT',f'chat-draft:{session_id}:{body.through_sequence}',s['entry_id'],payload={'session_id':str(session_id),'through_sequence':body.through_sequence})
            return 202,{'job_id':jid}
        return mutate(owner,request,key,body.model_dump(),op)

    def snapshot(owner):
        with repo.transaction(owner) as db:
            versions=db.execute('SELECT corpus_version,topic_version,layout_version FROM user_state WHERE user_id=%s',(owner,)).fetchone()
            revisions=db.execute('''SELECT r.* FROM entries e JOIN entry_revisions r ON r.entry_id=e.id AND r.user_id=e.user_id AND r.revision=e.current_revision
                WHERE e.user_id=%s AND e.deleted_at IS NULL''',(owner,)).fetchall()
            topics=db.execute('SELECT * FROM topics WHERE user_id=%s AND merged_into IS NULL',(owner,)).fetchall()
            return {'revisions':revisions,'topics':topics,'versions':versions}

    def invoke(name,owner,**args):
        service=services.get(name)
        if not service: fail(503,'service_unavailable',f'Track B service {name} is not registered')
        return service(snapshot(owner),**args)

    def dates(start,end):
        if start and end and start>=end: fail(422,'invalid_range','from must precede to')

    @app.get('/api/v1/graph')
    def graph(from_date:date|None=Query(None,alias='from'),to_date:date|None=Query(None,alias='to'),owner:UUID=Depends(verify)):
        dates(from_date,to_date)
        return invoke('graph',owner,from_date=from_date,to_date=to_date)

    @app.get('/api/v1/graph/compare')
    def compare(a_from:date,a_to:date,b_from:date,b_to:date,owner:UUID=Depends(verify)):
        dates(a_from,a_to); dates(b_from,b_to)
        return invoke('graph_compare',owner,a_from=a_from,a_to=a_to,b_from=b_from,b_to=b_to)

    @app.get('/api/v1/topics/{topic_id}')
    def topic(topic_id:UUID,from_date:date|None=Query(None,alias='from'),to_date:date|None=Query(None,alias='to'),owner:UUID=Depends(verify)):
        dates(from_date,to_date)
        with repo.transaction(owner) as db:
            t=db.execute('SELECT id FROM topics WHERE user_id=%s AND id=%s',(owner,topic_id)).fetchone()
            if not t: fail(404,'not_found','Topic not found')
        return invoke('topic_detail',owner,topic_id=str(topic_id),from_date=from_date,to_date=to_date)

    @app.patch('/api/v1/topics/{topic_id}')
    def edit_topic(topic_id:UUID,body:TopicEdit,request:Request,owner:UUID=Depends(verify),key:str|None=Header(None,alias='Idempotency-Key')):
        def op(db):
            version=db.execute('SELECT topic_version FROM user_state WHERE user_id=%s',(owner,)).fetchone()['topic_version']
            t=db.execute('SELECT * FROM topics WHERE user_id=%s AND id=%s',(owner,topic_id)).fetchone()
            if not t: fail(404,'not_found','Topic not found')
            if version!=body.expected_topic_version: fail(409,'topic_conflict','Topic registry changed')
            if body.label is not None and not body.label.strip(): fail(422,'invalid_label','Label cannot be blank')
            aliases=list(t['aliases'])
            if body.label is not None and body.label!=t['label']: aliases.append(t['label'])
            db.execute('UPDATE topics SET label=%s,hidden=%s,aliases=%s WHERE user_id=%s AND id=%s',(body.label or t['label'],body.hidden if body.hidden is not None else t['hidden'],Jsonb(aliases),owner,topic_id))
            db.execute('UPDATE user_state SET topic_version=topic_version+1 WHERE user_id=%s',(owner,))
            db.execute("UPDATE derived_documents SET status='stale' WHERE user_id=%s",(owner,))
            return 200,{'topic_version':version+1}
        return mutate(owner,request,key,body.model_dump(mode='json'),op)
