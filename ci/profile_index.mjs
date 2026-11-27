// Local benchmark input is generated from the private DB by profile_search.py.
import {readFileSync,writeFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import assert from 'node:assert/strict';
import {performance} from 'node:perf_hooks';
const src=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const c={parts:['head','body','arm','waist','leg']};
runInNewContext(src.slice(src.indexOf('class CandidateIndex{'),src.indexOf('Object.assign(words,{virtualWeapon:'))+'\nglobalThis.Index=CandidateIndex;',c);
runInNewContext(src.slice(src.indexOf('function liveAchieved('),src.indexOf('function liveSpec(')),c);
const hits=JSON.parse(readFileSync(process.argv[2],'utf8'));
const targets=new Map();
for(const h of hits)for(const [id,pt] of c.Index.attained(h.evaluation))targets.set(id+'|'+pt,{skill:id,points:pt});
const rows=[...targets.values()].slice(0,40);
const common=rows.find(s=>hits.every(h=>c.liveAchieved(h.evaluation,s.skill,s.points)));
const required=common?[common]:[];
const memoryBefore=process.memoryUsage();const index=new c.Index();let start=performance.now();index.ingest('scope',hits);const build=performance.now()-start;
const indexed=[],naive=[];
for(let i=0;i<30;i++){
 start=performance.now();const expected=rows.map(s=>hits.filter(h=>required.every(r=>c.liveAchieved(h.evaluation,r.skill,r.points))&&c.liveAchieved(h.evaluation,s.skill,s.points)).length);naive.push(performance.now()-start);
 start=performance.now();const actual=rows.map(s=>index.count('scope',required,s.skill,s.points));indexed.push(performance.now()-start);assert.deepEqual(actual,expected);
}
const stats=xs=>{xs.sort((a,b)=>a-b);return {median_ms:xs[Math.floor(xs.length/2)],p95_ms:xs[Math.floor(xs.length*.95)-1]}};
const after=process.memoryUsage();
const result={candidates:hits.length,visible_skill_rows:rows.length,index_build_ms:build,naive_scan:stats(naive),bitset:stats(indexed),
 heap_delta_mib:(after.heapUsed-memoryBefore.heapUsed)/1024**2,process_rss_mib:after.rss/1024**2};
if(process.argv[3])writeFileSync(process.argv[3],JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result,null,2));
