import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {makeBackup,validateBackup} from './web/backup.mjs';
const src=readFileSync('web/app.js','utf8');
const parts=['head','body','arm','waist','leg'];
const c={parts};
runInNewContext(src.slice(src.indexOf('class CandidateIndex{'),src.indexOf('Object.assign(words,{virtualWeapon:'))+'\nglobalThis.Index=CandidateIndex;',c);
const makeHit=i=>({build:{armor:Object.fromEntries(parts.map(p=>[p,{item:p+Math.floor(i/3),level:'L1',jewels:p==='head'?['j'+i]:[]}]))},evaluation:{valid:true,skills:[{id:'normal:a',threshold:i%2?20:10,status:'active'}],automatic:[],zenith:[]}});

test('The full reservoir survives a five-result display and required deletion restores its range',()=>{
 const index=new c.Index();const hits=Array.from({length:180},(_,i)=>makeHit(i));index.ingest('scope',hits);
 assert.equal(index.query('scope').hits.length,180);
 assert.equal(index.count('scope',[],'normal:a',20),90);
 assert.equal(index.query('scope',[{skill:'normal:a',points:20}]).hits.slice(0,5).length,5);
 assert.equal(index.query('scope').hits.length,180);
 const groups=c.groupCandidates(index.query('scope').hits);
 assert.equal(groups.length,60);assert.ok(groups.every(h=>h.variant_count===3&&h.variants.length===2));
});
test('Overflow, wrong weapon and missing Zenith prerequisites never enter the activation index',()=>{
 const index=new c.Index();const a=makeHit(1),b=makeHit(2),d=makeHit(3);
 a.evaluation.skills[0].status='overflow';a.evaluation.attained={'normal:a':30};
 b.evaluation.skills[0].status='wrong_weapon';
 d.evaluation.zenith=[{id:'zenith:x',level:2,has_base_skill:false}];
 index.ingest('x',[a,b,d]);
 assert.equal(index.count('x',[],'normal:a',10),1);assert.equal(index.count('x',[],'zenith:x',1),0);
});
test('Equivalent jewel placements are deduplicated while a real cuff alternative survives',()=>{
 const index=new c.Index();const a=makeHit(1),b=structuredClone(a),d=structuredClone(a);
 b.build.armor.body.jewels=b.build.armor.head.jewels;b.build.armor.head.jewels=[];
 d.build.cuffs=['another-cuff'];index.ingest('x',[a,b,d]);
 assert.equal(index.query('x').hits.length,2);
});
test('Evicted ordinal bits are rebuilt within the configured capacity',()=>{
 const index=new c.Index(24,12);for(let i=0;i<6;i++)index.ingest('s'+i,Array.from({length:20},(_,j)=>makeHit(j)));
 assert.ok([...index.scopes.values()].reduce((n,s)=>n+s.hits.size,0)<=24);
 for(const scope of index.scopes.values())for(const tiers of scope.postings.values())for(const bits of tiers.values())assert.ok(bits<(1n<<12n));
});
test('Virtual weapon backups remain version-one compatible and malformed selectors are rejected',()=>{
 const evaluation={slots:{},skills:[],zenith:[],automatic:[],errors:[],configuration_warnings:[]};
 const favorite={build:{weapon_type:'MS',sex:'男',armor:{},cuffs:[],weapon:{virtual:true,slots:3,slot_mode:'shared',sigils:1,jewels:[]}},evaluation,display:{}};
 const data={favorites:[favorite],inventory:{},profiles:[],lang:'ja',theme:'dark'};
 assert.doesNotThrow(()=>validateBackup(makeBackup(data)));
 const bad=structuredClone(data);bad.favorites[0].build.weapon.slots=4;
 assert.throws(()=>validateBackup(makeBackup(bad)));
 const mixed=structuredClone(data);mixed.favorites[0].build.weapon.page='physical';
 assert.throws(()=>validateBackup(makeBackup(mixed)));
});
test('Paging resets only the skill-list scroll, while ordinary rerenders retain scroll',()=>{
 assert.ok(src.includes("skillPage--;renderSkills();$('skillRows').scrollTop=0"));
 assert.ok(src.includes("skillPage++;renderSkills();$('skillRows').scrollTop=0"));
 assert.ok(src.includes('if(oldFilter===filterKey)root.scrollTop=oldScroll'));
});
test('Live refresh queries the index before conditionally launching a bounded background solver',()=>{
 const pump=src.slice(src.indexOf('function pumpLive(){'),src.indexOf('function pauseLiveForTab'));
 assert.ok(pump.indexOf("'/api/candidates/query'")<pump.indexOf("'/api/search'"));
 assert.ok(pump.includes("if(cached.status==='input_conflict'||!needMore"));
 assert.ok(pump.includes('epoch!==live.epoch'));
 assert.ok(pump.includes('live.rounds<3'));
});
