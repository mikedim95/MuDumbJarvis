#!/usr/bin/env python3
"""Explicit idle-session migration of the existing native artifact reader schema."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from uuid import UUID


VERSION='bounded-native-input-v1'
FIELDS={'artifact_id','artifact_offset','offset','limit','materialize'}


def migrate_pin(pin, live):
    """Merge reviewed optional fields only; preserve names, order and custom prose."""
    if not isinstance(pin,dict) or not isinstance(pin.get('tools'),list):
        raise ValueError('This session has no recognized saved tool schema')
    revised=copy.deepcopy(pin)
    saved=next((t.get('function') for t in revised['tools'] if
        (t.get('function') or {}).get('name')=='research_sources'),None)
    if not saved:
        raise ValueError('The session did not authorize research_sources')
    current=live['parameters']['properties']
    properties=saved['parameters']['properties']
    base={'frameworks','action','urls','query','issue_ids'}
    if not base<=properties.keys() or not FIELDS<=current.keys():
        raise ValueError('Unrecognized artifact reader contract')
    if saved['parameters'].get('required',[])!=live['parameters'].get('required',[]):
        raise ValueError('Saved required fields differ; operator review is needed')
    for key in base|FIELDS:
        if key in properties and properties[key]!=current[key]:
            raise ValueError('Saved parameter customization conflicts: '+key)
    for key in sorted(FIELDS):properties[key]=copy.deepcopy(current[key])
    return revised


RUNTIME_CODE='''import json,sys
from hermes_constants import get_hermes_home
sys.path.insert(0,str(get_hermes_home()/'plugins'))
from jarvis_readonly import employee_work
from hermes_state import SessionDB
request=json.load(sys.stdin)
namespace={};exec(compile(request['migration_code'],'reviewed-tool-schema-migration','exec'),namespace)
tools=[];ctx=type('SchemaCheck',(),{'register_tool':lambda self,**kw:tools.append(kw)})()
employee_work.register(ctx)
live=next(t['schema'] for t in tools if t['name']=='research_sources')
db=SessionDB();row=db.get_session(request['session_id'])
if not row:raise ValueError('Existing native Hermes session not found')
pin=json.loads(row.get('tool_names') or 'null')
if request['apply'] and pin!=request['expected_old_pin']:
 raise ValueError('Saved tool schema changed after the reviewed plan')
updated=namespace['migrate_pin'](pin,live)
if request['apply'] and updated!=pin:
 db.update_session_tool_names(request['session_id'],updated)
 after=db.get_session(request['session_id'])
 assert all(after[k]==v for k,v in row.items() if k!='tool_names'), 'Session metadata/history changed unexpectedly'
 assert json.loads(after['tool_names'])==updated
print(json.dumps({'old_pin':pin,'new_pin':updated,'changed':updated!=pin,'applied':request['apply'],
 'message_count':row.get('message_count'),'transcript_revision':row.get('transcript_revision')}))
db.close()
'''


def main():
    from deploy.staffing import Board,settings,inspect
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--issue-id',required=True,type=lambda v:str(UUID(v)))
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    env=settings();board=Board(env)
    issue=board.api('GET','/issues/'+args.issue_id)
    assert issue['companyId']==env['PAPERCLIP_COMPANY_ID']
    agent=board.api('GET','/agents/'+issue['assigneeAgentId'])
    meta=(agent.get('metadata') or {}).get('jarvis') or {}
    assert meta.get('managed') and meta.get('profile') in ('research','security_analysis')
    name='jarvis-employee-'+meta['runtime_id']
    state=inspect('container',name)
    assert state and state['State']['Running']
    live=board.api('GET','/companies/'+env['PAPERCLIP_COMPANY_ID']+'/live-runs')
    assert not any(r['agentId']==agent['id'] and r['status'] in ('running','queued') for r in live), 'Runtime must be idle'
    session=f"paperclip:company:{issue['companyId']}:agent:{agent['id']}:issue:{issue['id']}"
    code=Path(__file__).read_text().split('RUNTIME_CODE=',1)[0]
    payload={'session_id':session,'apply':False,'migration_code':code}
    def call():
        result=subprocess.run(['docker','exec','--user','1000:1000','-i',name,'python','-c',RUNTIME_CODE],
            input=json.dumps(payload),text=True,capture_output=True,check=True,timeout=30)
        return json.loads(result.stdout)
    plan=call()
    digest=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
    result={'version':VERSION,'issue_id':issue['id'],'runtime':name,'changed':plan['changed'],
        'before_sha256':digest(plan['old_pin']),'after_sha256':digest(plan['new_pin']),'applied':False}
    if args.apply and plan['changed']:
        backup=Path(__file__).resolve().parents[1]/'.runtime/backups/tool-schemas'/(
            datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+issue['id'])
        backup.mkdir(parents=True,mode=0o700)
        (backup/'before.json').write_text(json.dumps(plan,indent=2));(backup/'before.json').chmod(0o600)
        payload.update(apply=True,expected_old_pin=plan['old_pin'])
        applied=call()
        assert applied['old_pin']==plan['old_pin'] and applied['new_pin']==plan['new_pin']
        result.update(applied=True,backup=str(backup),activation='Reload this idle runtime before continuing its existing task.')
        (backup/'receipt.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
