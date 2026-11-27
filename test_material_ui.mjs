import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
// Exercise the exact calculation included in the browser script, without a DOM.
const src=fs.readFileSync(new URL('./web/app.js',import.meta.url),'utf8');
const fn=src.slice(src.indexOf('function materialTotals()'),src.indexOf('function renderMaterialTotals()'));
const context={lang:'ja',name:m=>m.ja,materialState:{stock:{'ja:A':4}},materialPlan:{steps:[{id:'1',count:3,options:[{materials:[{key:'ja:A',ja:'A',qty:2}]},{materials:[{key:'ja:B',ja:'B',qty:100}]}]},{id:'2',count:1,options:[{materials:[{key:'ja:A',ja:'A',qty:3}]}]},{id:'3',count:1,options:[]}]},materialProgress:s=>({choice:0,done:s.id==='1'?1:0})};
test('only chosen recipe, remaining quantities, and stock are counted',()=>{const result=vm.runInNewContext(fn+'\nJSON.stringify(materialTotals())',context);const rows=JSON.parse(result);assert.equal(rows.length,1);assert.equal(rows[0].required,7);assert.equal(rows[0].missing,3)});
