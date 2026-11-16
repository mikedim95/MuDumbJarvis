import React,{useEffect,useMemo,useRef,useState} from 'react';
import {ReactFlow,Background,Controls,MarkerType} from '@xyflow/react';
import {Terminal} from '@xterm/xterm';
import {FitAddon} from '@xterm/addon-fit';
import {Timeline,DataSet} from 'vis-timeline/standalone';
import {eventText,safeTerminal,channelMessages} from './state.mjs';

export const provenance=value=>({native_record:'PAPERCLIP RECORD',verified_tool_output:'VERIFIED TOOL OUTPUT',agent_summary:'AGENT SUMMARY'}[value]||'REPORTED DATA');
export function Empty({children}){return <div className="csi-empty"><span aria-hidden="true">◇</span><p>{children}</p></div>;}
export function EventList({events,limit=16}){
 return <div className="csi-event-list">{events.slice(-limit).reverse().map(e=><article className="csi-event" key={e.id} data-event-id={e.id}>
  <div className="csi-event-time">{e.occurred_at?new Date(e.occurred_at).toLocaleString():'Timestamp unavailable'}</div>
  <strong>{e.title}</strong><span className="csi-provenance" data-provenance={e.provenance}>{provenance(e.provenance)}</span>
  <pre>{eventText(e)||JSON.stringify(e.data,null,2)}</pre>
  <small className="csi-muted">{e.source_ref?.run_id?'Run '+e.source_ref.run_id:'Task '+e.task_id}</small>
 </article>)}</div>;
}
export function Identity({data,onChannel}){
 const people=data?.agents||[],matches=(data?.events||[]).filter(e=>e.type==='identity.partial_match_found');
 return <><p className="csi-label">CURRENT REGISTERED EXECUTORS</p>{people.map(a=><article className="cy-profile csi-agent-card" key={a.id}>
  <div className="cy-profile__avatar"><span className="cy-profile__initials">{a.name?.split(/[- ]/).map(s=>s[0]).slice(0,2).join('')}</span>
   <span className={'cy-profile__status '+(['idle','running','active'].includes(a.status)&&a.lifecycleState==='ready'?'cy-profile__status--online':'cy-profile__status--away')}><span className="cy-sr-only">{a.status}</span></span></div>
  <div className="cy-profile__info"><h3 className="cy-profile__name">{a.name}</h3><p className="cy-profile__role">{a.role} · {a.status}</p></div>
  <dl className="cy-profile__stats"><div><dt>Provider</dt><dd>{a.provider||'unavailable'}</dd></div><div><dt>Model</dt><dd>{a.model||'unavailable'}</dd></div><div><dt>Runtime</dt><dd>Hermes</dd></div></dl>
  <small className="csi-muted">Employee ID: {a.id}</small>
 </article>)}{!people.length&&<Empty>No assigned executor identity is recorded.</Empty>}
 <button className="cy-modal__btn csi-action" type="button" onClick={onChannel}>◉ OPEN AGENT CHANNEL</button>
 {matches.length?<EventList events={matches}/>:<p className="csi-muted">No verified identity matches recorded. Employee identity comes from Paperclip.</p>}</>;
}
export function Files({data,onMetadata}){
 const items=data?.artifacts||[];
 return <><p className="csi-label">PAPERCLIP ARTIFACTS · {items.length} RECORDED</p>
 <p className="csi-muted">Uploaded execution deliverables.</p>
 {!items.length?<Empty>No files have been recorded for this case yet.</Empty>:items.map(a=><article className="csi-artifact" key={a.id}>
  <strong>{a.originalFilename}</strong><span className="csi-badge">{Number(a.byteSize||0).toLocaleString()} B</span>
  <small className="csi-muted">{a.contentType||'Content type unavailable'}</small>
  <div><a className="cy-modal__btn csi-action" href={'/api/tasks/'+a.issueId+'/artifacts/'+a.id} download>DOWNLOAD</a>
  <button className="cy-modal__btn csi-action" onClick={()=>onMetadata(a.id)}>METADATA</button></div>
 </article>)}</>;
}
export function Warnings({events}){
 const list=events.filter(e=>e.type==='analysis.warning'||e.type==='task.failed');
 return list.length?<EventList events={list}/>:<Empty>No execution warnings or failures are recorded for this case.</Empty>;
}
export function Metadata({data,selected,onSelect}){
 const list=data?.artifacts||[],item=list.find(a=>a.id===selected)||list[0];
 if(!item)return <Empty>No evidence metadata has been recorded yet.</Empty>;
 return <><label className="csi-label">EVIDENCE OBJECT<select value={item.id} onChange={e=>onSelect(e.target.value)}>{list.map(a=><option key={a.id} value={a.id}>{a.originalFilename}</option>)}</select></label>
 <dl className="csi-kv">{[['File',item.originalFilename],['Artifact ID',item.id],['Paperclip task',item.issueId],['Created by',item.createdByAgentId],['Originating run',item.originatingRunId],['Bytes',item.byteSize],['SHA-256',item.sha256],['Recorded',item.createdAt]].map(([k,v])=><React.Fragment key={k}><dt>{k}</dt><dd>{v??'Not recorded'}</dd></React.Fragment>)}</dl>
 <p className="csi-muted">Downloads are checked against the native byte count and SHA-256 by FastAPI.</p></>;
}
export function Links({graph}){
 const [selected,setSelected]=useState(null),flow=useRef(null);
 const {nodes,edges}=useMemo(()=>{
  const counters={},cols={agent:0,task:1,run:2,artifact:3};
  return {nodes:(graph?.nodes||[]).map(n=>{const row=counters[n.kind]||0;counters[n.kind]=row+1;
   return {id:n.id,position:{x:(cols[n.kind]??1)*250,y:row*125},data:{label:<><small>{n.kind.toUpperCase()}</small><strong>{n.label}</strong><span>{n.status||'recorded'}</span></>},
    style:{borderColor:n.kind==='agent'?'#5fddb5':n.kind==='artifact'?'#719be3':'#327889'},sourcePosition:'right',targetPosition:'left'};
  }),edges:(graph?.edges||[]).map(e=>({...e,type:'smoothstep',markerEnd:{type:MarkerType.ArrowClosed,color:'#2c7e94'},style:{stroke:'#2c7e94'},labelStyle:{fill:'#a0bdcb',fontSize:10}}))};
 },[graph]);
 const nodeIds=nodes.map(n=>n.id).join('|');
 useEffect(()=>{
  const frame=requestAnimationFrame(()=>flow.current?.fitView({padding:.25,duration:matchMedia('(prefers-reduced-motion: reduce)').matches?0:220}));
  return()=>cancelAnimationFrame(frame);
 },[nodeIds]);
 return <><div className="csi-graph nodrag"><ReactFlow nodes={nodes} edges={edges} fitView fitViewOptions={{padding:.25}}
  nodesDraggable={false} nodesConnectable={false} elementsSelectable={true} deleteKeyCode={null}
  onInit={instance=>{flow.current=instance;}} onNodeClick={(_,n)=>setSelected(n.id)} minZoom={.15} maxZoom={2} colorMode="dark" proOptions={{hideAttribution:false}}>
  <Background color="#163945" gap={22} size={1}/><Controls showInteractive={false}/></ReactFlow></div>
 <p className="csi-muted">{selected||'Native assignments, dependencies, executions and artifacts.'}</p></>;
}
export function OperationLog({events,taskId}){
 const host=useRef(null),instance=useRef(null),written=useRef(new Set());
 useEffect(()=>{
  const terminal=new Terminal({disableStdin:true,convertEol:true,cursorBlink:false,scrollback:1800,fontSize:11,
   fontFamily:'ui-monospace, monospace',theme:{background:'#04101a',foreground:'#a2d4df',cursor:'#4de8e8',selectionBackground:'#16526b'}});
  const fit=new FitAddon();terminal.loadAddon(fit);terminal.open(host.current);instance.current=terminal;written.current=new Set();
  terminal.writeln('PAPERCLIP EVENT STREAM · READ ONLY');
  const resize=()=>{try{if(host.current?.clientWidth>40&&host.current?.clientHeight>40)fit.fit();}catch{}};
  const observer=new ResizeObserver(resize);observer.observe(host.current);resize();
  return()=>{observer.disconnect();instance.current=null;terminal.dispose();};
 },[taskId]);
 useEffect(()=>{
  const terminal=instance.current;if(!terminal)return;
  for(const event of events){
   if(written.current.has(event.id))continue;written.current.add(event.id);
   const timestamp=event.occurred_at?new Date(event.occurred_at).toLocaleTimeString():'time unavailable';
   terminal.writeln(safeTerminal('['+timestamp+'] '+event.type+' · '+event.title));
   terminal.writeln(safeTerminal('  '+provenance(event.provenance)+' · '+event.task_id));
   const detail=eventText(event)||JSON.stringify(event.data);
   terminal.writeln(safeTerminal('  '+detail.slice(0,1300)).replaceAll('\n','\r\n  '));
  }
 },[events,taskId]);
 return <><div ref={host} className="csi-terminal nodrag" aria-label="Recorded operation log"/>
  <small className="csi-muted">Actual backend records. Terminal input and shell access are disabled.</small></>;
}
export function CaseTimeline({events,taskId}){
 const host=useRef(null),timeline=useRef(null),set=useRef(null),ids=useRef(new Set());
 useEffect(()=>{
  const items=new DataSet();set.current=items;ids.current=new Set();
  const view=new Timeline(host.current,items,{height:'100%',minHeight:170,stack:true,editable:false,
   orientation:'top',showCurrentTime:false,zoomKey:'ctrlKey',verticalScroll:true,selectable:false,
   tooltip:{followMouse:false},margin:{item:8,axis:10},format:{minorLabels:{second:'HH:mm:ss',minute:'HH:mm',hour:'HH:mm'}}});
  timeline.current=view;let frame;
  const resize=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{
   if(host.current){host.current.style.height=Math.max(150,host.current.parentElement.clientHeight-36)+'px';view.redraw();}
  });};
  const observer=new ResizeObserver(resize);observer.observe(host.current.parentElement);resize();
  return()=>{observer.disconnect();cancelAnimationFrame(frame);view.destroy();timeline.current=null;};
 },[taskId]);
 useEffect(()=>{
  if(!set.current||!timeline.current)return;
  const initial=ids.current.size===0,valid=events.filter(e=>e.occurred_at&&Number.isFinite(Date.parse(e.occurred_at))).slice(-100);
  const items=valid.map(e=>{const label=document.createElement('span');label.textContent=e.title;
   return {id:e.id,content:label,start:new Date(e.occurred_at),type:'point',className:e.type==='analysis.warning'||e.type==='task.failed'?'csi-time-warning':''};});
  const next=new Set(items.map(i=>i.id));set.current.remove([...ids.current].filter(id=>!next.has(id)));
  set.current.update(items);ids.current=next;
  if(initial&&items.length)timeline.current.fit({animation:false});
 },[events,taskId]);
 return <><div ref={host} className="csi-timeline nodrag"/><small className="csi-muted">Recorded timestamps · Ctrl + scroll to zoom</small></>;
}
export function Network({events}){
 const traces=events.filter(e=>e.type==='network.trace'),hosts=[...new Set(traces.map(e=>e.data?.host).filter(v=>typeof v==='string'))].slice(0,7);
 if(!traces.length)return <Empty>No verified network trace or source retrieval is recorded for this case.</Empty>;
 return <><svg className="csi-network" viewBox="0 0 540 260" role="img" aria-label="Recorded source relationships">
  <circle cx="80" cy="130" r="25" fill="#0b2939" stroke="#4de8e8"/><text x="80" y="174" textAnchor="middle" fill="#b5e8f0" fontSize="11">TASK EXECUTION</text>
  {hosts.map((host,i)=>{const y=28+i*32;return <g key={host}><path d={'M105 130 C230 130 230 '+y+' 355 '+y} fill="none" stroke="#2b7e94"/>
   <circle cx="360" cy={y} r="5" fill="#65c9d0"/><text x="375" y={y+4} fill="#b5e8f0" fontSize="10">{host.slice(0,24)}</text></g>;})}</svg>
 <p className="csi-muted">Source relationships only. No packet route, geographic location or IP ownership is inferred.</p><EventList events={traces} limit={8}/></>;
}
export function Decryption({events}){
 const findings=events.filter(e=>e.type==='decryption.progress');
 return findings.length?<EventList events={findings}/>:<Empty>No verified decryption activity is recorded. This panel waits for actual tool evidence.</Empty>;
}
function useLocalSpeech(text){
 const [voices,setVoices]=useState([]),[speaking,setSpeaking]=useState(false),[error,setError]=useState('');
 useEffect(()=>{
  if(!('speechSynthesis' in window))return;
  const update=()=>setVoices(window.speechSynthesis.getVoices().filter(v=>v.localService===true));update();
  window.speechSynthesis.addEventListener('voiceschanged',update);
  return()=>{window.speechSynthesis.removeEventListener('voiceschanged',update);window.speechSynthesis.cancel();};
 },[]);
 useEffect(()=>()=>{if('speechSynthesis' in window)window.speechSynthesis.cancel();},[text]);
 const stop=()=>{window.speechSynthesis?.cancel();setSpeaking(false);};
 const read=()=>{
  if(!voices.length||!text)return;stop();setError('');
  const utterance=new SpeechSynthesisUtterance(text.slice(0,12000));
  utterance.voice=voices.find(v=>v.lang.startsWith('en'))||voices[0];utterance.lang=utterance.voice.lang;utterance.rate=.96;
  utterance.onstart=()=>setSpeaking(true);utterance.onend=()=>setSpeaking(false);
  utterance.onerror=e=>{setSpeaking(false);if(!['interrupted','canceled'].includes(e.error))setError('Local voice playback failed: '+e.error);};
  window.speechSynthesis.speak(utterance);
 };
 return {voices,speaking,error,read,stop};
}
export function AgentChannel({data}){
 const events=data?.events||[],assignee=data?.task.assigneeAgentId;
 const employee=data?.agents.find(a=>a.id===assignee);
 const messages=channelMessages(data);
 const latest=messages.at(-1),response=latest?.data.text||'',speech=useLocalSpeech(response);
 const plans=messages.filter(e=>e.data.update_kind==='plan');
 return <div className="csi-channel"><p className="csi-label">{employee?.name||'ASSIGNED AGENT'} · {data?.task.status||'WAITING'}</p>
 <p className="csi-muted">Published plans, activity and replies for the selected Paperclip objective.</p>
 {plans.length>0&&<details><summary>EXECUTION PLAN</summary><pre>{plans.at(-1).data.text}</pre></details>}
 <div className={'csi-response'+(speech.speaking?' is-speaking':'')} id="csiAgentResponse" role="status">
  <span className="csi-provenance">{response?(data?.task.status==='done'?'PUBLISHED AGENT RESPONSE':'PUBLISHED AGENT UPDATE'):'AWAITING RECORDED RESPONSE'}</span>
  <pre>{response||'The agent has not published a response for this objective yet.'}</pre>
 </div>
 <div className="csi-toolbar"><button className="cy-modal__btn" onClick={speech.read} disabled={!response||!speech.voices.length}>▷ READ REPLY</button>
 <button className="cy-modal__btn" onClick={speech.stop} disabled={!speech.speaking}>■ STOP VOICE</button></div>
 <p className="csi-muted">{speech.speaking?'Local voice speaking.':speech.voices.length?'Local device voice · click Read reply to speak.':'No local device voice is available here. Replies remain visible as text.'}</p>
 {speech.error&&<p className="csi-error" role="alert">{speech.error}</p>}
 </div>;
}
