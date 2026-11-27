import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import assert from 'node:assert/strict';
import {test} from 'node:test';
const src=readFileSync('web/app.js','utf8'), html=readFileSync('web/index.html','utf8');
const c={};
runInNewContext(src.slice(src.indexOf('function sortResultHits('),src.indexOf('function renderResults(')),c);
const select=html.match(/<select id="sort">(.*?)<\/select>/s)[1];
const keys=[...select.matchAll(/value="([^"]+)"/g)].map(x=>x[1]);
const asc=['rank','required_surplus','new_jewels'];
test('All display sort modes compare their actual metrics in the correct direction',()=>{
 for(const key of keys){
  const a={rank:1,metrics:{[key]:1}},b={rank:2,metrics:{[key]:2}},hits=[b,a];
  const result=c.sortResultHits(hits,key);
  assert.equal(result[0],asc.includes(key)?a:b,key);assert.deepEqual(hits,[b,a]);
 }
 assert.ok(src.includes("$('sort').onchange=renderResults"));
});
test('Equal metrics use search rank and stable source order; missing values sort last',()=>{
 const a={rank:1,metrics:{defense:12}},b={rank:2,metrics:{defense:12}},missing={rank:0,metrics:{defense:null}};
 assert.deepEqual([...c.sortResultHits([b,missing,a],'defense')],[a,b,missing]);
 assert.deepEqual([...c.sortResultHits([a,b],'new_jewels')],[a,b]);
});
const live={live:{cache:new Map()}};
runInNewContext(src.slice(src.indexOf('function liveAchieved('),src.indexOf('function rememberLive(')),live);
test('Live cache accepts reached overlap, but rejects overflow and insufficient own tier',()=>{
 const r={valid:true,skills:[{id:'normal:1',status:'overlap',threshold:20}]};
 assert.equal(live.liveAchieved(r,'normal:1',20),true);
 assert.equal(live.liveAchieved(r,'normal:1',30),false);
 r.skills[0].status='overflow';assert.equal(live.liveAchieved(r,'normal:1',20),false);
});
test('Required addition schedules a new solver request even with an empty cached sample',()=>{
 const schedule=src.slice(src.indexOf('function scheduleLive('),src.indexOf('async function pumpLive('));
 assert.ok(schedule.includes('live.pending={spec,epoch};pumpLive()'));
 const a=live.liveSpec({required:[],optional:[],forbidden:[],limit:5});
 const b=live.liveSpec({required:[{skill:'normal:1',points:30}],optional:[],forbidden:[],limit:5});
 assert.notEqual(a.key,b.key);assert.equal(a.base,b.base);
 assert.equal(live.liveSample(b,[]).length,0);
});
