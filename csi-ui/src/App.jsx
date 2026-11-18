import React,{useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react';
import {AnimatePresence,MotionConfig} from 'motion/react';
import CSIWindow from './CSIWindow.jsx';
import {PANELS,clampRect,defaultRect,readPreferences,panelFor} from './state.mjs';
import {Identity,Files,Warnings,OperationLog,Links,CaseTimeline,Network,Metadata,Decryption,AgentChannel,Empty} from './panels.jsx';
import AutoPopups from './AutoPopups.jsx';

const store={get:key=>{try{return localStorage.getItem(key);}catch{return null;}},set:(key,value)=>{try{localStorage.setItem(key,value);}catch{}}};
const defaultBridge=()=>window.JarvisTasks?.snapshot()||{tasks:[],agents:[],selected:null,submitting:false};
function useBridge(){
 const [data,setData]=useState(defaultBridge);
 useEffect(()=>{const update=e=>setData(e.detail||defaultBridge());window.addEventListener('jarvis-tasks-updated',update);update({});
  return()=>window.removeEventListener('jarvis-tasks-updated',update);},[]);
 return data;
}
function useFeed(taskId,refreshToken){
 const [state,setState]=useState({data:null,error:'',lastSync:null});
 useEffect(()=>{
  let retired=false,timer=null,controller=null,busy=false;
  setState({data:null,error:'',lastSync:null});
  const tick=async()=>{
   if(retired||busy||!taskId||document.hidden)return;
   busy=true;controller=new AbortController();
   try{
    const r=await fetch('/api/tasks/'+encodeURIComponent(taskId)+'/events',{
     signal:AbortSignal.any([controller.signal,AbortSignal.timeout(25000)]),cache:'no-store'});
    if(!r.ok)throw new Error(r.status===401?'Authentication required. Unlock the HUD.':r.status===404?'This task is no longer available.':'Event feed unavailable (HTTP '+r.status+').');
    const next=await r.json();if(next.task_id!==taskId||!Array.isArray(next.events))throw new Error('Invalid task event response.');
    if(!retired)setState(previous=>({data:previous.data?.snapshot_id===next.snapshot_id?previous.data:next,error:'',lastSync:Date.now()}));
   }catch(e){if(!retired&&e.name!=='AbortError')setState(previous=>({...previous,error:e.message}));}
   finally{busy=false;}
  };
  tick();timer=setInterval(tick,3000);document.addEventListener('visibilitychange',tick);
  return()=>{retired=true;clearInterval(timer);controller?.abort();document.removeEventListener('visibilitychange',tick);};
 },[taskId,refreshToken]);
 return state;
}
function initialWindows(stage){
 return Object.fromEntries(['identity','log','graph'].map(id=>[id,{rect:defaultRect(id,stage),closed:false,minimized:false}]));
}
function Workspace({onClose}){
 const bridge=useBridge(),stageRef=useRef(null),liveCase=useRef(null),seen=useRef(new Set()),firstSnapshot=useRef(true),channelFor=useRef(null);
 const [caseId,setCaseId]=useState(()=>store.get('jarvis-csi-case')||bridge.selected||'');
 const [stage,setStage]=useState({width:window.innerWidth,height:Math.max(300,window.innerHeight-210)});
 const [windows,setWindows]=useState({}),[focused,setFocused]=useState('graph'),[order,setOrder]=useState(['identity','graph','log']);
 const [updated,setUpdated]=useState({}),[ready,setReady]=useState(false),[refreshToken,setRefreshToken]=useState(0);
 const [selectedArtifact,setSelectedArtifact]=useState(null),[objective,setObjective]=useState(''),[dispatchError,setDispatchError]=useState(''),[busy,setBusy]=useState(false);
 const {data:feedData,error,lastSync}=useFeed(caseId,refreshToken),compact=stage.width<850;
 const data=feedData?.task_id===caseId?feedData:null;
 const key=caseId?'jarvis-csi-layout-v1:'+caseId:null;
 useLayoutEffect(()=>{
  const observer=new ResizeObserver(()=>{const r=stageRef.current?.getBoundingClientRect();if(r)setStage({width:r.width,height:r.height});});
  observer.observe(stageRef.current);return()=>observer.disconnect();
 },[]);
 useEffect(()=>{
  if(!bridge.tasks.length)return;
  if(!bridge.tasks.some(t=>t.id===caseId))setCaseId(bridge.selected||bridge.tasks[0].id);
 },[bridge.tasks,bridge.selected,caseId]);
 useEffect(()=>{
  if(!caseId)return;setReady(false);liveCase.current=caseId;firstSnapshot.current=true;
  const prefs=readPreferences(localStorage,'jarvis-csi-layout-v1:'+caseId);
  const next=prefs?.windows||initialWindows(stage),channel=channelFor.current===caseId;
  if(channel)next.agent={rect:defaultRect('agent',stage),closed:false,minimized:false};
  setWindows(next);setFocused(channel?'agent':prefs?.focused||'graph');
  if(channel){setOrder(previous=>[...previous.filter(id=>id!=='agent'),'agent']);channelFor.current=null;}
  seen.current=new Set(prefs?.seen||[]);setUpdated({});setSelectedArtifact(null);setReady(true);
  store.set('jarvis-csi-case',caseId);
 },[caseId]);
 useEffect(()=>{
  if(!ready||!key||liveCase.current!==caseId)return;
  store.set(key,JSON.stringify({version:1,windows,focused,seen:[...seen.current].slice(-600)}));
 },[windows,focused,ready,key,caseId]);
 useEffect(()=>{
  if(!data||data.task_id!==caseId||!ready)return;
  const fresh=data.events.filter(e=>!seen.current.has(e.id)),now=Date.now();
  data.events.forEach(e=>seen.current.add(e.id));
  if(fresh.length){
   const panels=[...new Set(fresh.map(e=>panelFor(e.type)))],backfill=firstSnapshot.current;
   setWindows(previous=>{
    const next={...previous};
    for(const id of panels){
     if(next[id])continue; // An explicitly closed/minimized window stays so.
     next[id]={rect:defaultRect(id,stage),closed:false,minimized:backfill&&['metadata','network','decryption'].includes(id)};
    }
    return next;
   });
   setUpdated(Object.fromEntries(panels.map(id=>[id,now])));
  }
  firstSnapshot.current=false;
  // Cursors are view preferences, not a cache of task or finding content.
  try{const p=readPreferences(localStorage,key);if(p)store.set(key,JSON.stringify({...p,seen:[...seen.current].slice(-600)}));}catch{}
 },[data,caseId,ready]);
 useEffect(()=>{if(!Object.keys(updated).length)return;const timer=setTimeout(()=>setUpdated({}),2100);return()=>clearTimeout(timer);},[updated]);
 useEffect(()=>{setWindows(previous=>Object.fromEntries(Object.entries(previous).map(([id,w])=>[id,{...w,rect:clampRect(w.rect,stage)}])));},[stage]);
 const focus=useCallback(id=>{setFocused(id);setOrder(previous=>[...previous.filter(i=>i!==id),id]);},[]);
 const openPanel=id=>{setWindows(previous=>({...previous,[id]:{rect:previous[id]?.rect||defaultRect(id,stage),closed:false,minimized:false}}));focus(id);};
 const selectCase=async id=>{
  setCaseId(id);setDispatchError('');
  try{await window.JarvisTasks?.select(id);}catch(e){setDispatchError(e.message);}
 };
 const submit=async e=>{
  e.preventDefault();const text=objective.trim();if(!text||busy||bridge.submitting)return;
  setBusy(true);setDispatchError('');setObjective('');
  try{
   const task=await window.JarvisTasks?.submitObjective(text);
   if(!task)throw new Error(window.JarvisTasks?.snapshot().error||'Objective submission was not confirmed. Retry the same text.');
   channelFor.current=task.id;setCaseId(task.id);
  }catch(e){setDispatchError(e.message);setObjective(current=>current||objective);}finally{setBusy(false);}
 };
 const events=data?.events||[],warningCount=events.filter(e=>['analysis.warning','task.failed'].includes(e.type)).length;
 const current=bridge.tasks.find(t=>t.id===caseId),caseStatus=data?.task.status||current?.status||'connecting';
 const renderPanel=id=>{
  if(!data)return <Empty>{error?'The backend event feed is unavailable. No findings are being generated.':'Loading authenticated Paperclip records…'}</Empty>;
  const props={data,events};
  if(id==='identity')return <Identity {...props} onChannel={()=>openPanel('agent')}/>;
  if(id==='files')return <Files {...props} onMetadata={id=>{setSelectedArtifact(id);openPanel('metadata');}}/>;
  if(id==='warning')return <Warnings {...props}/>;
  if(id==='log')return <OperationLog {...props} taskId={caseId}/>;
  if(id==='graph')return <Links graph={data.graph}/>;
  if(id==='timeline')return <CaseTimeline {...props} taskId={caseId}/>;
  if(id==='network')return <Network {...props}/>;
  if(id==='metadata')return <Metadata {...props} selected={selectedArtifact} onSelect={setSelectedArtifact}/>;
  if(id==='decryption')return <Decryption {...props}/>;
  return <AgentChannel {...props}/>;
 };
 const visible=Object.entries(windows).filter(([id,w])=>!w.closed&&!w.minimized&&(!compact||id===focused));
 return <MotionConfig reducedMotion="user"><section id="csiWorkspace" className="csi-workspace" aria-label="Live CSI investigation workspace">
  <div className="csi-topbar">
   <div className="csi-brand"><strong>JARVIS <span style={{color:'#55dfbc'}}>/</span> CSI</strong><span>LIVE OPERATIONS<br/>PAPERCLIP EVIDENCE LINK</span></div>
   <div className="csi-toolbar"><label htmlFor="csiCaseSelect" className="csi-label">CASE</label>
    <select id="csiCaseSelect" value={caseId} onChange={e=>selectCase(e.target.value)} aria-label="Select Paperclip case">
     {!bridge.tasks.length&&<option value="">Loading task history…</option>}
     {bridge.tasks.map(t=><option value={t.id} key={t.id}>{t.identifier} · {t.status} · {t.title.slice(0,48)}</option>)}
    </select>
    <button type="button" className="cy-modal__btn" onClick={()=>setRefreshToken(v=>v+1)}>↻ SYNC</button>
    <button id="csiExit" type="button" className="cy-modal__btn" onClick={onClose}>BACK TO HUD ×</button>
   </div>
  </div>
  <div className="csi-footer" style={{justifyContent:'space-between'}}>
   <span><span className="csi-badge">{data?.task.identifier||current?.identifier||'NO CASE'}</span> {caseStatus.replaceAll('_',' ')} · {data?.graph.nodes.length||0} recorded objects · {data?.artifacts.length||0} files</span>
   <span id="csiConnection" role={error?'alert':'status'} className={error?'csi-error':'csi-muted'}>
    {error||(lastSync?'Paperclip connected · synced '+new Date(lastSync).toLocaleTimeString():'Connecting to Paperclip…')}{error&&data?' Last verified snapshot shown; live updates paused.':''}
   </span>
  </div>
  <div ref={stageRef} className="csi-stage" id="csiStage">
   <AnimatePresence>{ready&&visible.map(([id,w])=><CSIWindow key={caseId+':'+id} id={id} {...PANELS[id]}
    rect={w.rect} focused={id===focused} updated={!!updated[id]} compact={compact} zIndex={id===focused?100:10+Math.max(0,order.indexOf(id))}
    status={id==='warning'?(warningCount?warningCount+' recorded warnings':'no warnings'):error?'connection interrupted':caseStatus}
    onFocus={()=>focus(id)} onRectChange={rect=>setWindows(previous=>({...previous,[id]:{...previous[id],rect}}))}
    onClose={()=>setWindows(previous=>({...previous,[id]:{...previous[id],closed:true}}))}
    onMinimize={()=>setWindows(previous=>({...previous,[id]:{...previous[id],minimized:true}}))}>
    {renderPanel(id)}
   </CSIWindow>)}</AnimatePresence>
   {!visible.length&&<Empty>{compact?'Choose a panel from the dock below.':'All panels are minimized. Restore a panel from the dock.'}</Empty>}
  </div>
  <nav className="csi-dock" aria-label="CSI window controls">{Object.entries(PANELS).map(([id,p])=><button key={id} data-csi-open={id} type="button"
    className={'cy-modal__btn'+(id===focused?' is-active':'')} aria-pressed={id===focused} onClick={()=>openPanel(id)}>
    <span aria-hidden="true">{p.icon}</span> {p.title}{id==='warning'&&warningCount>0?' ('+warningCount+')':''}{updated[id]?' •':''}
   </button>)}</nav>
  <form className="csi-composer" onSubmit={submit}>
   <label className="csi-label" htmlFor="csiObjectiveInput">◉ CEO UPLINK</label>
   <input id="csiObjectiveInput" className="csi-input" value={objective} onChange={e=>setObjective(e.target.value)} maxLength={8000}
    placeholder="Give the CEO one objective…" autoComplete="off"/>
   <button id="csiObjectiveSend" className="cy-modal__btn csi-primary" type="submit" disabled={busy||bridge.submitting||!objective.trim()}>{busy?'DISPATCHING…':'DISPATCH OBJECTIVE ↗'}</button>
   {dispatchError&&<p role="alert" className="csi-error">{dispatchError}</p>}
  </form>
  <div className="csi-footer"><span>Paperclip is authoritative · public plans / tool evidence / saved results</span><span>{data?.limits.truncated?'Display limit reached; full history remains in Paperclip.':'3 s polling · '+(compact?'compact panel view':'drag / resize / minimize')} · no synthetic findings</span></div>
 </section></MotionConfig>;
}
function OperationsApp(){
 const [open,setOpen]=useState(()=>store.get('jarvis-csi-open')==='true');
 useEffect(()=>{
  const launch=()=>setOpen(true),button=document.getElementById('csiLaunch');
  button?.addEventListener('click',launch);window.JarvisCSI={open:launch,close:()=>setOpen(false)};
  return()=>{button?.removeEventListener('click',launch);delete window.JarvisCSI;};
 },[]);
 useEffect(()=>{store.set('jarvis-csi-open',String(open));},[open]);
 return open?<Workspace onClose={()=>{setOpen(false);document.getElementById('csiLaunch')?.focus();}}/>:null;
}
export default function App(){
 return document.body.classList.contains('ai-minimal')?<AutoPopups/>:<OperationsApp/>;
}
