import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import assert from 'node:assert/strict';
import {test} from 'node:test';
const source=readFileSync('web/app.js','utf8');
const html=readFileSync('web/index.html','utf8');
function setup(native){
  const nodes=new Map(),events={};
  function el(tag,text){return {textContent:text??'',hidden:false,disabled:false,children:[],append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items},get childElementCount(){return this.children.length},addEventListener(){},showModal(){this.open=true}}}
  const $=id=>{if(!nodes.has(id))nodes.set(id,el('div'));return nodes.get(id)};
  const window={pywebview:native?{api:native}:undefined,addEventListener:(k,f)=>events[k]=f};
  runInNewContext(source.slice(source.indexOf('(function desktopInformation(){')),{window,$,el,lang:'ja',Date,Number});
  return {$,window,events};
}
const info={app:'1.1.0-rc.6',launcher:'1.1.0-rc.5',channel:'preview',startup:true,history:[{at:'2026-11-27T01:30:00Z',status:'launcher_installed',version:'1.1.0-rc.5'}],backups:3,checkpoint:true,previous_app:true,previous_launcher:true};
test('settings are hidden in web-only mode',()=>{const f=setup(null);assert.equal(f.$('desktopInfoOpen').hidden,true);assert.ok(html.includes('id="desktopInfoDialog"'))});
test('native settings show independently reported versions and history',async()=>{const f=setup({version_information:async()=>info});assert.equal(f.$('desktopInfoOpen').hidden,false);await f.$('desktopInfoOpen').onclick();assert.equal(f.$('desktopInfoVersions').children[0].children[1].textContent,'1.1.0-rc.6');assert.equal(f.$('desktopInfoVersions').children[1].children[1].textContent,'1.1.0-rc.5');assert.equal(f.$('desktopInfoHistory').children.length,1)});
test('manual discovery does not install and settings save explicitly',async()=>{let saved=[];const f=setup({version_information:async()=>info,configure_updates:async(...args)=>saved=args,discover_updates:async()=>({status:'available',version:'1.1.0'})});await f.$('desktopInfoOpen').onclick();await f.$('desktopInfoCheck').onclick();assert.match(f.$('desktopInfoStatus').textContent,/1\.1\.0.*再起動/);assert.equal(saved.length,0);f.$('desktopInfoStartup').checked=false;f.$('desktopInfoChannel').value='stable';await f.$('desktopInfoSave').onclick();assert.deepEqual(saved,[false,'stable'])});
