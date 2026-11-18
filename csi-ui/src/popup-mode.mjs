// Presentation lanes only. Native task state is owned by Paperclip.
export function popupMode(value, minimal=true,projectView='context',generalView='chat'){
 return minimal?(value==='general'?(generalView==='run'?'projects':generalView==='chat'?'administrator':generalView==='cron'?'cron':'project-list'):
  value==='cron'?'cron':value==='projects'?(projectView==='admin'?'administrator':projectView==='cron'?'cron':projectView==='list'?'project-list':'projects'):'direct'):'operations';
}

export function visibleSource(mode,source){
 if(mode==='project-list'||mode==='administrator'||mode==='cron')return false;
 return mode==='operations'||source===(mode==='projects'?'task':'chat');
}

export const popupKey=entry=>`${entry.source}:${entry.panel}`;
export const approvalPopupAllowed=entry=>entry?.approvalOnly===true&&
 Array.isArray(entry.data?.approvals)&&entry.data.approvals.some(a=>['pending','revision_requested'].includes(a.status));

export function shouldPublishReply(mode,commentId,published){
 return visibleSource(mode,'task')&&typeof commentId==='string'&&!published.has(commentId);
}

export function visibleWindows(windows,mode,selectedObjective){
 return Object.values(windows).filter(entry=>visibleSource(mode,entry.source)&&
  (mode!=='projects'||entry.source!=='task'||entry.taskId===selectedObjective)).sort((a,b)=>a.at-b.at);
}

export function boundedWindows(windows,limit,priority,mode){
 const ordered=Object.values(windows).sort((a,b)=>(priority[b.panel]||0)-(priority[a.panel]||0)||b.at-a.at);
 if(mode==='operations')return Object.fromEntries(ordered.slice(0,limit).map(entry=>[popupKey(entry),entry]));
 // Each mode retains its own windows. Background project updates must not
 // replace or evict a direct-chat tool/error panel using the same panel type.
 const counts={};
 return Object.fromEntries(ordered.filter(entry=>{
  counts[entry.source]=(counts[entry.source]||0)+1;
  return counts[entry.source]<=limit;
 }).map(entry=>[popupKey(entry),entry]));
}
