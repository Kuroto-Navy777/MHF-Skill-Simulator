import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import assert from 'node:assert/strict';
import {test} from 'node:test';
const src=readFileSync('web/app.js','utf8');
const html=readFileSync('web/index.html','utf8');
const state={fields:{},checks:{},required:[],optional:[],forbidden:[],armor:{},weapon:null,cuffs:[],excluded:[],classes:[]};
function fixture(responses){
  const storage=new Map(),controls=new Map(),messages=[],results=[];
  const $=id=>{if(!controls.has(id))controls.set(id,{hidden:false,disabled:false,scrollIntoView(){},onchange(){}});return controls.get(id)};
  const c={sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},$: $,validProfileState:x=>!!x?.fields,api:async()=>{const v=responses.shift();if(v instanceof Error)throw v;return v},t:k=>k,message:v=>messages.push(v),document:{querySelectorAll:()=>[]},comparisonKeys:new Set(),resetResultFilters(){},renderResults:()=>results.push(c.result),restoreProfile(){},generation:0,currentJob:null,result:null,setTimeout:f=>f()};
  runInNewContext(src.slice(src.indexOf("const LAST_SEARCH="),src.indexOf('function itemName(')),c);return {c,storage,controls,messages,results};
}
const id='a'.repeat(32);
test('running job survives session refresh and clears on completion',async()=>{const f=fixture([{status:'running',elapsed_seconds:1},{status:'done',result:{results:[]}}]);f.c.setActiveRecord({id,state});assert.equal(f.c.activeRecord().id,id);await f.c.resumeSearch();assert.equal(f.c.activeRecord(),null);assert.equal(f.results.length,1);assert.equal(f.c.currentJob,null)});
test('temporary disconnection retains job, expired job clears it',async()=>{const f=fixture([Error('offline'),Object.assign(Error('missing'),{status:404})]);f.c.setActiveRecord({id,state});await f.c.resumeSearch();assert.equal(f.c.activeRecord().id,id);await f.c.resumeSearch();assert.equal(f.c.activeRecord(),null);assert.equal(f.messages.at(-1),'jobExpired')});
test('cancel clears active job and advances generation',async()=>{const f=fixture([{status:'cancelled'}]);f.c.setActiveRecord({id,state});f.c.currentJob=id;await f.c.cancel();assert.equal(f.c.activeRecord(),null);assert.equal(f.c.generation,1)});
test('RC2 controls exist and assets are cache versioned',()=>{for(const id of ['restoreLast','resumeJob'])assert.ok(html.includes(`id="${id}"`));assert.ok(html.includes('app.js?v=11a'));assert.ok(html.includes('style.css?v=11a'))});
// The request ID is saved before POST; a lost response must leave a recoverable record.
test('search submission persists its ID before POST and retains it after lost response',async()=>{
  const f=fixture([]);
  Object.assign(f.c,{crypto:{getRandomValues:a=>a.fill(10)},makeBuild:()=>({seconds:10}),tab:'search',snapshot:()=>state,Uint8Array});
  let submitted;
  f.c.api=async (url,method,body)=>{submitted=body;assert.equal(f.c.activeRecord().id,body._job_id);throw Error('offline')};
  await f.c.run();
  assert.equal(f.c.activeRecord().id,submitted._job_id);
  assert.equal(f.messages.at(-1),'offline');
});
test('confirmed submission rejection clears the pending record',async()=>{
  const f=fixture([]);
  Object.assign(f.c,{crypto:{getRandomValues:a=>a.fill(10)},makeBuild:()=>({seconds:10}),tab:'search',snapshot:()=>state,Uint8Array});
  f.c.api=async()=>{throw Object.assign(Error('conflict'),{status:409})};
  await f.c.run();assert.equal(f.c.activeRecord(),null);
});
