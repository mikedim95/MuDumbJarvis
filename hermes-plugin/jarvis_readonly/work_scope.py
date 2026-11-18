"""General knowledge is durable; mission knowledge follows native issue ancestry."""
import re
GENERAL_PREFIX='[JARVIS GENERAL WORK]\n'
SCOPE_VARIABLE='jarvis_work_scope'
MISSION_VARIABLE='jarvis_mission_id'


def description_scope(description):
    if str(description or '').startswith(GENERAL_PREFIX):return {'kind':'general','mission_id':None,'routine_id':None}
    match=re.match(r'^\[JARVIS MISSION ([0-9a-f-]{36})\]\n',str(description or ''))
    return {'kind':'project','mission_id':match.group(1),'routine_id':None} if match else None


def clean_description(description):
    return re.sub(r'^\[JARVIS (?:GENERAL WORK|MISSION [0-9a-f-]{36})\]\n','',str(description or ''),count=1)


def description(text,kind,mission_id=None):
    return (GENERAL_PREFIX if kind=='general' else '[JARVIS MISSION '+str(mission_id)+']\n')+clean_description(text)


def routine_scope(routine):
    values={v.get('name'):v.get('defaultValue') for v in routine.get('variables') or []}
    kind=values.get(SCOPE_VARIABLE,'general')
    return {'kind':'project' if kind=='project' else 'general',
        'mission_id':values.get(MISSION_VARIABLE) if kind=='project' else None,
        'routine_id':routine.get('id')}


def variables(existing,kind,mission_id=None):
    retained=[v for v in existing or [] if v.get('name') not in (SCOPE_VARIABLE,MISSION_VARIABLE)]
    return retained+[
        {'name':SCOPE_VARIABLE,'type':'text','required':False,'defaultValue':kind},
        {'name':MISSION_VARIABLE,'type':'text','required':False,'defaultValue':str(mission_id or '')}]


def classify(issue,issues=(),routines=()):
    company=issue.get('companyId')
    by_id={row['id']:row for row in issues if row.get('companyId')==company}
    jobs={row['id']:row for row in routines if row.get('companyId')==company}
    current=issue;seen=set()
    for _ in range(24):
        if current['id'] in seen:break
        seen.add(current['id'])
        stamped=description_scope(current.get('description'))
        if stamped and (not current.get('parentId') or current.get('originKind')=='routine_execution'):return stamped
        if current.get('originKind')=='routine_execution' and current.get('originId') in jobs:
            return routine_scope(jobs[current['originId']])
        parent=current.get('parentId')
        if not parent:
            return {'kind':'project','mission_id':current['id'],'routine_id':None}
        if parent not in by_id:
            return {'kind':'project','mission_id':parent,'routine_id':None}
        current=by_id[parent]
    return {'kind':'project','mission_id':issue['id'],'routine_id':None}


def closed(mission):
    return mission.get('status') in ('done','cancelled') or bool(mission.get('hiddenAt'))


def guidance(scope):
    if scope['kind']=='general':
        return 'General work builds reusable team knowledge across missions. Do not automatically import mission-specific details. Standing directions apply to every assignment.'
    return ('This is a temporary mission context. Use shared General knowledge and agent directions, '
        'but keep this mission\'s findings, conversations and artifacts local to mission '+str(scope.get('mission_id'))+
        '. Do not promote its details into standing directions or General knowledge without an explicit owner request.')
