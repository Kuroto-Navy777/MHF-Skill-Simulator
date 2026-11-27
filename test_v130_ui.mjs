import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import assert from 'node:assert/strict';
import {test} from 'node:test';
const src=readFileSync('web/app.js','utf8');
const start=src.indexOf('function liveSpec('),end=src.indexOf('function liveFilter(',start);
test('Probe transport and retry ID do not invalidate an unchanged UI request',()=>{
 const c={};runInNewContext(src.slice(start,end)+';globalThis.spec=liveSpec',c);
 const req={weapon_type:'MS',search_mode:'automatic',required:[{skill:'n:a',points:10}],optional:[],forbidden:[],seconds:10,limit:5};
 const plain=c.spec(req),probe=c.spec({...req,probe:{seconds:10,offset:24,candidate_limit:24},_job_id:'retry'});
 assert.equal(plain.key,probe.key);assert.equal(plain.base,probe.base);assert.equal(plain.poolScope,probe.poolScope);
 assert.notEqual(plain.key,c.spec({...req,required:[{skill:'n:b',points:10}]}).key);
 assert.notEqual(plain.poolScope,c.spec({...req,weapon:{sigils:3}}).poolScope);
});
test('Scope selection preserves explicit ownership and clears only selected fixed items',()=>{
 const fn=src.slice(src.indexOf('function probeRequest('),src.indexOf('function clearAllFixes('));
 const controls={probeScope:{value:'all'},probeBatch:{value:'24'},sigils:{value:'0'}};
 const c={$:id=>controls[id],structuredClone,liveSpec:()=>({key:'key'}),probePlanKey:null,probeNextOffset:0,cuffs:[],result:{results:[{build:{armor:Object.fromEntries(['head','body','arm','waist','leg'].map(p=>[p,{item:p,jewels:['j']} ])),cuffs:['c']}}]}};
 runInNewContext(fn,c);
 const original={required:[],armor:{head:{item:'head'}},cuffs:['locked'],seconds:10,inventory:{j:2}};
 const a=c.probeRequest(original);assert.equal(a.search_mode,'automatic');assert.deepEqual(a.inventory,{j:2});assert.equal(a.cuffs,undefined);assert.equal(Object.keys(a.armor).length,0);
 controls.probeScope.value='armor_cuffs';const b=c.probeRequest(original);assert.equal(Object.keys(b.armor).length,5);assert.deepEqual(b.cuffs,['locked']);assert.ok(Object.values(b.armor).every(a=>a.jewels.length===0));
 controls.probeScope.value='armor';assert.equal(c.probeRequest(original).cuffs,undefined);
 assert.deepEqual(original.cuffs,['locked']);
});
