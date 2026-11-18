import React,{useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react';
import {AnimatePresence,MotionConfig} from 'motion/react';
import CSIWindow from './CSIWindow.jsx';
import {PANELS,clampRect,safeTerminal,channelMessages,eventText} from './state.mjs';
import {Identity,Files,Warnings,OperationLog,Links,CaseTimeline,Network,Metadata,Decryption} from './panels.jsx';
import {popupMode,visibleSource,popupKey,boundedWindows,shouldPublishReply,visibleWindows,approvalPopupAllowed} from './popup-mode.mjs';
import './auto-popups.css';

const STORAGE='jarvis-agent-popups-v1';
const PRIORITY={warning:9,agent:8.5,files:8,decryption:7,network:6,log:5,identity:4,graph:3,metadata:2,timeline:1};
const nativeKey=(taskId,panel)=>`case:${taskId}:${panel}`;
const fingerprint=task=>[task.updatedAt,task.status,task.executionRunId].join('|');
const baselineRecord=task=>({fingerprint:fingerprint(task),updatedAt:task.updatedAt,
 status:task.status,executionRunId:task.executionRunId});
const bounded=values=>values.slice(-600);
const currentMode=()=>{
 const view=window.JarvisModes?.snapshot?.();
 return popupMode(view?.mode,document.body.classList.contains('ai-minimal'),view?.projectView,view?.generalView);
};
function preferences(){
 try{
  const saved=JSON.parse(localStorage.getItem(STORAGE)||'null');
  if(saved?.version!==1)return {rects:{},closed:[],seen:[],open:[]};
  return {rects:saved.rects&&typeof saved.rects==='object'?saved.rects:{},
   closed:Array.isArray(saved.closed)?saved.closed.filter(v=>typeof v==='string').slice(-80):[],
   seen:Array.isArray(saved.seen)?saved.seen.filter(v=>typeof v==='string').slice(-600):[],
   objective:typeof saved.objective==='string'?saved.objective:null,
   open:Array.isArray(saved.open)?saved.open.filter(v=>v&&typeof v.taskId==='string'&&PANELS[v.panel]).slice(-3):[]};
 }catch{return {rects:{},closed:[],seen:[],open:[]};}
}
function defaultRect(panel,stage){
 const width=Math.min(panel==='agent'?410:350,stage.width-20),height=Math.min(panel==='agent'?480:panel==='files'?310:280,stage.height-20);
 const left=['identity','files','metadata','decryption'].includes(panel);
 return clampRect({x:left?12:stage.width-width-12,y:panel==='warning'?Math.min(310,stage.height-height-12):16,
  width,height},stage);
}
function nativePanels(events){
 const found=new Set();
 for(const e of events){
  if(e.type==='analysis.warning'||e.type==='task.failed')found.add('warning');
  else if(e.type==='evidence.file_recovered')found.add('files');
  else if(e.type==='identity.partial_match_found'&&e.provenance==='verified_tool_output')found.add('identity');
  else if(e.type==='network.trace'&&e.provenance==='verified_tool_output')found.add('network');
  else if(e.type==='decryption.progress'&&e.provenance==='verified_tool_output')found.add('decryption');
  else if(e.type==='identity.updated')found.add('identity');
  else if(e.type==='task.progress'&&(e.data?.tool||e.source_ref?.run_id||e.provenance==='agent_summary'))found.add('log');
 }
 // Artifact metadata travels with the file card instead of opening a second
 // popup for the same discovery. Aggregate timeline ticks are not findings.
 if(!found.has('files')&&events.some(e=>e.type==='evidence.metadata'))found.add('metadata');
 const relations=events.filter(e=>e.type==='graph.node_discovered');
 if(relations.length>=3&&relations.some(e=>['artifact','task'].includes(e.data?.node?.kind)))found.add('graph');
 return [...found].sort((a,b)=>PRIORITY[b]-PRIORITY[a]);
}

function ChatActivity({entry}){
 return <div className="csi-auto-chat-activity">
  <p className="csi-label">LIVE CONVERSATION ACTIVITY</p>
  <ul>{entry.activity.map(e=><li key={e.id}>
   <strong>{e.kind==='tool'?`Tool started: ${e.name}`:e.kind==='error'?'Chat could not complete':'Reply completed'}</strong>
   {e.preview&&<pre>{e.preview}</pre>}
   {e.message&&<p>{e.message}</p>}
   {e.kind==='tool'&&<small>Execution was requested; this event does not establish a successful result.</small>}
   {e.runtime?.provider&&<small>{e.runtime.provider}{e.runtime.model?' · '+e.runtime.model:''}</small>}
   {e.reference&&<small>Reference: {e.reference}</small>}
  </li>)}</ul>
 </div>;
}

function ApprovalRequests({entry}){
 const [feedback,setFeedback]=useState(''),[deciding,setDeciding]=useState(false);
 const approvals=(entry.data.approvals||[]).filter(a=>['pending','revision_requested'].includes(a.status));
 const decide=async(id,decision)=>{setDeciding(true);setFeedback('Recording your decision…');
  const result=await window.JarvisTasks?.decide(id,decision,'Human decision from the approval popup.');
  setFeedback(result?'Decision recorded.':window.JarvisTasks?.snapshot().error||'Could not record the decision.');setDeciding(false);};
 return <div className="csi-objective"><p className="csi-label">YOUR APPROVAL IS REQUIRED</p>
  {approvals.map(a=><section className="csi-objective-approval" key={a.id} data-approval-id={a.id}>
   <strong>{a.proposal?.name||a.proposal?.title||a.type}</strong>
   <pre>{a.hiring_reason||a.proposal?.reason||a.proposal?.summary||a.proposal?.proposal||'Review this request before deciding.'}</pre>
   {a.proposal?.scope&&<pre>{typeof a.proposal.scope==='string'?a.proposal.scope:JSON.stringify(a.proposal.scope,null,2)}</pre>}
   <small>Approval {a.id} · {a.status}</small>
   <div className="cron-actions"><button type="button" disabled={deciding} onClick={()=>decide(a.id,'approve')}>Approve</button>
    <button type="button" disabled={deciding} onClick={()=>decide(a.id,'reject')}>Reject</button></div>
   <p>In the project conversation, reply with <code>/approve {a.id}</code> or <code>/reject {a.id}</code>, optionally followed by a note.</p>
  </section>)}
  {feedback&&<p role="status">{feedback}</p>}</div>;
}

function ObjectiveActivity({entry}){
 const data=entry.data,task=data.task,people=data.agents||[],employee=people.find(a=>a.id===task.assigneeAgentId);
 const messages=channelMessages(data),plans=messages.filter(e=>e.data.update_kind==='plan');
 const reply=messages.filter(e=>e.data.update_kind!=='plan').at(-1);
 const operator=(data.events||[]).filter(e=>e.task_id===task.id&&e.provenance==='native_record'&&e.source_ref?.comment_id&&typeof e.data?.text==='string').at(-1);
 const awaitingReply=entry.followupPending||!!(operator&&(!reply||Date.parse(operator.occurred_at)>Date.parse(reply.occurred_at)));
 const activity=(data.events||[]).filter(e=>e.type==='task.failed'||e.type==='analysis.warning'||
  (e.type==='task.progress'&&e.provenance!=='agent_summary')).slice(-2).reverse();
 const children=(data.graph?.nodes||[]).filter(n=>n.kind==='task'&&n.native_id!==task.id);
 const nodeById=new Map((data.graph?.nodes||[]).map(n=>[n.id,n]));
 const relations=(nodeId,label)=>(data.graph?.edges||[]).filter(e=>e.source===nodeId&&e.label===label).map(e=>nodeById.get(e.target)).filter(Boolean);
 const approvals=(data.approvals||[]).filter(a=>['pending','revision_requested'].includes(a.status));
 return <div className="csi-objective" data-ceo-task-id={task.id}>
  <div className="csi-objective-heading"><strong>{task.identifier||task.id}</strong><span className="csi-badge">{task.status||'recorded'}</span></div>
  <p className="csi-objective-title">{task.title}</p>
  {employee?<section className="csi-objective-executor"><strong>{employee.name}</strong>
   <span>{employee.role} · {employee.status||'status unavailable'}</span>
   <small>{[employee.provider,employee.model].filter(Boolean).join(' · ')||'Model not recorded'}</small>
  </section>:<p className="csi-muted">{task.assigneeAgentId?'Assignment recorded. Loading registered employee identity.':'No assigned employee is recorded.'}</p>}
  {people.filter(a=>a.id!==task.assigneeAgentId).map(a=><p className="csi-objective-worker" key={a.id}>
   <strong>{a.name}</strong> · {a.role} · {a.status||'status unavailable'}</p>)}
  {children.length>0&&<ul className="csi-objective-children">{children.map(n=><li key={n.id}><strong>{n.label}</strong> · {n.status||'recorded'}
   <small>{relations(n.id,'assigned to').map(a=>a.label).join(', ')||'No assignee recorded'}</small>
   {relations(n.id,'depends on').length>0&&<small>Depends on: {relations(n.id,'depends on').map(d=>d.label+' · '+d.status).join(', ')}</small>}
   {relations(n.id,'execution').slice(-2).map(r=><small key={r.id}>Run {r.native_id.slice(0,8)} · {r.status||'recorded'}</small>)}
  </li>)}</ul>}
  {approvals.map(a=><section className="csi-objective-approval" key={a.id} data-approval-id={a.id}>
   <p className="csi-label">HUMAN APPROVAL · {a.status}</p><strong>{a.proposal?.name||a.proposal?.title||a.type}</strong>
   <pre>{a.hiring_reason||a.proposal?.reason||a.proposal?.summary||a.proposal?.proposal||'Review the native scoped proposal before deciding.'}</pre>
   {a.proposal?.scope&&<pre>{typeof a.proposal.scope==='string'?a.proposal.scope:JSON.stringify(a.proposal.scope,null,2)}</pre>}
   <small>Approval: {a.id}</small><p>Reply with <code>/approve {a.id}</code> or <code>/reject {a.id}</code>, optionally followed by a note.</p>
  </section>)}
  {awaitingReply&&<p className="csi-muted">Your follow-up is recorded. Awaiting a new published JARVIS reply.</p>}
  {reply?<section className="csi-objective-response"><p className="csi-label">{awaitingReply?'PREVIOUS PUBLISHED REPLY':task.status==='done'?'JARVIS CONSOLIDATED RESULT':'PUBLISHED JARVIS UPDATE'}</p>
   <pre>{window.JarvisCEOInput?.publishedText?.(reply.data.text)??reply.data.text}</pre><small>Agent summary · Paperclip comment {reply.source_ref?.comment_id}</small>
   {reply.data.text.length>=2400&&<small>Published text excerpt limited by the monitoring API.</small>}
  </section>:<p className="csi-muted">{task.status==='done'?'Paperclip marked this task done; no assignee-authored result is recorded.':'Awaiting a published update from the assigned employee.'}</p>}
  {(data.artifacts||[]).length>0&&<p className="csi-objective-artifacts">{data.artifacts.map(a=><a key={a.id}
   href={'/api/tasks/'+encodeURIComponent(a.issueId)+'/artifacts/'+encodeURIComponent(a.id)} download>{a.originalFilename}</a>)}</p>}
  {plans.length>0&&<section><p className="csi-label">PUBLISHED EXECUTION PLAN</p><pre>{plans.at(-1).data.text}</pre></section>}
  {activity.length>0&&<section className="csi-objective-progress"><p className="csi-label">LATEST RECORDED ACTIVITY</p>{activity.map(e=><article key={e.id}>
   <strong>{e.title}</strong><small>{e.provenance==='verified_tool_output'?'Verified tool output':'Paperclip record'}</small>
   {e.provenance==='verified_tool_output'?<pre>{JSON.stringify(e.data.result??e.data,null,2)}</pre>:<pre>{eventText(e)}</pre>}
  </article>)}</section>}
 </div>;
}

/** Automatic presentation only. No task mutation, inference request or finding cache. */
export default function AutoPopups(){
 const initial=useRef(preferences()),prefs=initial.current;
 const seen=useRef(new Set(prefs.seen)),closed=useRef(new Set(prefs.closed)),windowsRef=useRef({}),activeCase=useRef(null);
 const selectedObjective=useRef(prefs.objective||prefs.open.find(p=>p.panel==='agent')?.taskId||null);
 const publishedReplies=useRef(new Set());
 const [windows,setWindows]=useState({}),[focused,setFocused]=useState(null);
 const [mode,setMode]=useState(currentMode),modeRef=useRef(mode);
 modeRef.current=mode;
 const [stage,setStage]=useState({width:window.innerWidth,height:Math.max(180,window.innerHeight-190)});
 const stageRef=useRef(stage),host=useRef(null),nativeData=useRef(null);
 stageRef.current=stage;windowsRef.current=windows;
 const compact=stage.width<680;
 const persist=useCallback(next=>{
  try{localStorage.setItem(STORAGE,JSON.stringify({version:1,rects:prefs.rects,
   closed:[...closed.current].slice(-80),seen:bounded([...seen.current]),
   objective:selectedObjective.current,
   open:Object.values(next).filter(e=>e.source==='task').slice(-3).map(e=>({taskId:e.taskId,panel:e.panel}))}));}catch{}
 },[prefs]);
 const update=useCallback((panel,entry,{highlight=true,focus=highlight}={})=>{
  if(!approvalPopupAllowed(entry))return;
  if(closed.current.has(entry.key))return;
  const now=Date.now();
  setWindows(previous=>{
   const id=popupKey({...entry,panel}),prior=previous[id];
   const next={...previous,[id]:{...entry,panel,at:now,updated:highlight?now:prior?.updated,
    rect:prior?.key===entry.key?prior.rect:clampRect(prefs.rects[panel]||defaultRect(panel,stageRef.current),stageRef.current)}};
   const limit=stageRef.current.width<680?1:3;
   const boundedNext=boundedWindows(next,limit,PRIORITY,modeRef.current);
   persist(boundedNext);return boundedNext;
  });
  if(focus&&visibleSource(modeRef.current,entry.source))setFocused(popupKey({...entry,panel}));
 },[persist,prefs]);
 const dismiss=useCallback(id=>{
  setWindows(previous=>{const entry=previous[id];if(entry)closed.current.add(entry.key);
   const next={...previous};delete next[id];persist(next);return next;});
 },[persist]);

 useEffect(()=>{
  const listener=event=>{
   const e=event.detail;
   if(e?.surface==='administrator')return;
   if(!e||!['tool','reply','error'].includes(e.kind)||typeof e.request_id!=='string')return;
   const name=typeof e.tool?.name==='string'?e.tool.name:'tool';
   const eventId=`chat:${e.request_id}:${e.kind}:${name}:${e.run_id||''}:${e.reference||''}`;
   if(seen.current.has(eventId))return;seen.current.add(eventId);
   if(e.kind==='reply'){
    const previous=windowsRef.current['chat:log'];
    if(previous?.source!=='chat'||previous.requestId!==e.request_id)return;
    update('log',{...previous,status:'reply complete',activity:[...previous.activity,
     {id:eventId,kind:'reply',runtime:e.runtime}].slice(-16)});
   }else if(e.kind==='tool'){
    const key=`chat:${e.request_id}:log`,previous=windowsRef.current['chat:log'];
    const activity=previous?.key===key?previous.activity:[];
    update('log',{key,source:'chat',requestId:e.request_id,status:'tool started',activity:[...activity,
     {id:eventId,kind:'tool',name,preview:typeof e.tool?.preview==='string'?safeTerminal(e.tool.preview).slice(0,500):''}].slice(-16)});
   }else{
    update('warning',{key:`chat:${e.request_id}:warning`,source:'chat',requestId:e.request_id,status:'chat error',
     activity:[{id:eventId,kind:'error',message:typeof e.message==='string'?e.message:'The chat could not complete.',
      reference:typeof e.reference==='string'?e.reference:null}]});
   }
  };
  window.addEventListener('jarvis-ai-activity',listener);
  return()=>window.removeEventListener('jarvis-ai-activity',listener);
 },[update]);

 useEffect(()=>{
  let retired=false,busy=false,baseline=null,controller=null,pendingObjective=null;
  const restore=prefs.open.at(-1),restoredPanels=prefs.open;
  const api=async path=>{
   const response=await fetch('/api/'+path,{cache:'no-store',signal:AbortSignal.any([controller.signal,AbortSignal.timeout(25000)])});
   if(!response.ok){const error=new Error('Agent record feed unavailable');error.status=response.status;error.path=path;throw error;}return response.json();
  };
  const observe=async(task,{restoring=false,live=false,cutoff=0}={})=>{
   const [snapshot,monitor]=await Promise.all([api('tasks/'+encodeURIComponent(task.id)+'/events'),
    selectedObjective.current===task.id?api('monitor').catch(()=>null):null]);
   if(retired||snapshot.task_id!==task.id||!Array.isArray(snapshot.events))return;
   if(selectedObjective.current&&selectedObjective.current!==task.id)return;
   if(activeCase.current!==task.id){
    activeCase.current=task.id;
    setWindows(previous=>Object.fromEntries(Object.entries(previous).filter(([,e])=>e.source!=='task'||e.taskId===task.id)));
   }
   const scope=new Set([task.id,...(snapshot.graph?.nodes||[]).filter(n=>n.kind==='task').map(n=>n.native_id)]);
   snapshot.approvals=(monitor?.approvals||(nativeData.current?.task_id===task.id?nativeData.current.approvals:[])||[])
    .filter(a=>(a.issue_ids||[]).some(id=>scope.has(id)));
   nativeData.current=snapshot;
   window.dispatchEvent(new CustomEvent('jarvis-project-snapshot',{detail:snapshot}));
   const fresh=snapshot.events.filter(e=>!seen.current.has(e.id)&&(!cutoff||Date.parse(e.occurred_at||'')>=cutoff));
   snapshot.events.forEach(e=>seen.current.add(e.id));
   const objective=selectedObjective.current===task.id;
   if(objective){
    const reply=channelMessages(snapshot).filter(e=>e.data.update_kind!=='plan').at(-1);
    if(shouldPublishReply(modeRef.current,reply?.source_ref?.comment_id,publishedReplies.current)){
     publishedReplies.current.add(reply.source_ref.comment_id);
     window.dispatchEvent(new CustomEvent('jarvis-ceo-reply',{detail:{task_id:task.id,identifier:snapshot.task.identifier,
      comment_id:reply.source_ref.comment_id,text:reply.data.text,provenance:'agent_summary'}}));
    }
    if(visibleSource(modeRef.current,'task')){
     window.JarvisTaskVisualState={identifier:snapshot.task.identifier,status:snapshot.task.status,
      active:!!snapshot.task.executionRunId||(snapshot.graph?.nodes||[]).some(n=>n.kind==='run'&&n.status==='running')};
     window.dispatchEvent(new CustomEvent('jarvis-task-visual-state',{detail:window.JarvisTaskVisualState}));
    }
   }
   const approvals=(snapshot.approvals||[]).filter(a=>['pending','revision_requested'].includes(a.status));
   const approvalKey='approval:'+task.id+':'+approvals.map(a=>a.id).sort().join(',');
   const panels=approvals.length?['agent']:[];
   if(!approvals.length)setWindows(previous=>Object.fromEntries(Object.entries(previous).filter(([,e])=>e.taskId!==task.id)));
   for(const panel of [...new Set(panels)].slice(0,3)){
    const current=windowsRef.current['task:'+panel];
    update(panel,{key:approvalKey,approvalOnly:true,source:'task',taskId:task.id,data:snapshot,status:'approval required'},
     {highlight:!restoring&&(fresh.length>0||current?.status!==snapshot.task.status),focus:!current});
   }
   // Already open windows update from canonical snapshots without opening a
   // new window for every status/comment or replaying historical discoveries.
   setWindows(previous=>{
    const next=Object.fromEntries(Object.entries(previous).map(([panel,e])=>[panel,
     e.source==='task'&&e.taskId===task.id?{...e,data:snapshot,status:snapshot.task.status,stale:false}:e]));
    persist(next);return next;
   });
  };
  const tick=async()=>{
   if(retired||busy||document.hidden)return;busy=true;controller=new AbortController();
   try{
    const list=await api('tasks');if(retired)return;
    const tasks=Array.isArray(list.tasks)?list.tasks:[],byId=new Map(tasks.map(t=>[t.id,t]));
    const selected=byId.get(selectedObjective.current)||pendingObjective,pendingId=pendingObjective?.id;
    if(selectedObjective.current&&!selected)selectedObjective.current=null;
    for(const key of closed.current){const parts=key.split(':');if(parts[0]==='case'&&!byId.has(parts[1])&&parts[1]!==pendingObjective?.id)closed.current.delete(key);}
    setWindows(previous=>{const next=Object.fromEntries(Object.entries(previous).filter(([,e])=>e.source!=='task'||byId.has(e.taskId)||e.taskId===pendingId));persist(next);return next;});
    if(modeRef.current!=='operations'&&!selected){
     baseline=new Map(tasks.map(t=>[t.id,baselineRecord(t)]));return;
    }
    if(!baseline){
     baseline=new Map(tasks.map(t=>[t.id,baselineRecord(t)]));
     const saved=restore&&byId.get(restore.taskId);
     const running=tasks.find(t=>t.status==='in_progress'&&t.executionRunId);
     if(selected){await observe(selected,{restoring:true});pendingObjective=null;}
     else if(saved)await observe(saved,{restoring:true});
     else if(running)await observe(running,{live:true,cutoff:Date.now()});
     return;
    }
    const changed=tasks.filter(t=>{
     const prior=baseline.get(t.id);
     if(!prior)return true;
     if(prior.fingerprint===fingerprint(t))return false;
     // A comment on an old inactive case is not fresh agent activity. Keep
     // genuine state transitions, live work and active execution changes.
     return prior.status!==t.status||t.status==='in_progress'||prior.status==='in_progress'||
      !!t.executionRunId||!!prior.executionRunId;
    }).sort((a,b)=>(b.updatedAt||'').localeCompare(a.updatedAt||''));
    const target=selected||changed[0]||tasks.find(t=>t.id===activeCase.current&&t.status==='in_progress'&&t.executionRunId);
    if(target){
     const prior=baseline.get(target.id),cutoff=prior?Date.parse(prior.updatedAt||'')||Date.now():Date.parse(target.createdAt||'')||Date.now();
     await observe(target,{cutoff});
     if(pendingObjective?.id===target.id)pendingObjective=null;
    }
    baseline=new Map(tasks.map(t=>[t.id,baselineRecord(t)]));
   }catch(error){
    if(!retired&&error.status===404&&selectedObjective.current&&error.path==='tasks/'+encodeURIComponent(selectedObjective.current)+'/events'){
     const missing=selectedObjective.current;selectedObjective.current=null;pendingObjective=null;
     setWindows(previous=>{const next=Object.fromEntries(Object.entries(previous).filter(([,e])=>e.taskId!==missing));persist(next);return next;});
    }else if(!retired)setWindows(previous=>Object.fromEntries(Object.entries(previous).map(([id,e])=>[id,
     e.source==='task'?{...e,status:'connection interrupted',stale:true}:e])));
   }finally{busy=false;}
  };
  const submitted=event=>{
   const task=event.detail?.task;if(!task||typeof task.id!=='string')return;
   const commentId=event.detail?.comment_id;
   if(event.detail?.followup&&typeof commentId==='string'&&!seen.current.has('ceo-message:'+commentId)){
    seen.current.add('ceo-message:'+commentId);closed.current.delete(nativeKey(task.id,'agent'));
   }
   // Selecting a goal is an explicit request to reopen its agent view, even
   // if the operator dismissed that same view during an earlier visit.
   closed.current.delete(nativeKey(task.id,'agent'));
   for(const key of closed.current)if(key.startsWith('approval:'+task.id+':'))closed.current.delete(key);
   selectedObjective.current=task.id;pendingObjective=task;
   setWindows(previous=>Object.fromEntries(Object.entries(previous).filter(([,e])=>e.source!=='task'||e.taskId===task.id)));
   const prior=windowsRef.current['task:agent'];
   update('agent',{key:nativeKey(task.id,'agent'),source:'task',taskId:task.id,status:task.status||'recorded',
    followupPending:!!event.detail?.followup,data:prior?.taskId===task.id?{...prior.data,task}:{task,agents:[],events:[],graph:{nodes:[],edges:[]}}});
   tick();
  };
  const context=event=>{
   if(event.detail?.task_id!==null)return;
   selectedObjective.current=null;pendingObjective=null;activeCase.current=null;
   setWindows(previous=>{const next=Object.fromEntries(Object.entries(previous).filter(([,e])=>e.source!=='task'));persist(next);return next;});
   window.JarvisTaskVisualState=null;window.dispatchEvent(new CustomEvent('jarvis-task-visual-state',{detail:null}));
  };
  const changedMode=()=>{
   const next=currentMode();modeRef.current=next;setMode(next);
   if(!visibleSource(next,'task')){
    window.JarvisTaskVisualState=null;
    window.dispatchEvent(new CustomEvent('jarvis-task-visual-state',{detail:null}));
   }else tick();
  };
  tick();const timer=setInterval(tick,3000);document.addEventListener('visibilitychange',tick);
  window.addEventListener('jarvis-objective-submitted',submitted);
  window.addEventListener('jarvis-ceo-context',context);
  window.addEventListener('jarvis-mode-changed',changedMode);
  return()=>{retired=true;clearInterval(timer);controller?.abort();document.removeEventListener('visibilitychange',tick);
   window.removeEventListener('jarvis-objective-submitted',submitted);window.removeEventListener('jarvis-ceo-context',context);
   window.removeEventListener('jarvis-mode-changed',changedMode);};
 },[persist,prefs,update]);

 const entries=visibleWindows(windows,mode,selectedObjective.current);
 useLayoutEffect(()=>{
  if(!host.current)return;
  const measure=()=>{const r=host.current.getBoundingClientRect();setStage(p=>p.width===r.width&&p.height===r.height?p:{width:r.width,height:r.height});};
  measure();const observer=new ResizeObserver(measure);observer.observe(host.current);return()=>observer.disconnect();
 },[entries.length>0]);
 useEffect(()=>{
  const timer=setInterval(()=>setWindows(previous=>{
   if(!Object.values(previous).some(e=>e.updated&&Date.now()-e.updated>2100))return previous;
   return Object.fromEntries(Object.entries(previous).map(([id,e])=>[id,{...e,updated:e.updated&&Date.now()-e.updated<=2100?e.updated:null}]));
  }),1000);return()=>clearInterval(timer);
 },[]);
 const body=entry=>{
  if(entry.source==='chat')return <ChatActivity entry={entry}/>;
  const data=entry.data,events=data.events||[];
  if(entry.panel==='agent')return <ApprovalRequests entry={entry}/>;
  if(entry.panel==='identity')return <Identity data={data} onChannel={()=>{}}/>;
  if(entry.panel==='files')return <Files data={data} onMetadata={()=>{}}/>;
  if(entry.panel==='warning')return <Warnings events={events}/>;
  if(entry.panel==='log')return <OperationLog events={events} taskId={entry.taskId}/>;
  if(entry.panel==='graph')return <Links graph={data.graph}/>;
  if(entry.panel==='network')return <Network events={events}/>;
  if(entry.panel==='decryption')return <Decryption events={events}/>;
  if(entry.panel==='metadata')return <Metadata data={data} selected={null} onSelect={()=>{}}/>;
  return <CaseTimeline events={events} taskId={entry.taskId}/>;
 };
 if(!entries.length)return null;
 const display=compact?entries.slice(-1):entries;
 return <MotionConfig reducedMotion="user"><section className="csi-workspace csi-automatic" data-csi-auto aria-label="Approval requests">
  <div className="csi-stage csi-auto-stage" ref={host}>
   <AnimatePresence>{display.map(entry=><CSIWindow key={entry.key} id={entry.panel} {...PANELS[entry.panel]} title="Approval required"
    status={entry.status} rect={clampRect(entry.rect,stage)} compact={compact}
    focused={focused===popupKey(entry)} zIndex={focused===popupKey(entry)?100:10+entries.indexOf(entry)} updated={!!entry.updated}
    onFocus={()=>setFocused(popupKey(entry))} onClose={()=>dismiss(popupKey(entry))} onMinimize={()=>dismiss(popupKey(entry))}
    onRectChange={rect=>{prefs.rects[entry.panel]=rect;setWindows(previous=>{const id=popupKey(entry),next={...previous,[id]:{...previous[id],rect}};persist(next);return next;});}}>
    {entry.stale&&<p className="csi-muted">Live updates interrupted. Last recorded snapshot shown.</p>}
    {body(entry)}
   </CSIWindow>)}</AnimatePresence>
  </div>
 </section></MotionConfig>;
}
