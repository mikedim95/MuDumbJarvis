import test from 'node:test';
import assert from 'node:assert/strict';
import {clampRect,readPreferences,panelFor,safeTerminal,channelMessages} from '../src/state.mjs';
test('offscreen and poisoned geometry always fits the visible workspace',()=>{
 for(const rect of [{x:1e6,y:-42,width:2000,height:Infinity},{x:NaN,y:NaN,width:'bad',height:0},null]){
  const r=clampRect(rect,{width:393,height:500});
  assert(r.x>=0&&r.y>=0&&r.x+r.width<=393&&r.y+r.height<=500);
 }
});
test('storage restores only geometry/cursors, never task data or arbitrary panels',()=>{
 const data={version:1,task:{secret:'discard'},windows:{identity:{rect:{x:5,y:6,width:300,height:200},closed:true},attacker:{rect:{}}},seen:['event',1],focused:'attacker'};
 const p=readPreferences({getItem:()=>JSON.stringify(data)},'key');
 assert.deepEqual(Object.keys(p.windows),['identity']);assert(!p.task);assert.deepEqual(p.seen,['event']);assert.equal(p.focused,'graph');
 assert.equal(readPreferences({getItem:()=>'{broken'},'key'),null);
});
test('actual event types route to windows without making up findings',()=>{
 assert.equal(panelFor('task.failed'),'warning');assert.equal(panelFor('identity.partial_match_found'),'identity');
 assert.equal(panelFor('network.trace'),'network');assert.equal(panelFor('decryption.progress'),'decryption');
 assert.equal(panelFor('evidence.file_recovered'),'files');
});
test('operation log cannot execute terminal escape or clipboard controls',()=>{
 assert.equal(safeTerminal('\x1b[31merror\x1b[0m\x1b]52;c;secret\x07\x00\nnext'),'error\nnext');
 assert.equal(safeTerminal('\u009b31merror\u009b0m\u009d52;c;secret\u009c\nnext'),'error\nnext');
});
test('agent channel never speaks a worker or another case as the selected executor',()=>{
 const own={provenance:'agent_summary',task_id:'case',source_ref:{agent_id:'ceo'},data:{text:'CEO response'}};
 const data={task:{id:'case',assigneeAgentId:'ceo'},events:[own,{...own,task_id:'child'},
  {...own,source_ref:{agent_id:'worker'}},{...own,provenance:'verified_tool_output'}]};
 assert.deepEqual(channelMessages(data),[own]);
});
