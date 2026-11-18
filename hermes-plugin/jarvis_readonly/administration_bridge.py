"""Owner administration through a request-scoped HUD callback, without board credentials."""
import json
import os
import urllib.error
import urllib.request


def manage(args, **kwargs):
    if os.environ.get('JARVIS_AGENT_ROLE') or os.environ.get('JARVIS_PROFILE'):
        raise PermissionError('Use the human Administrator chat')
    request=urllib.request.Request('http://jarvis:8765/api/admin/tool',
        data=json.dumps(args).encode(),method='POST',headers={
            'Authorization':'Bearer '+os.environ['API_SERVER_KEY'],'Content-Type':'application/json'})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request,timeout=30) as response:
            return json.dumps(json.load(response))
    except urllib.error.HTTPError as error:
        try:message=json.load(error).get('detail','Administrator operation failed')
        except Exception:message='Administrator operation failed'
        return json.dumps({'error':message,'saved':False})


def register(ctx):
    if os.environ.get('JARVIS_AGENT_ROLE') or os.environ.get('JARVIS_PROFILE'):
        return
    ctx.register_tool(name='jarvis_administrator',toolset='jarvis_readonly',handler=manage,
        schema={'name':'jarvis_administrator','description':
            'In authenticated Direct and General chat, use start_project to open a project when the owner '
            'assigns new work to you as CEO, including requests phrased as questions. Answer information requests directly. '
            'In General chat you can also read or edit system prompts, rename staff, use start_general_work '
            'for explicitly shared team knowledge, or schedule recurring work with schedule_project. '
            'Schedules default to work_scope=general. A mission schedule requires work_scope=project and mission_id. '
            'Use list_schedules to read job IDs and project scopes; set_schedule_status pauses, resumes or archives a native job. Ongoing work needs a real schedule; saving directions alone does not schedule execution. '
            'Use the active request_id supplied by the HUD. '
            'Read first; set_system_prompt requires the current prompt_sha256 as expected_sha256. '
            'Provide the exact agent_id and scope (agent, direct, administrator); the selected prompt in the '
            'chat is the default target unless the user names another. Use general_context for standing notes. '
            'Act on clear ordinary requests without demanding special phrases. Saved prompts apply next turn. '
            'Only an actual native receipt confirms a change. Direct authorizes only start_project.',
            'parameters':{'type':'object','properties':{
                'request_id':{'type':'string'},
                'action':{'type':'string','enum':['read','rename_agent','set_system_prompt','start_project','start_general_work','schedule_project','set_schedule_status','list_schedules']},
                'agent_id':{'type':'string'},'scope':{'type':'string','enum':['agent','direct','administrator']},
                'name':{'type':'string','maxLength':80},'text':{'type':'string','maxLength':20000,
                    'description':'Full replacement system prompt or recurring job goal. New projects preserve the latest owner message.'},
                'assignment_context':{'type':'string','maxLength':3000,'description':'Only if the owner referred to earlier turns, include the prior facts needed to understand this assignment. Keep the original scope.'},
                'expected_sha256':{'type':'string'},'title':{'type':'string','maxLength':120},
                'cron_expression':{'type':'string','description':'Five cron fields; default 0 9 * * * (daily 09:00).'},
                'timezone':{'type':'string'},'project_id':{'type':'string'},'job_id':{'type':'string'},
                'work_scope':{'type':'string','enum':['general','project'],'description':'General work is reusable across missions; project work is local to mission_id.'},
                'mission_id':{'type':'string','description':'Native CEO mission issue ID, required for a project-scoped schedule.'},
                'status':{'type':'string','enum':['active','paused','archived']}},
                'required':['request_id','action'],'additionalProperties':False}})
