import React,{useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react';
import {AnimatePresence,MotionConfig} from 'motion/react';
import CSIWindow from './CSIWindow.jsx';
import {PANELS,clampRect,safeTerminal} from './state.mjs';
import {Identity,Files,Warnings,OperationLog,Links,CaseTimeline,Network,Metadata,Decryption} from './panels.jsx';
import './auto-popups.css';

const STORAGE='jarvis-agent-popups-v1';
const PRIORITY={warning:9,files:8,decryption:7,network:6,log:5,identity:4,graph:3,metadata:2,timeline:1};
const nativeKey=(taskId,panel)=>`case:${taskId}:${panel}`;
const fingerprint=task=>[task.updatedAt,task.status,task.executionRunId].join('|');
const baselineRecord=task=>({fingerprint:fingerprint(task),updatedAt:task.updatedAt,
 status:task.status,executionRunId:task.executionRunId});
const bounded=values=>values.slice(-600);
function preferences(){
 try{
  const saved=JSON.parse(localStorage.getItem(STORAGE)||'null');
  if(saved?.version!==1)return {rects:{},closed:[],seen:[],open:[]};
  return {rects:saved.rects&&typeof saved.rects==='object'?saved.rects:{},
   closed:Array.isArray(saved.closed)?saved.closed.filter(v=>typeof v==='string').slice(-80):[],
   seen:Array.isArray(saved.seen)?saved.seen.filter(v=>typeof v==='string').slice(-600):[],
   open:Array.isArray(saved.open)?saved.open.filter(v=>v&&typeof v.taskId==='string'&&PANELS[v.panel]).slice(-3):[]};
 }catch{return {rects:{},closed:[],seen:[],open:[]};}
}
function defaultRect(panel,stage){
 const width=Math.min(350,stage.width-20),height=Math.min(panel==='files'?310:280,stage.height-20);
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

/** Automatic presentation only. No task mutation, inference request or finding cache. */
export default function AutoPopups(){
 const initial=useRef(preferences()),prefs=initial.current;
 const seen=useRef(new Set(prefs.seen)),closed=useRef(new Set(prefs.closed)),windowsRef=useRef({}),activeCase=useRef(null);
 const [windows,setWindows]=useState({}),[focused,setFocused]=useState(null);
 const [stage,setStage]=useState({width:window.innerWidth,height:Math.max(180,window.innerHeight-190)});
 const stageRef=useRef(stage),host=useRef(null),nativeData=useRef(null);
 stageRef.current=stage;windowsRef.current=windows;
 const compact=stage.width<680;
 const persist=useCallback(next=>{
  try{localStorage.setItem(STORAGE,JSON.stringify({version:1,rects:prefs.rects,
   closed:[...closed.current].slice(-80),seen:bounded([...seen.current]),
   open:Object.values(next).filter(e=>e.source==='task').slice(-3).map(e=>({taskId:e.taskId,panel:e.panel}))}));}catch{}
 },[prefs]);
 const update=useCallback((panel,entry,{highlight=true}={})=>{
  if(closed.current.has(entry.key))return;
  const now=Date.now();
  setWindows(previous=>{
   const next={...previous,[panel]:{...entry,panel,at:now,updated:highlight?now:previous[panel]?.updated,
    rect:previous[panel]?.key===entry.key?previous[panel].rect:clampRect(prefs.rects[panel]||defaultRect(panel,stageRef.current),stageRef.current)}};
   const limit=stageRef.current.width<680?1:3;
   const keep=Object.values(next).sort((a,b)=>PRIORITY[b.panel]-PRIORITY[a.panel]||b.at-a.at).slice(0,limit);
   const boundedNext=Object.fromEntries(keep.map(e=>[e.panel,e]));
   persist(boundedNext);return boundedNext;
  });
  setFocused(panel);
 },[persist,prefs]);
 const dismiss=useCallback(panel=>{
  setWindows(previous=>{const entry=previous[panel];if(entry)closed.current.add(entry.key);
   const next={...previous};delete next[panel];persist(next);return next;});
 },[persist]);

 useEffect(()=>{
  const listener=event=>{
   const e=event.detail;
   if(!e||!['tool','reply','error'].includes(e.kind)||typeof e.request_id!=='string')return;
   const name=typeof e.tool?.name==='string'?e.tool.name:'tool';
   const eventId=`chat:${e.request_id}:${e.kind}:${name}:${e.run_id||''}:${e.reference||''}`;
   if(seen.current.has(eventId))return;seen.current.add(eventId);
   if(e.kind==='reply'){
    const previous=windowsRef.current.log;
    if(previous?.source!=='chat'||previous.requestId!==e.request_id)return;
    update('log',{...previous,status:'reply complete',activity:[...previous.activity,
     {id:eventId,kind:'reply',runtime:e.runtime}].slice(-16)});
   }else if(e.kind==='tool'){
    const key=`chat:${e.request_id}:log`,previous=windowsRef.current.log;
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
  let retired=false,busy=false,baseline=null,controller=null;
  const restore=prefs.open.at(-1),restoredPanels=prefs.open;
  const api=async path=>{
   const response=await fetch('/api/'+path,{cache:'no-store',signal:AbortSignal.any([controller.signal,AbortSignal.timeout(25000)])});
   if(!response.ok)throw new Error('Agent record feed unavailable');return response.json();
  };
  const observe=async(task,{restoring=false,live=false,cutoff=0}={})=>{
   const snapshot=await api('tasks/'+encodeURIComponent(task.id)+'/events');
   if(retired||snapshot.task_id!==task.id||!Array.isArray(snapshot.events))return;
   if(activeCase.current!==task.id){
    activeCase.current=task.id;
    setWindows(previous=>Object.fromEntries(Object.entries(previous).filter(([,e])=>e.source!=='task'||e.taskId===task.id)));
   }
   nativeData.current=snapshot;
   const fresh=snapshot.events.filter(e=>!seen.current.has(e.id)&&(!cutoff||Date.parse(e.occurred_at||'')>=cutoff));
   snapshot.events.forEach(e=>seen.current.add(e.id));
   const panels=restoring?restoredPanels.filter(p=>p.taskId===task.id).map(p=>p.panel):nativePanels(fresh);
   if(live){panels.push('log');if(snapshot.agents?.length)panels.push('identity');}
   for(const panel of [...new Set(panels)].slice(0,3)){
    update(panel,{key:nativeKey(task.id,panel),source:'task',taskId:task.id,data:snapshot,status:snapshot.task.status});
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
    setWindows(previous=>Object.fromEntries(Object.entries(previous).filter(([,e])=>e.source!=='task'||byId.has(e.taskId))));
    if(!baseline){
     baseline=new Map(tasks.map(t=>[t.id,baselineRecord(t)]));
     const saved=restore&&byId.get(restore.taskId);
     const running=tasks.find(t=>t.status==='in_progress'&&t.executionRunId);
     if(saved)await observe(saved,{restoring:true});
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
    const target=changed[0]||tasks.find(t=>t.id===activeCase.current&&t.status==='in_progress'&&t.executionRunId);
    if(target){
     const prior=baseline.get(target.id),cutoff=prior?Date.parse(prior.updatedAt||'')||Date.now():Date.parse(target.createdAt||'')||Date.now();
     await observe(target,{cutoff});
    }
    baseline=new Map(tasks.map(t=>[t.id,baselineRecord(t)]));
   }catch{
    if(!retired)setWindows(previous=>Object.fromEntries(Object.entries(previous).map(([id,e])=>[id,
     e.source==='task'?{...e,status:'connection interrupted',stale:true}:e])));
   }finally{busy=false;}
  };
  tick();const timer=setInterval(tick,3000);document.addEventListener('visibilitychange',tick);
  return()=>{retired=true;clearInterval(timer);controller?.abort();document.removeEventListener('visibilitychange',tick);};
 },[persist,prefs,update]);

 const entries=Object.values(windows).sort((a,b)=>a.at-b.at);
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
 return <MotionConfig reducedMotion="user"><section className="csi-workspace csi-automatic" data-csi-auto aria-label="Agent activity popups">
  <div className="csi-stage csi-auto-stage" ref={host}>
   <AnimatePresence>{display.map(entry=><CSIWindow key={entry.key} id={entry.panel} {...PANELS[entry.panel]}
    status={entry.status} rect={clampRect(entry.rect,stage)} compact={compact}
    focused={focused===entry.panel} zIndex={focused===entry.panel?100:10+entries.indexOf(entry)} updated={!!entry.updated}
    onFocus={()=>setFocused(entry.panel)} onClose={()=>dismiss(entry.panel)} onMinimize={()=>dismiss(entry.panel)}
    onRectChange={rect=>{prefs.rects[entry.panel]=rect;setWindows(previous=>{const next={...previous,[entry.panel]:{...previous[entry.panel],rect}};persist(next);return next;});}}>
    {entry.stale&&<p className="csi-muted">Live updates interrupted. Last recorded snapshot shown.</p>}
    {body(entry)}
   </CSIWindow>)}</AnimatePresence>
  </div>
 </section></MotionConfig>;
}
