import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../../server/hud/tasks.js',import.meta.url),'utf8');
const ceo='11111111-1111-1111-1111-111111111111',taskId='22222222-2222-2222-2222-222222222222';
function harness(saved={}){
 const storage=new Map(Object.entries(saved)),nodes=new Map(),calls=[],events=[];
 let task={id:taskId,identifier:'JAR-TEST',title:'Objective',status:'todo',assigneeAgentId:ceo},messageFailure=null;
 const node=id=>{
  if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',options:[],hidden:false,replaceChildren(){this.options=[];},
   append(child){this.options.push(child);},setAttribute(){}});
  return nodes.get(id);
 };
 const context=vm.createContext({document:{getElementById:node,body:{classList:{contains:()=>true}},createElement:()=>({setAttribute(){}})},
  localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,String(value)),removeItem:key=>storage.delete(key)},
  crypto:{randomUUID:(()=>{let n=0;return()=>`00000000-0000-0000-0000-${String(++n).padStart(12,'0')}`;})()},
  AbortSignal,CustomEvent:class{constructor(type,init={}){this.type=type;this.detail=init.detail;}},Event:class{constructor(type){this.type=type;}},
  setInterval(){},queueMicrotask,console,
  fetch:async(url,options={})=>{
   const path=url.replace('/api/',''),body=options.body?JSON.parse(options.body):null;
   calls.push({path,method:options.method||'GET',body});
   if(path.endsWith('/messages')&&messageFailure){const failure=messageFailure;messageFailure=null;throw failure;}
   let data;
   if(path==='agents')data={ceo_id:ceo,agents:[{id:ceo,name:'JARVIS',role:'ceo',lifecycleState:'ready'}]};
   else if(path==='tasks'&&options.method==='POST')data=task;
   else if(path==='tasks')data={tasks:[task]};
   else if(path===`tasks/${taskId}`)data={...task,comments:[],runs:[],children:[]};
   else if(path.endsWith('/messages'))data={task,comment_id:'native-comment'};
   else if(path.startsWith('approvals/'))data={id:path.split('/')[1],status:body.decision==='approve'?'approved':'rejected'};
   else if(path==='monitor')data={};
   else throw new Error('Unexpected test path '+path);
   return {ok:true,status:200,json:async()=>data};
  }});
 context.window=context;context.addEventListener=()=>{};context.dispatchEvent=event=>events.push(event);
 context.JarvisMonitor={clear(){},dashboard(){},async show(){}};
 vm.runInContext(source,context);
 return {api:context.JarvisTasks,calls,events,storage,node,failNextMessage:error=>{messageFailure=error;}};
}
test('CEO follow-ups append to one native objective instead of creating new tasks',async()=>{
 const h=harness();
 await h.api.submitObjective('Inspect models');
 await h.api.followup('Include sizes');
 const writes=h.calls.filter(c=>c.method==='POST');
 assert.equal(writes.length,2);assert.equal(writes[0].path,'tasks');
 assert.equal(writes[1].path,`tasks/${taskId}/messages`);
 assert.equal(writes[1].body.input,'Include sizes');
 assert.equal(h.api.snapshot().objectiveId,taskId);
 assert(h.events.some(e=>e.type==='jarvis-objective-submitted'&&e.detail.followup===true&&e.detail.comment_id==='native-comment'));
});
test('uncertain follow-up retries reuse its nonce and cannot become a fresh objective',async()=>{
 const h=harness({'jarvis-ceo-objective':taskId});
 h.failNextMessage(new Error('connection lost after submission'));
 await h.api.followup('Include sizes');
 const pending=JSON.parse(h.storage.get('jarvis-task-pending'));
 await h.api.submitObjective('A different objective');
 assert.equal(h.calls.filter(c=>c.method==='POST'&&c.path==='tasks').length,0);
 await h.api.followup('Include sizes');
 const messages=h.calls.filter(c=>c.path.endsWith('/messages'));
 assert.equal(messages.length,2);assert.equal(messages[1].body.request_id,pending.request_id);
 assert(!h.storage.has('jarvis-task-pending'));
});
test('a restored explicit CEO reference is used directly; resetting only changes view context',async()=>{
 const h=harness({'jarvis-ceo-objective':taskId});
 await h.api.followup('Continue the report');
 assert.equal(h.calls[0].path,`tasks/${taskId}/messages`);
 const before=h.calls.length;h.api.newObjective();
 assert.equal(h.calls.length,before);assert.equal(h.api.snapshot().objectiveId,null);
 assert(!h.storage.has('jarvis-ceo-objective'));
});
test('typed human decisions use the existing native authenticated approval endpoint',async()=>{
 const h=harness();const id='33333333-3333-3333-3333-333333333333';
 const result=await h.api.decide(id,'reject','Do not hire for this objective');
 assert.equal(result.status,'rejected');assert.equal(h.calls[0].path,`approvals/${id}/decision`);
 assert.equal(h.calls[0].body.note,'Do not hire for this objective');
 assert.equal(h.calls.filter(c=>c.path==='tasks').length,0);
});
