"""Direct Chat can manage only request-authorized general notes through the HUD."""
import json
import os
import urllib.error
import urllib.request


def manage(args, **kwargs):
    if os.environ.get('JARVIS_AGENT_ROLE') or os.environ.get('JARVIS_PROFILE'):
        raise PermissionError('General directions are edited through the human Direct Chat only')
    request = urllib.request.Request('http://jarvis:8765/api/general-context/tool',
        data=json.dumps(args).encode(),method='POST',headers={
            'Authorization':'Bearer '+os.environ['API_SERVER_KEY'],'Content-Type':'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request,timeout=20) as response:
            return json.dumps(json.load(response))
    except urllib.error.HTTPError as error:
        try:
            message=json.load(error).get('detail','General context operation failed')
        except Exception:
            message='General context operation failed'
        return json.dumps({'error':message,'saved':False})


def register(ctx):
    if os.environ.get('JARVIS_AGENT_ROLE') or os.environ.get('JARVIS_PROFILE'):
        return
    ctx.register_tool(name='general_context',toolset='jarvis_readonly',handler=manage,
        schema={'name':'general_context','description':'Read persistent general directions for Jarvis or its workers. '
            'In Direct Chat append or replace when the latest human request explicitly asks to save general directions. '
            'In Administrator chat act on clearly requested standing directions without requiring special phrases, '
            'using the active request_id and authorized agent IDs supplied by the HUD. This never creates project work '
            'or changes permissions. A successful saved receipt is required before saying directions were stored.',
            'parameters':{'type':'object','properties':{
                'request_id':{'type':'string'},'action':{'type':'string','enum':['read','append','replace']},
                'agent_id':{'type':'string','description':'Exact registered agent UUID; omit only for read-all.'},
                'text':{'type':'string','maxLength':8000},'expected_revision':{'type':'integer','minimum':0}},
                'required':['request_id','action'],'additionalProperties':False}})
