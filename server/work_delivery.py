"""Deliver published CEO replies to the conversation that assigned the work."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import re
from uuid import UUID, uuid5

from fastapi import HTTPException

import administration
import general_knowledge
import agent_work
from chat_context import text
from csi_events import public_body
from task_api import Paperclip

MARKER = re.compile(r'^\[JARVIS USER MESSAGE request_id=([0-9a-f-]{36})\]\n')
INTERNAL = re.compile(r'^(?:\[JARVIS |CEO delegated |Verified (?:delegated execution|execution|local_ollama_models))')


def record(grant, receipt):
    if not grant.conversation_id:
        return
    task = receipt['task']
    stamp = task.get('createdAt') if receipt['action'] != 'continue_project' else None
    stamp = stamp or datetime.now(timezone.utc).isoformat()
    rows = [(grant.request_key, grant.conversation_id, grant.mission_id, task['id'],
              receipt.get('comment_id'), stamp)]
    # Creating a project opens its own conversation in the UI. Deliver the initial
    # result there as well as to the General conversation that assigned it.
    if receipt['action']=='start_project' and grant.mission_id is None and task.get('work_scope')=='project':
        project_thread=administration.conversations(task['id'])['default_id']
        rows.append((str(uuid5(UUID(grant.request_key),'project-default-delivery')),project_thread,
                     task['id'],task['id'],None,stamp))
    with closing(administration._threads()) as db, db:
        for values in rows:
            db.execute('INSERT INTO conversation_work VALUES (?,?,?,?,?,?) ON CONFLICT(request_key) DO NOTHING', values)
            saved = db.execute('SELECT conversation_id,scope_id,task_id FROM conversation_work WHERE request_key=?', (values[0],)).fetchone()
            if saved != values[1:4]:
                raise HTTPException(409, 'Work request belongs to a different conversation')


def links(conversation_id, scope_id=None):
    with closing(administration._threads()) as db:
        rows = db.execute('SELECT request_key,task_id,comment_id,started_at FROM conversation_work WHERE conversation_id=? AND scope_id IS ? ORDER BY started_at DESC,request_key ASC LIMIT 30', (conversation_id, scope_id)).fetchall()
    return [{'request_key':k,'task_id':t,'comment_id':c,'started_at':d} for k,t,c,d in rows]


def epoch(value):
    if isinstance(value,(int,float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError):
        return 0


def recover(conversation_id, scope_id, comments):
    """Recover pre-delivery project requests using their exact native message nonce."""
    if not scope_id:
        return
    by_key = {m.group(1):c for c in comments if c.get('authorUserId') and (m:=MARKER.match(c.get('body') or ''))}
    with closing(administration._threads()) as db, db:
        previous = db.execute('SELECT request_id,question FROM public_messages WHERE conversation_id=? AND mission_id=?', (conversation_id,scope_id)).fetchall()
        for key, question in previous:
            comment = by_key.get(key)
            if not comment:
                continue
            original = MARKER.sub('',comment['body'],count=1)
            if original != question and not original.startswith(question+'\n\nPrior conversation context:\n'):
                continue
            db.execute('INSERT INTO conversation_work VALUES (?,?,?,?,?,?) ON CONFLICT(request_key) DO NOTHING',
                       (key,conversation_id,scope_id,scope_id,comment['id'],comment['createdAt']))


async def updates(conversation_id, scope_id=None):
    linked = await asyncio.to_thread(links,conversation_id,scope_id)
    # Older project conversations have a public-message index but no delivery link.
    if not linked:
        with closing(administration._threads()) as db:
            recoverable = scope_id and db.execute('SELECT 1 FROM public_messages WHERE conversation_id=? AND mission_id=? LIMIT 1', (conversation_id,scope_id)).fetchone()
        if not recoverable:
            return {'messages':[], 'work':[]}
    p = Paperclip()
    limit = asyncio.Semaphore(4)
    async def read(task_id):
        async with limit:
            try:
                task = await p.issue(task_id)
                if task.get('hiddenAt') or task.get('parentId') or task.get('assigneeAgentId') != p.ceo:
                    return None
                if scope_id and task['id'] != scope_id:
                    return None
                comments = await p.request('GET',f'issues/{task_id}/comments')
                return task,comments
            except HTTPException as exc:
                if exc.status_code == 404:
                    return None
                raise
    try:
        ids = {item['task_id'] for item in linked}
        if scope_id:
            ids.add(scope_id)
        ids=sorted(ids)
        results=await asyncio.gather(*(read(task_id) for task_id in ids),return_exceptions=True)
        for result in results:
            if isinstance(result,Exception):raise result
        data = dict(zip(ids,results))
        if scope_id and data.get(scope_id):
            await asyncio.to_thread(recover,conversation_id,scope_id,data[scope_id][1])
            linked = await asyncio.to_thread(links,conversation_id,scope_id)
        messages = {}; work = []; publications = None
        for link in linked:
            native = data.get(link['task_id'])
            if not native:
                continue
            task,comments = native
            anchor = next((c for c in comments if c['id']==link['comment_id'] and c.get('authorUserId') and
                           (m:=MARKER.match(c.get('body') or '')) and m.group(1)==link['request_key']),None)
            if link['comment_id'] and not anchor:
                continue
            start = epoch(anchor['createdAt'] if anchor else link['started_at'])
            following = [epoch(c['createdAt']) for c in comments if c.get('authorUserId') and
                         MARKER.match(c.get('body') or '') and epoch(c['createdAt'])>start]
            end = min(following,default=float('inf'))
            replies = []
            for comment in comments:
                body = str(comment.get('body') or '').strip()
                when = epoch(comment.get('createdAt'))
                marker=re.fullmatch(r'\[JARVIS GENERAL KNOWLEDGE RECEIPT ([0-9a-f]{64})\]',body.partition('\n')[0])
                if (not scope_id and marker and start<=when<end and comment.get('authorUserId')
                        and not comment.get('authorAgentId') and not comment.get('createdByRunId')
                        and not comment.get('derivedAuthorAgentId') and comment.get('issueId')==task['id']):
                    if publications is None:
                        ceo=await p.request('GET','agents/'+p.ceo)
                        publications=general_knowledge.publications(ceo) if ceo.get('companyId')==p.company and ceo.get('id')==p.ceo else {}
                    saved=publications.get(marker[1])
                    if saved:
                        replies.append({'id':'paperclip:'+comment['id'],'role':'system','timestamp':when,
                            'text':saved['identifier']+' findings are available in General chat.',
                            'source':{'kind':'project_result','label':'General knowledge','task_id':task['id'],'identifier':task.get('identifier')}})
                    continue
                if (comment.get('authorAgentId') != p.ceo or not start <= when < end or not body or INTERNAL.match(body)):
                    continue
                body = text(public_body(body),20000).strip()
                if not body:
                    continue
                row = {'id':'paperclip:'+comment['id'],'role':'assistant','text':body,'timestamp':when,
                       'source':{'kind':'project_result','task_id':task['id'],'identifier':task.get('identifier')}}
                replies.append(row)
            if replies:
                latest=max(replies,key=lambda row:(row['source'].get('label')=='General knowledge',row['timestamp'],row['id']))
                messages[latest['id']]=latest
            state, _ = agent_work.engagement(task)
            if following:
                state = 'closed'
            work.append({'task_id':task['id'],'identifier':task.get('identifier'),'state':state,
                         'has_reply':bool(replies),'superseded':bool(following),'request_key':link['request_key'],
                         'reason':text((task.get('unblockDescriptor') or {}).get('action'),200)})
        return {'messages':sorted(messages.values(),key=lambda m:(m['timestamp'],m['id'])),'work':work}
    finally:
        await p.http.aclose()


def merge_history(messages, delivered):
    if not delivered:
        return messages[-160:]
    # Older Hermes records without timestamps keep their original relative order.
    combined = [(epoch(m.get('timestamp')) or -1+i/10000,i,m) for i,m in enumerate(messages)]
    combined += [(m['timestamp'],len(messages)+i,m) for i,m in enumerate(delivered)]
    return [row[2] for row in sorted(combined,key=lambda row:row[:2])][-160:]
