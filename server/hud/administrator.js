/* Independent global/project conversations. Capture scope before every async operation. */
(() => {
  if (!document.body.classList.contains('ai-minimal')) return;
  const el=id=>document.getElementById(id), input=el('administratorInput'), feed=el('administratorFeed');
  const states=new Map();
  let scope=null, current='default', threads=[], listVersion=0, creating=false, initialized=false, followEnd=true;
  const selectionKey=m=>m?'jarvis-project-conversation:'+m:'jarvis-general-conversation';
  const creationKey=m=>m?'jarvis-project-new-conversation:'+m:'jarvis-general-new-conversation';
  const key=(id,m=scope)=>(m||'general')+':'+id;
  const draftKey=(id,m)=>m?'jarvis-project-draft:'+m+':'+id:id==='default'?'jarvis-administrator-draft':'jarvis-general-draft:'+id;
  const visible=()=>!el('administratorPanel').hidden;
  const same=(id,m)=>id===current&&m===scope;
  const viewScope=()=>{const v=window.JarvisModes.snapshot();return v.mode==='projects'?v.missionId:null;};
  const params=(m,extra={})=>new URLSearchParams({...extra,...(m?{mission_id:m}:{})});
  async function api(path,options={}) {
    const response=await fetch('/api/admin/'+path,{cache:'no-store',...options});
    const data=await response.json().catch(()=>({}));
    if(!response.ok){const error=new Error(data.error||data.detail||'Chat is unavailable.');error.data=data;throw error;}
    return data;
  }
  const post=body=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  function state(id,m=scope) {
    const k=key(id,m);
    if(!states.has(k)){
      let saved={};try{saved=JSON.parse(localStorage.getItem(draftKey(id,m))||'{}')||{};}catch{}
      states.set(k,{draft:saved.text||'',pending:saved.pending||(saved.request_id?[saved]:[]),messages:[],loaded:false,loading:null,sending:false,status:'',work:[],workChecked:0,workLoading:false,workSignature:'',deliveryError:''});
    }
    return states.get(k);
  }
  function save(id,m){const s=state(id,m),k=draftKey(id,m);if(s.draft||s.pending.length)localStorage.setItem(k,JSON.stringify({text:s.draft,pending:s.pending}));else localStorage.removeItem(k);}
  function scrollEnd(){followEnd=true;feed.scrollTop=feed.scrollHeight;}
  feed.addEventListener('scroll',()=>{followEnd=feed.scrollHeight-feed.clientHeight-feed.scrollTop<50;});
  new ResizeObserver(()=>{if(followEnd)scrollEnd();}).observe(feed);
  function messageElement(message){
    const row=document.createElement('div');
    if(message.source?.kind==='project_result'){row.dataset.workReplyId=message.id;}
    row.className='msg '+(message.role==='user'?'you':message.role==='assistant'?'jarvis':'sys');row.textContent=message.text;
    if(message.source?.kind==='project_result'){const source=document.createElement('small');source.className='work-result-source';source.textContent=message.source.identifier+' · '+(message.source.label||'Jarvis result');row.prepend(source);}
    if(message.open){const link=document.createElement('button');link.type='button';link.textContent=message.label;link.onclick=message.open;row.append(' ',link);}
    return row;
  }
  function append(id,m,message){message.timestamp??=Date.now()/1000;state(id,m).messages.push(message);if(same(id,m)){feed.append(messageElement(message));scrollEnd();}}
  function renderComposer(){
    const s=state(current);el('administratorSend').disabled=s.sending||!threads.some(t=>t.id===current);
    const status=el('administratorStatus');
    const waiting=s.work.find(w=>w.state!=='closed'),missing=s.work.find(w=>w.state==='closed'&&!w.has_reply&&!w.superseded);
    const progress=waiting?(waiting.state==='blocked'?(waiting.identifier+' · '+(waiting.reason||'Blocked; Jarvis needs to resolve this.')):'Jarvis is working with the team…'):missing?'Work ended without a published reply.':'';
    status.textContent=s.status||s.deliveryError||(s.pending.length?'Delivery unconfirmed.':progress);
    if(!s.sending)for(const request of s.pending){
      if(s.draft.trim()===request.text.trim())continue;
      const retry=document.createElement('button');retry.type='button';retry.textContent='Retry';retry.onclick=()=>send(null,request);status.append(' ',retry);
    }
  }
  function renderThread(){
    const s=state(current);el('administratorHeading').textContent=threads.find(t=>t.id===current)?.title||(scope?'Project conversation':'General conversation');
    feed.replaceChildren(...s.messages.map(messageElement));input.value=s.draft;renderComposer();scrollEnd();
  }
  function renderList(){
    const focused=document.activeElement?.dataset.threadId;
    el('generalThreads').replaceChildren(...threads.map(thread=>{
      const button=document.createElement('button');button.type='button';button.dataset.threadId=thread.id;button.textContent=thread.title;
      button.setAttribute('aria-current',String(visible()&&thread.id===current));button.onclick=()=>selectThread(thread.id);return button;
    }));
    if(focused)[...el('generalThreads').children].find(b=>b.dataset.threadId===focused)?.focus({preventScroll:true});
  }
  async function history(id,m){
    const s=state(id,m);if(s.loaded)return;
    if(!s.loading)s.loading=api('history?'+params(m,{conversation_id:id}),{signal:AbortSignal.timeout(20000)}).then(data=>{
      s.messages=data.messages;s.work=data.work||[];s.deliveryError=data.work_error||'';s.loaded=true;s.workChecked=Date.now();if(same(id,m))renderThread();
    }).finally(()=>{s.loading=null;});
    await s.loading;
  }
  async function refreshWork(id=current,m=scope,force=false){
    const s=state(id,m);
    if(!s.loaded||s.sending||s.workLoading)return;
    const pending=s.work.some(w=>w.state!=='closed');
    if(!force&&Date.now()-s.workChecked<(pending?4000:30000))return;
    s.workLoading=true;s.workChecked=Date.now();
    try{
      const data=await api('updates?'+params(m,{conversation_id:id}),{signal:AbortSignal.timeout(20000)});
      s.work=data.work||[];s.deliveryError='';
      const signature=JSON.stringify(data.messages||[]);
      if(signature!==s.workSignature){
        s.workSignature=signature;
        const ordinary=s.messages.filter(message=>message.source?.kind!=='project_result');
        s.messages=[...ordinary,...(data.messages||[])].map((message,index)=>({message,index}))
          .sort((a,b)=>(a.message.timestamp??(-1+a.index/10000))-(b.message.timestamp??(-1+b.index/10000))||a.index-b.index).map(item=>item.message);
        if(same(id,m)){
          const atEnd=followEnd,position=feed.scrollTop;feed.replaceChildren(...s.messages.map(messageElement));
          if(atEnd)scrollEnd();else feed.scrollTop=position;
        }
      }
    }catch(error){s.deliveryError='Could not load work replies. Retrying…';}
    finally{s.workLoading=false;if(same(id,m))renderComposer();}
  }
  function readHistory(id,m){history(id,m).catch(error=>{state(id,m).status=error.message;if(same(id,m))renderComposer();});}
  function openChat(){if(scope)window.JarvisModes.setProjectView('chat');else window.JarvisModes.setMode('direct');}
  function selectThread(id){current=id;localStorage.setItem(selectionKey(scope),id);renderList();renderThread();openChat();readHistory(id,scope);}
  async function loadList(m=scope){
    const version=++listVersion;
    try{
      const data=await api('conversations?'+params(m),{signal:AbortSignal.timeout(20000)});
      if(version!==listVersion||m!==scope)return;
      threads=data.conversations.map(thread=>({...thread,title:thread.id===data.default_id?(m?'Project conversation':'General conversation'):thread.title}));
      if(!threads.some(t=>t.id===current)){current=data.default_id;localStorage.setItem(selectionKey(m),current);}
      el('generalThreadsStatus').textContent='';renderList();renderThread();if(visible())readHistory(current,m);
    }catch(error){if(version===listVersion)el('generalThreadsStatus').textContent=error.message;}
  }
  async function newThread(){
    if(creating)return;creating=true;el('newGeneralChat').disabled=true;
    const m=scope;
    try{
      const id=localStorage.getItem(creationKey(m))||crypto.randomUUID();localStorage.setItem(creationKey(m),id);
      const thread=await api('conversations',post({id,mission_id:m}));localStorage.removeItem(creationKey(m));
      if(m!==scope)return;
      ++listVersion;threads=[thread,...threads.filter(t=>t.id!==thread.id)];selectThread(thread.id);await loadList(m);
    }catch(error){if(m===scope)el('generalThreadsStatus').textContent=error.message;}
    finally{creating=false;el('newGeneralChat').disabled=false;}
  }
  function receipts(id,m,data){
    const updates=[...(data.administration_updates||[]),...(data.general_context_updates||[])];
    for(const r of updates){
      const row={role:'system'};
      if(['start_project','start_general_work','continue_project'].includes(r.action)){
        row.text=(r.action==='continue_project'?'Sent to ':'')+r.task.identifier+' · '+r.task.title;
        row.label=r.task.work_scope==='general'?'Open General work':'Open project';row.open=()=>window.JarvisModes.openProject(r.task.id);window.JarvisTasks.refresh();
      }else if(r.action==='publish_knowledge'){
        row.text='Available in General knowledge · '+r.identifier;
      }else if(r.job){
        row.text='Saved cron job: '+r.job.title;row.label='Cron jobs';row.open=async()=>{
          if(r.job.work_scope==='project'){await window.JarvisModes.openProject(r.job.mission_id);window.JarvisModes.openProjectCron();}else window.JarvisModes.setGeneralView('cron');};
      }else if(r.action==='rename_agent')row.text='Renamed '+r.name+'.';
      else if(r.action==='set_system_prompt')row.text='Saved system prompt for '+r.name+'.';
      else row.text='Saved '+(r.mission_id?'project':'general')+' directions for '+r.name+'.';
      append(id,m,row);
    }
    if(updates.some(r=>!r.job&&!r.task))window.dispatchEvent(new Event('jarvis-general-context-updated'));
  }
  async function send(event,previous){
    event?.preventDefault();const id=current,m=scope,s=state(id,m),text=previous?.text||input.value.trim();
    if(!text||s.sending||!threads.some(t=>t.id===id))return;
    let request=previous||s.pending.find(item=>item.text.trim()===text);
    if(!request){request={text,request_id:crypto.randomUUID()};s.pending.push(request);}
    if(!previous||input.value.trim()===text){input.value='';s.draft='';}save(id,m);
    s.sending=true;s.status='Jarvis is working…';renderComposer();openChat();
    const origin=window.JarvisModes.snapshot().navigationRevision;let project;
    try{
      await history(id,m);
      if(!s.messages.some(msg=>msg.requestId===request.request_id))append(id,m,{role:'user',text,requestId:request.request_id});
      const data=await api('chat',post({conversation_id:id,mission_id:m,input:text,request_id:request.request_id,prompt_scope:'administrator'}));
      project=window.JarvisModes.createdProject(data);append(id,m,{role:'assistant',text:data.text});receipts(id,m,data);
      s.pending=s.pending.filter(item=>item!==request);s.status='';save(id,m);if(m===scope)await loadList(m);
    }catch(error){
      project||=window.JarvisModes.createdProject(error.data);if(error.data)receipts(id,m,error.data);s.status=error.message;
      if(project)s.pending=s.pending.filter(item=>item!==request);
      else if(!s.draft){s.draft=text;if(same(id,m))input.value=text;}save(id,m);
    }finally{
      s.sending=false;refreshWork(id,m,true);
      if(same(id,m)){renderComposer();if(visible()){
        if(project&&window.JarvisModes.snapshot().navigationRevision===origin)await window.JarvisModes.openProject(project.id);else input.focus();
      }}
    }
  }
  function activate(){
    const v=window.JarvisModes.snapshot(),m=viewScope(),workspace=v.mode!=='projects'||v.projectView!=='list'&&m;
    if(!workspace)return;
    if(!initialized||m!==scope){initialized=true;scope=m;current=localStorage.getItem(selectionKey(m))||'default';threads=[];renderThread();renderList();loadList(m);}
    else{renderList();if(visible()&&threads.some(t=>t.id===current)){readHistory(current,m);refreshWork(current,m,true);}}
  }
  input.addEventListener('input',()=>{const s=state(current);s.draft=input.value;save(current,scope);if(s.pending.length&&!s.sending)renderComposer();});
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();send();}});
  el('administratorForm').addEventListener('submit',send);el('newGeneralChat').onclick=newThread;
  window.addEventListener('jarvis-mode-changed',activate);
  window.addEventListener('jarvis-tasks-updated',()=>{if(!initialized||viewScope()!==scope)activate();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&visible())refreshWork(current,scope,true);});
  setInterval(()=>{if(!document.hidden&&visible())refreshWork();},5000);
  renderThread();activate();
})();
