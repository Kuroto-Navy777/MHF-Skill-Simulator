import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import assert from 'node:assert/strict';
import { test } from 'node:test';
const src=readFileSync('web/app.js','utf8');
const html=readFileSync('web/index.html','utf8');
// Test the pure result filter, without browser APIs or network.
const match=runInNewContext(src.slice(src.indexOf('function resultMatches('),src.indexOf('function resultFilterState('))+'\nresultMatches');
const hit={display:{items:{head:{ja:'フィンスZPヘッド'}}},evaluation:{skills:[{ja:'剛撃',level_ja:'剛撃+6',status:'active'},{ja:'幕無',status:'overflow'}],zenith:[{ja:'巧撃強化',level:1,has_base_skill:false}],protection:Array.from({length:3},()=>({super_protection:true}))},metrics:{free_jewel_slots:2,res_Fire:55,res_Water:56,res_Thunder:null,optional:[{achieved:true}]}};
const f={q:'',free:0,res:0,super:false,optional:false};
test('Search by name and active skill, not inactive skill',()=>{assert.ok(match(hit,{...f,q:'フィンス 剛撃＋６'}));assert.ok(!match(hit,{...f,q:'幕無'}));assert.ok(!match(hit,{...f,q:'巧撃強化'}))});
test('Resistance, free slots, optional and protection filters',()=>{assert.ok(match(hit,{...f,res:2,free:2,super:true,optional:true}));assert.ok(!match(hit,{...f,res:3}));assert.ok(!match(hit,{...f,free:3}));assert.ok(!match({...hit,metrics:{}},{...f,optional:true}))});
test('New HTML controls and cache version',()=>{const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(x=>x[1]);assert.equal(ids.length,new Set(ids).size);for(const k of ['roadFloor','road_advance','road_last_stand','road_revival','road_points','road_initial_gm','resultFilters','resultQuery','resultFree','resultResistance','resultSuper','resultOptional','resultReset','mealEffect','armorLevelMode','applyArmorLevel'])assert.ok(ids.includes(k),k);assert.ok(/app\.js\?v=[a-z0-9]+/.test(html))});
