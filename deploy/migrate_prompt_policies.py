#!/usr/bin/env python3
"""Plan/apply prompt v2 only; never creates work, pauses, resumes, or restarts agents.

Review a private plan, then apply it during an operator-managed idle window.
Unknown/custom prompts and skills are retained byte for byte. All changes have a
private rollback receipt, exact source checks, and the HUD's configuration lock.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID, uuid4

import staffing

policy = staffing.prompt_policies


def fingerprint(agent):
    return policy.digest(json.dumps({k: agent.get(k) for k in
        ('adapterConfig','metadata','permissions','runtimeConfig','name','reportsTo','role')},
        sort_keys=True,separators=(',',':')))


def home_for(root, agent, ceo):
    return Path(root) / ('.runtime/hermes-ceo' if agent['id'] == ceo else
        '.runtime/employees/' + str(UUID(agent['id'])))


def file_text(path, root):
    if any(p.is_symlink() for p in (path,*path.parents) if p == root or root in p.parents):
        raise ValueError('Refusing symlinked policy path: ' + str(path.relative_to(root)))
    return path.read_text() if path.exists() else None


def entry(agent, root, ceo):
    role = 'ceo' if agent['id'] == ceo else staffing.registry.employee_profile(agent)
    if role not in policy.ROLES:
        raise ValueError('Agent has no v2 role policy')
    item = staffing.registry.profile(role) if role != 'ceo' else None
    default = policy.assemble(role,agent['name'],item['authority'] if item else '')
    meta = (agent.get('metadata') or {}).get('jarvis') or {}
    prior = meta.get('prompt_policy') or {}
    adapter=agent.get('adapterConfig') or {}
    template=adapter.get('payloadTemplate') or {}
    if not isinstance(template,dict) or template.get('system_message'):
        raise ValueError('Native prompt is shadowed by an alternate/unknown payload template; operator review required')
    native = adapter.get('instructions') or ''
    if not isinstance(native,str):raise ValueError('Native instructions must be text')
    # Validates saved overrides, including bad hashes, before any migration write.
    staffing.configured_agent_prompt(agent,default)
    saved = (meta.get('system_prompts') or {}).get('agent')
    managed = saved is None and (not native or policy.is_legacy(native,role,item) or
        (prior.get('native_managed') is True and prior.get('native_sha256') == policy.digest(native)))
    after = default if managed else native
    files = []
    soul = policy.identity_soul(agent['name']) if after.startswith('[JARVIS PROMPT POLICY v2]\n') else default
    candidates = {'SOUL.md': soul, **{'skills/'+name+'/SKILL.md': text for name,text in policy.skills(role).items()}}
    for path,text in candidates.items():
        before = file_text(home_for(root,agent,ceo) / path,Path(root))
        legacy = policy.is_legacy(before,role,item) if path == 'SOUL.md' and before is not None else (
            item is not None and before == policy.legacy_skill(item,policy.ROLES[role][1]))
        known = before is None or legacy or (prior.get('files') or {}).get(path) == policy.digest(before)
        files.append({'path':path,'before':before,'after':text if known else before,
            'disposition':'managed_default' if known else 'preserved_custom'})
    adopted = after.startswith('[JARVIS PROMPT POLICY v2]\n') or any(
        f['path'] == 'SOUL.md' and str(f['after']).startswith('[JARVIS PROMPT POLICY v2]\n') for f in files)
    record = policy.provenance(role,after,{f['path']:f['after'] for f in files
        if f['disposition']=='managed_default'},managed) if adopted else meta.get('prompt_policy')
    return {'agent_id':agent['id'],'name':agent['name'],'role':role,'fingerprint':fingerprint(agent),
        'native':{'before':native,'after':after,'disposition':'managed_default' if managed else 'preserved_custom'},
        'policy_before':meta.get('prompt_policy'),'policy_after':record,'files':files}


def roster(board):
    company,ceo = board.env['PAPERCLIP_COMPANY_ID'],board.env['PAPERCLIP_CEO_AGENT_ID']
    return [a for a in board.api('GET','/companies/'+company+'/agents') if
        a.get('companyId') == company and a.get('status') != 'terminated' and
        (a['id'] == ceo or (a.get('reportsTo') == ceo and staffing.registry.employee_profile(a) in policy.ROLES))]


def make_plan(board, root=staffing.ROOT, agent_id=None):
    people=roster(board)
    if agent_id:
        people=[a for a in people if a['id'] == agent_id]
        if not people:raise ValueError('Choose an existing CEO or specialist in this company')
    roles=['ceo' if a['id'] == board.env['PAPERCLIP_CEO_AGENT_ID'] else staffing.registry.employee_profile(a) for a in people]
    if len(roles) != len(set(roles)):
        raise ValueError('Duplicate existing role; select one exact agent with --agent-id for review')
    return {'version':2,'company_id':board.env['PAPERCLIP_COMPANY_ID'],
        'ceo_id':board.env['PAPERCLIP_CEO_AGENT_ID'],
        'agents':[entry(a,root,board.env['PAPERCLIP_CEO_AGENT_ID']) for a in people]}


def ensure_idle(board, identifiers):
    live = board.api('GET','/companies/'+board.env['PAPERCLIP_COMPANY_ID']+'/live-runs')
    if any(r.get('agentId') in identifiers and r.get('status') in ('queued','running') for r in live):
        raise ValueError('Selected agents have active/queued work; migration deferred without changing tasks')
    for identifier in identifiers:
        agent=board.api('GET','/agents/'+identifier)
        if agent.get('status') in ('running','pending_approval'):
            raise ValueError('Selected agent is not idle; migration deferred')


def write_file(path, text):
    if text is None:
        path.unlink(missing_ok=True)
    else:
        # Source was checked under lock. Replace atomically, with private mode.
        temporary=path.with_name('.'+path.name+'.'+uuid4().hex)
        staffing.write_private(temporary,text)
        temporary.replace(path)


def patch_native(board, agent, item, reverse=False):
    metadata=copy.deepcopy(agent.get('metadata') or {})
    jarvis=metadata.setdefault('jarvis',{})
    record=item['policy_before' if reverse else 'policy_after']
    if record is None:jarvis.pop('prompt_policy',None)
    else:jarvis['prompt_policy']=record
    desired=item['native']['before' if reverse else 'after']
    body={'metadata':metadata}
    if desired != ((agent.get('adapterConfig') or {}).get('instructions') or ''):
        body['adapterConfig']={**agent.get('adapterConfig',{}),'instructions':desired}
    result=board.api('PATCH','/agents/'+agent['id'],body)
    if ((result.get('adapterConfig') or {}).get('instructions') or '') != desired or result.get('metadata') != metadata:
        raise ValueError('Native migration was not confirmed; inspect the private backup before recovery')


def apply_plan(board, plan, root=staffing.ROOT):
    root=Path(root);ceo=board.env['PAPERCLIP_CEO_AGENT_ID']
    if plan.get('version') != 2 or plan.get('company_id') != board.env['PAPERCLIP_COMPANY_ID'] or plan.get('ceo_id') != ceo:
        raise ValueError('Plan company or policy version does not match')
    by_id={a['id']:a for a in roster(board)}
    selected=plan.get('agents') or []
    if not selected or len({e['agent_id'] for e in selected}) != len(selected) or any(
            e['agent_id'] not in by_id or entry(by_id[e['agent_id']],root,ceo) != e for e in selected):
        raise ValueError('Prompt/configuration conflict or changed policy source; generate and review a fresh plan')
    ensure_idle(board,set(e['agent_id'] for e in selected))
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    backup=root/'.runtime/backups/prompt-policies'/stamp/'receipt.json'
    backup.parent.mkdir(parents=True,mode=0o700)
    staffing.write_private(backup,json.dumps(plan,indent=2))
    # Validation above prevents an ordinary stale plan from partially applying.
    # Locks also protect against HUD/reconciler edits during each actual mutation.
    try:
        for item in selected:
            identifier=item['agent_id']
            with staffing._configuration_lock.lock(identifier):
                agent=board.api('GET','/agents/'+identifier)
                if entry(agent,root,ceo) != item:
                    raise ValueError('Concurrent owner edit')
                ensure_idle(board,{identifier})
                home=home_for(root,agent,ceo)
                for f in item['files']:
                    if f['before'] != f['after']:write_file(home/f['path'],f['after'])
                patch_native(board,agent,item)
    except Exception as error:
        raise RuntimeError('Migration stopped; review partial application before retrying. '
            'Conflict-aware rollback receipt: '+str(backup)) from error
    return backup


def rollback(board, receipt, root=staffing.ROOT):
    """Restore only migrated prompt fields; refuse to erase subsequent owner edits."""
    root=Path(root);ceo=board.env['PAPERCLIP_CEO_AGENT_ID']
    if receipt.get('company_id') != board.env['PAPERCLIP_COMPANY_ID'] or receipt.get('ceo_id') != ceo or receipt.get('version') != 2:
        raise ValueError('Backup belongs to another company/policy')
    known={a['id']:a for a in roster(board)}
    for item in receipt['agents']:
        identifier=item['agent_id']
        if identifier not in known:raise ValueError('Backup agent is outside the current team')
        with staffing._configuration_lock.lock(identifier):
            ensure_idle(board,{identifier});agent=board.api('GET','/agents/'+identifier)
            home=home_for(root,agent,ceo)
            allowed={'SOUL.md',*('skills/'+n+'/SKILL.md' for n in policy.skills(item['role']))}
            native=(agent.get('adapterConfig') or {}).get('instructions') or ''
            marker=((agent.get('metadata') or {}).get('jarvis') or {}).get('prompt_policy')
            if native not in (item['native']['before'],item['native']['after']) or marker not in (item['policy_before'],item['policy_after']):
                raise ValueError('Owner changed native prompt after migration; rollback refused')
            for f in item['files']:
                if f['path'] not in allowed:raise ValueError('Backup contains an invalid policy path')
                if file_text(home/f['path'],root) not in (f['before'],f['after']):
                    raise ValueError('Owner changed local policy after migration; rollback refused')
            for f in item['files']:
                if f['before'] != f['after']:write_file(home/f['path'],f['before'])
            patch_native(board,agent,item,reverse=True)


def summary(plan):
    return [{'agent_id':e['agent_id'],'name':e['name'],'native':e['native']['disposition'],
        'native_changes':e['native']['before'] != e['native']['after'],
        'files':[{'path':f['path'],'disposition':f['disposition'],'changes':f['before'] != f['after']} for f in e['files']]}
        for e in plan['agents']]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--plan',type=Path,help='Write a private reviewable plan; no native writes')
    mode.add_argument('--apply',type=Path,help='Apply an unchanged reviewed plan to idle agents only')
    mode.add_argument('--rollback',type=Path,help='Restore prompt fields from a migration receipt without erasing later edits')
    parser.add_argument('--agent-id',type=lambda v:str(UUID(v)),help='Limit planning to one existing agent')
    args=parser.parse_args();board=staffing.Board(staffing.settings())
    if args.apply:
        backup=apply_plan(board,json.loads(args.apply.read_text()))
        print(json.dumps({'applied':True,'backup':str(backup),'restarts':0,'task_changes':0,
            'activation':'Local SOUL/skills and cached plugin code require a separately scheduled idle-runtime reload. No workers were restarted.'}))
    elif args.rollback:
        rollback(board,json.loads(args.rollback.read_text()))
        print(json.dumps({'rolled_back':True,'restarts':0,'task_changes':0}))
    else:
        plan=make_plan(board,agent_id=args.agent_id)
        if args.plan:staffing.write_private(args.plan,json.dumps(plan,indent=2))
        print(json.dumps({'plan_only':True,'plan':str(args.plan) if args.plan else None,'agents':summary(plan)}))


if __name__ == '__main__':
    main()
