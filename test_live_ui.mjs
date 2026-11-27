import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import assert from 'node:assert/strict';
import {test} from 'node:test';
const src=readFileSync('web/app.js','utf8');
const code=src.slice(src.indexOf('function liveAchieved('),src.indexOf('function rememberLive('));
const c={live:{cache:new Map()}};
runInNewContext(code,c);
const report={valid:true,skills:[{id:'normal:a',status:'active',threshold:20,points:24},{id:'normal:b',status:'overflow',threshold:30,points:35}],automatic:[{id:'normal:c',effective:true,threshold:10}],zenith:[{id:'zenith:x',level:2,raw_points:2,has_base_skill:false},{id:'zenith:y',level:1,raw_points:1,has_base_skill:true}],slots:{},defense_stats:{}};
test('Only active normal/automatic and effective Zenith count as witnesses',()=>{
 assert.equal(c.liveAchieved(report,'normal:a',10),true);assert.equal(c.liveAchieved(report,'normal:a',30),false);assert.equal(c.liveAchieved(report,'normal:b',10),false);assert.equal(c.liveAchieved(report,'normal:c',10),true);assert.equal(c.liveAchieved(report,'zenith:x',1),false);assert.equal(c.liveAchieved(report,'zenith:y',1),true);
});
test('Cache scope is invalidated by non-required conditions, not required additions',()=>{
 const base={required:[],optional:[],forbidden:[],limit:5,seconds:20,weapon_type:'MS'};
 assert.equal(c.liveSpec(base).base,c.liveSpec({...base,required:[{skill:'normal:a',points:10}]}).base);
 assert.notEqual(c.liveSpec(base).base,c.liveSpec({...base,weapon_type:'SnS'}).base);
 assert.notEqual(c.liveSpec(base).base,c.liveSpec({...base,forbidden:[{skill:'normal:b',points:10}]}).base);
});
test('Cached verified builds stay available when fresh search finds none; dedup and cap',()=>{
 const req={required:[{skill:'normal:a',points:10}],optional:[],forbidden:[],limit:2,seconds:20};const spec=c.liveSpec(req);
 const hit={evaluation:report,build:{armor:{head:{item:'h',level:'1',jewels:['a','b']}}},metrics:{}};
 c.live.cache.set(spec.base,[hit,{...hit,build:{armor:{head:{item:'h',level:'1',jewels:['b','a']}}}},{...hit,evaluation:{...report,valid:false}}]);
 const results=c.liveSample(spec,[]);assert.equal(results.length,1);assert.equal(results[0].metrics.required_surplus,14);
});
