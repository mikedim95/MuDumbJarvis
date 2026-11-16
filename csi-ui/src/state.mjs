// View preferences only. Paperclip events/tasks are never persisted here.
export const PANELS = {
 identity:{title:'Identity Analysis',icon:'◈'},files:{title:'Recovered Files',icon:'▧'},
 warning:{title:'Analysis Warning',icon:'△'},log:{title:'Operation Log',icon:'⌁'},
 graph:{title:'Links Detected',icon:'⌘'},timeline:{title:'Case Timeline',icon:'◷'},
 network:{title:'Network Trace',icon:'⌖'},metadata:{title:'Evidence Metadata',icon:'▤'},
 decryption:{title:'Decryption',icon:'◇'},agent:{title:'Agent Channel',icon:'◉'}
};
export function panelFor(type){
 if(type.startsWith('identity.'))return 'identity';
 if(type==='evidence.file_recovered')return 'files';
 if(type.startsWith('evidence.'))return 'metadata';
 if(type==='analysis.warning'||type==='task.failed')return 'warning';
 if(type==='timeline.updated')return 'timeline';
 if(type.startsWith('graph.'))return 'graph';
 if(type.startsWith('network.'))return 'network';
 if(type.startsWith('decryption.'))return 'decryption';
 return 'log';
}
export function clampRect(rect,stage){
 const sw=Math.max(240,stage.width||1200),sh=Math.max(160,stage.height||700);
 const finite=(n,f)=>Number.isFinite(Number(n))?Number(n):f;
 const width=Math.max(Math.min(280,sw),Math.min(sw,finite(rect?.width,360)));
 const height=Math.max(Math.min(180,sh),Math.min(sh,finite(rect?.height,280)));
 return {width,height,x:Math.max(0,Math.min(sw-width,finite(rect?.x,12))),y:Math.max(0,Math.min(sh-height,finite(rect?.y,12)))};
}
export function defaultRect(id,stage){
 const w=stage.width||1400,h=stage.height||720;
 const left=Math.min(330,w*.25),right=Math.min(405,w*.3),center=Math.max(340,w-left-right-48);
 const top=Math.max(230,Math.min(375,h*.54));
 const positions={
 identity:{x:12,y:12,width:left,height:top},files:{x:12,y:top+28,width:left,height:h-top-40},
 graph:{x:left+28,y:12,width:center,height:top+60},
 log:{x:w-right-12,y:12,width:right,height:top+30},
 timeline:{x:left+28,y:top+88,width:center,height:h-top-100},
 warning:{x:w-right-12,y:top+60,width:right,height:h-top-72},
 metadata:{x:w*.30,y:85,width:490,height:380},network:{x:w*.36,y:100,width:480,height:350},
 decryption:{x:w*.25,y:115,width:440,height:330},agent:{x:w*.28,y:30,width:Math.min(650,w-24),height:h-60}
 };
 return clampRect(positions[id],stage);
}
export function readPreferences(storage,key){
 try{
  const raw=JSON.parse(storage.getItem(key)||'null');
  if(!raw||raw.version!==1)return null;
  const windows={};
  for(const [id,item] of Object.entries(raw.windows||{})){
   if(!PANELS[id]||!item||typeof item!=='object')continue;
   windows[id]={rect:clampRect(item.rect,{width:10000,height:10000}),closed:!!item.closed,minimized:!!item.minimized};
  }
  return {version:1,windows,seen:Array.isArray(raw.seen)?raw.seen.filter(v=>typeof v==='string').slice(-600):[],
   focused:PANELS[raw.focused]?raw.focused:'graph'};
 }catch{return null;}
}
export function safeTerminal(value){
 return String(value??'').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').replace(/\x1b\][^\x07]*(?:\x07|\x1b\\)/g,'')
  .replace(/\u009b[0-?]*[ -/]*[@-~]/g,'').replace(/\u009d[^\x07\u009c]*(?:\x07|\u009c|$)/g,'')
  .replace(/[\x00-\x08\x0b-\x1f\x7f\u0080-\u009f]/g,'');
}
export function channelMessages(data){
 return (data?.events||[]).filter(e=>e.provenance==='agent_summary'&&typeof e.data?.text==='string'&&
  e.task_id===data.task.id&&e.source_ref?.agent_id===data.task.assigneeAgentId);
}
export function eventText(event){
 const data=event.data||{};
 return [event.title,data.text,data.message,data.error,data.status].filter(v=>typeof v==='string').join('\n');
}
