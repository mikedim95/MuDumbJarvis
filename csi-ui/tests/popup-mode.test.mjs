import test from 'node:test';
import assert from 'node:assert/strict';
import {popupMode,visibleSource,popupKey,boundedWindows,shouldPublishReply,visibleWindows,approvalPopupAllowed} from '../src/popup-mode.mjs';

test('General chat, General schedules and mission schedules preserve their own presentation scope',()=>{
 assert.equal(popupMode('general',true,'list','chat'),'administrator');
 assert.equal(popupMode('general',true,'list','cron'),'cron');
 assert.equal(popupMode('general',true,'list','context'),'project-list');
 assert.equal(popupMode('general',true,'context','run'),'projects');
 assert.equal(popupMode('projects',true,'cron'),'cron');
});

test('direct chat defaults independently of saved project presentation',()=>{
 assert.equal(popupMode(undefined),'direct');
 assert.equal(popupMode('projects'),'projects');
 assert.equal(visibleSource('direct','task'),false);
 assert.equal(visibleSource('direct','chat'),true);
 assert.equal(visibleSource('projects','chat'),false);
 assert.equal(visibleSource('projects','task'),true);
 assert.equal(popupMode('projects',false),'operations');
 assert.equal(visibleSource('operations','chat'),true);
 assert.equal(visibleSource('operations','task'),true);
});

test('the project list has no conversation or task windows and cannot publish old replies',()=>{
 const mode=popupMode('projects',true,'list'),published=new Set();
 assert.equal(mode,'project-list');
 assert.equal(visibleSource(mode,'chat'),false);
 assert.equal(visibleSource(mode,'task'),false);
 assert.equal(shouldPublishReply(mode,'previous-result',published),false);
 assert.deepEqual(visibleWindows({task:{source:'task',taskId:'old',at:1},chat:{source:'chat',at:2}},mode,'old'),[]);
 assert.equal(published.size,0);
 assert.equal(popupMode('projects',true,'context'),'projects');
});

test('background project updates cannot replace a chat tool or error window',()=>{
 const chat={source:'chat',panel:'log',at:1,key:'chat-tool'};
 const task={source:'task',panel:'log',at:2,key:'project-update'};
 const state=boundedWindows({[popupKey(chat)]:chat,[popupKey(task)]:task},1,{log:5},'direct');
 assert.equal(state['chat:log'],chat);
 assert.equal(state['task:log'],task);
 const direct=Object.values(state).filter(entry=>visibleSource('direct',entry.source));
 const projects=Object.values(state).filter(entry=>visibleSource('projects',entry.source));
 assert.deepEqual(direct,[chat]);assert.deepEqual(projects,[task]);
});

test('Administrator has its own chat and never publishes a project or Direct Chat popup',()=>{
 const mode=popupMode('projects',true,'admin');
 assert.equal(mode,'administrator');
 assert.equal(visibleSource(mode,'chat'),false);
 assert.equal(visibleSource(mode,'task'),false);
 assert.equal(shouldPublishReply(mode,'old-project-comment',new Set()),false);
 assert.deepEqual(visibleWindows({task:{source:'task',taskId:'old',at:1},chat:{source:'chat',at:2}},mode,'old'),[]);
});

test('each mode preserves its most important windows within the viewport limit',()=>{
 const entries=[
  {source:'chat',panel:'log',at:1},{source:'chat',panel:'warning',at:2},
  {source:'task',panel:'agent',at:3},{source:'task',panel:'warning',at:4},
 ];
 const state=Object.fromEntries(entries.map(e=>[popupKey(e),e]));
 const bounded=boundedWindows(state,1,{log:5,agent:8.5,warning:9},'projects');
 assert.deepEqual(Object.keys(bounded).sort(),['chat:warning','task:warning']);
 // The explicit operator layout retains its existing shared popup limit.
 assert.equal(Object.keys(boundedWindows(state,1,{log:5,agent:8.5,warning:9},'operations')).length,1);
});

test('a reply observed during direct chat remains unpublished until Projects is opened',()=>{
 const emitted=new Set();
 assert.equal(shouldPublishReply('direct','native-comment',emitted),false);
 assert.equal(emitted.size,0);
 assert.equal(shouldPublishReply('projects','native-comment',emitted),true);
 emitted.add('native-comment');
 assert.equal(shouldPublishReply('projects','native-comment',emitted),false);
 assert.equal(shouldPublishReply('direct','new-comment',emitted),false);
 assert.equal(shouldPublishReply('projects','new-comment',emitted),true);
});

test('opening Projects only restores the selected objective, not unrelated saved tasks',()=>{
 const own={source:'task',panel:'agent',taskId:'selected',at:1};
 const other={source:'task',panel:'files',taskId:'older-unrelated',at:2};
 const chat={source:'chat',panel:'log',at:3};
 const state={own,other,chat};
 assert.deepEqual(visibleWindows(state,'projects','selected'),[own]);
 assert.deepEqual(visibleWindows(state,'projects',null),[]);
 assert.deepEqual(visibleWindows(state,'direct','selected'),[chat]);
 assert.deepEqual(visibleWindows(state,'operations','selected'),[own,other,chat]);
});

test('only pending approval requests may open automatic panels',()=>{
 for(const status of ['in_progress','done','blocked','error','tool started']){
  assert.equal(approvalPopupAllowed({source:'task',status,data:{approvals:[]}}),false);
  assert.equal(approvalPopupAllowed({source:'chat',status,data:{}}),false);
 }
 assert.equal(approvalPopupAllowed({approvalOnly:true,data:{approvals:[{status:'pending'}]}}),true);
 assert.equal(approvalPopupAllowed({approvalOnly:true,data:{approvals:[{status:'revision_requested'}]}}),true);
 for(const status of ['approved','rejected','cancelled'])assert.equal(approvalPopupAllowed({approvalOnly:true,data:{approvals:[{status}]}}),false);
 assert.equal(popupMode('cron'),'cron');assert.equal(visibleSource('cron','task'),false);
});
