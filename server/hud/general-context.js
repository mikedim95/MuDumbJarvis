/* The agent's Context button edits general and mission-local directions separately. */
(() => {
  if(!document.body.classList.contains('ai-minimal'))return;
  const el=id=>document.getElementById(id),input=el('generalContextText'),drafts=new Map();
  let selected=null,mission=null,scope='general',data=null,version=0,saving=false;
  const key=()=>[selected,mission,scope].join(':');
  const active=()=>!el('generalContextPanel').hidden;
  const remember=()=>{if(data)drafts.set(key(),input.value);};
  async function api(options){
    const response=await fetch('/api/agents/'+selected+'/context'+(mission?'?mission_id='+encodeURIComponent(mission):''),{cache:'no-store',...options});
    const result=await response.json();if(!response.ok)throw new Error(result.detail||'Context unavailable.');return result;
  }
  function render(){
    el('generalContextHeading').textContent=(data?.name||'Agent')+' · Context';
    el('agentGeneralScope').setAttribute('aria-pressed',String(scope==='general'));
    el('agentProjectScope').hidden=!mission;el('agentProjectScope').setAttribute('aria-pressed',String(scope==='project'));
    el('contextScopeHint').textContent=scope==='general'?'Standing directions used on every project.':'Directions for this project, applied together with this agent’s general directions.';
    input.value=drafts.get(key())??data?.[scope]?.text??'';input.disabled=!data||saving;
    el('saveAgentContext').disabled=!data||saving;el('reloadAgentContext').disabled=saving;
    el('agentGeneralScope').disabled=el('agentProjectScope').disabled=saving;
    el('administratorPrompt').textContent=data?.system_prompt||'No additional system prompt.';
    el('administratorPromptLabel').textContent=data?.name||'';
  }
  async function load(){
    const v=++version;data=null;render();el('generalContextStatus').textContent='Loading…';
    try{const result=await api();if(v!==version||!active())return;data=result;render();el('generalContextStatus').textContent='';}
    catch(error){if(v===version)el('generalContextStatus').textContent=error.message;}
  }
  function change(next){remember();scope=next;render();el('generalContextStatus').textContent='';}
  el('agentGeneralScope').onclick=()=>change('general');el('agentProjectScope').onclick=()=>change('project');
  el('reloadAgentContext').onclick=()=>{drafts.delete(key());load();};
  el('contextBackBtn').onclick=()=>{remember();window.JarvisAgents.open(selected);};
  input.addEventListener('input',()=>drafts.set(key(),input.value));
  el('agentContextForm').onsubmit=async event=>{
    event.preventDefault();if(saving||!data)return;
    const target=key(),v=version,content=input.value,section=scope,agent=selected,project=mission;
    saving=true;render();el('generalContextStatus').textContent='Saving…';
    try{
      const response=await fetch('/api/agents/'+agent+'/context',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        scope:section,text:content,expected_revision:data[section]?.revision??null,mission_id:project})});
      const result=await response.json();if(!response.ok)throw new Error(result.detail||'Save failed.');
      drafts.delete(target);if(v===version&&data){data[section]=result;el('generalContextStatus').textContent='Saved. Applies next turn.';}
      window.dispatchEvent(new Event('jarvis-general-context-updated'));
    }catch(error){if(v===version)el('generalContextStatus').textContent=error.message;}
    finally{saving=false;if(active())render();}
  };
  window.JarvisGeneralContext={
    open(id){remember();selected=id;const view=window.JarvisModes.snapshot();mission=view.mode==='projects'&&view.projectView!=='list'?view.missionId:null;scope=mission?'project':'general';data=null;window.JarvisModes.openAgentContext();load();},
    selectedAgentId:()=>active()?selected:null,
    selectedTarget:async()=>({scope:'administrator',agent_id:null})
  };
})();
