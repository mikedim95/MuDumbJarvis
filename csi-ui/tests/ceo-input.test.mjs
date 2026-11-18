import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const context=vm.createContext({});
vm.runInContext(readFileSync(new URL('../../server/hud/ceo-input.js',import.meta.url),'utf8'),context);
const route=(text,task)=>JSON.parse(JSON.stringify(context.JarvisCEOInput.route(text,task,"projects")));
test('conversation keeps the published prose while native proof appendices remain in evidence',()=>{
 assert.equal(context.JarvisCEOInput.publishedText('Actual report\n\nVerified delegated execution data:\n```json\n{"proof":"signed"}'),'Actual report');
 assert.equal(context.JarvisCEOInput.publishedText('Actual inventory\n\nVerified local_ollama_models data:\n[]'),'Actual inventory');
 assert.equal(context.JarvisCEOInput.publishedText('The report includes verified evidence.'),'The report includes verified evidence.');
});

test('opening a saved run restores its latest assignee reply rather than internal records or another agent',()=>{
 const comment=(id,authorAgentId,body,time)=>({id,authorAgentId,body,createdAt:'2026-11-18T10:00:'+time+'Z'});
 const reply=comment('result','ceo','The research batch is complete.','20');
 const task={assigneeAgentId:'ceo',comments:[
  comment('operator',null,'User follow-up','30'),
  comment('worker','worker','Worker result','31'),
  comment('review','ceo','[JARVIS CEO REVIEW]\nRuntime verification.','32'),
  comment('ready','ceo','[JARVIS CEO RESULTS READY]\nResults supplied for review.','33'),
  comment('tool','ceo','[JARVIS TOOL EVENT]\nRuntime evidence.','34'),
  reply,comment('older','ceo','The batch is running.','10')]};
 assert.equal(context.JarvisCEOInput.latestReply(task).id,reply.id);
 assert.equal(context.JarvisCEOInput.latestReply({assigneeAgentId:'ceo',comments:[]}),undefined);
});

test('ordinary input stays on its explicit CEO objective across follow-ups',()=>{
 assert.deepEqual(route('Build a report'),{kind:'new',input:'Build a report'});
 assert.deepEqual(route('Include limitations','native-objective'),{kind:'followup',input:'Include limitations',task_id:'native-objective'});
});
test('only explicit /chat leaves the CEO objective without changing its reference',()=>{
 assert.deepEqual(route('/chat Explain this term','native-objective'),{kind:'direct',input:'Explain this term'});
 assert.equal(route('/chatty is a project name','native-objective').kind,'followup');
 assert.equal(route('/chat').kind,'invalid');
});
test('new-objective commands never silently append to an older objective',()=>{
 assert.deepEqual(route('/new A different objective','old'),{kind:'new',input:'A different objective'});
 assert.deepEqual(route('@CEO A different objective','old'),{kind:'new',input:'A different objective'});
 assert.deepEqual(route('/new','old'),{kind:'reset'});
 assert.equal(route('@ceo','old').kind,'invalid');
});
test('approval decisions require an explicit native approval UUID',()=>{
 const id='12345678-1234-1234-1234-123456789abc';
 assert.deepEqual(route('/approve '+id+' Reviewed limited research scope','task'),{kind:'decision',decision:'approve',approval_id:id,note:'Reviewed limited research scope'});
 assert.equal(route('/reject '+id).decision,'reject');
 assert.equal(route('/approve all','task').kind,'invalid');
 assert.equal(route('approve it','task').kind,'followup');
});

// A saved project must never turn an ordinary direct conversation into work.
test('Direct Chat never submits projects or approval mutations, including slash commands',()=>{
 for(const text of ['Hello','What is JAR-56 doing?','/new Build something','@ceo Build something','/approve 12345678-1234-1234-1234-123456789abc']){
  const result=JSON.parse(JSON.stringify(context.JarvisCEOInput.route(text,'saved-project','direct')));
  assert.deepEqual(result,{kind:'direct',input:text});
 }
 assert.equal(context.JarvisCEOInput.route('Hello').kind,'direct');
});
