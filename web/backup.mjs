
// Only the app's own keys are eligible for backup; no arbitrary localStorage keys.
const keys=['mhf.favorites','mhf.inventory','mhf.profiles','mhf.lang','mhf.theme','mhf.collection','mhf.materials'];
const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const str=x=>typeof x==='string';
const list=x=>Array.isArray(x);
const parts=['head','body','arm','waist','leg'];
const wts=['MS','SnS','DB','GS','LS','Hammer','HH','Lance','GL','SA','Tonfas','HBG','LBG','Bow'];
const ref=x=>obj(x)&&str(x.id);
const idlist=x=>list(x)&&x.every(str);
const virtual=x=>obj(x)&&x.virtual===true&&!('page' in x)&&!('anchor' in x)&&!('template' in x)&&Number.isInteger(x.slots)&&x.slots>=0&&x.slots<=3&&['decoration','shared'].includes(x.slot_mode);
const row=x=>obj(x)&&str(x.item)&&str(x.level)&&idlist(x.jewels||[]);
const build=x=>obj(x)&&wts.includes(x.weapon_type)&&['男','女'].includes(x.sex)&&obj(x.armor)&&Object.entries(x.armor).every(([k,v])=>parts.includes(k)&&row(v))&&idlist(x.cuffs||[])&&(!x.weapon||(obj(x.weapon)&&(virtual(x.weapon)||(str(x.weapon.page)&&str(x.weapon.anchor)))&&idlist(x.weapon.jewels||[])));
const evaluation=x=>obj(x)&&obj(x.slots)&&list(x.skills)&&x.skills.every(s=>obj(s)&&list(s.contributions))&&list(x.zenith)&&list(x.automatic)&&list(x.errors)&&list(x.configuration_warnings)&&(!x.bounty||list(x.bounty.warnings));
const favorite=x=>obj(x)&&build(x.build)&&evaluation(x.evaluation)&&obj(x.display)&&(!x.title||str(x.title))&&(!x.category||str(x.category));
const state=x=>obj(x)&&obj(x.fields)&&obj(x.checks)&&list(x.required)&&list(x.optional)&&(x.forbidden===undefined||list(x.forbidden))&&[...x.required,...x.optional,...(x.forbidden||[])].every(s=>obj(s)&&str(s.id)&&Number.isFinite(s.points))&&obj(x.armor)&&Object.entries(x.armor).every(([k,v])=>parts.includes(k)&&ref(v)&&list(v.jewels)&&v.jewels.every(ref)&&list(v.levels))&&(!x.weapon||(obj(x.weapon)&&(virtual(x.weapon)||(str(x.weapon.page)&&str(x.weapon.anchor)))&&list(x.weapon.jewels)&&x.weapon.jewels.every(ref)))&&list(x.cuffs)&&x.cuffs.every(ref)&&list(x.excluded)&&x.excluded.every(v=>obj(v)&&(str(v.id)||(str(v.page)&&str(v.anchor))))&&idlist(x.classes);
const inventory=x=>obj(x)&&Object.entries(x).every(([k,v])=>obj(v)&&ref(v.item)&&v.item.id===k&&[...parts,'jewel','cuff'].includes(v.kind)&&Number.isInteger(v.count)&&v.count>=0&&v.count<=9999);
// New collection field is optional for old version-1 backups.
const collection=x=>obj(x)&&list(x.weapons)&&x.weapons.every(w=>obj(w)&&wts.includes(w.weapon_type)&&str(w.page)&&str(w.anchor)&&str(w.ja)&&str(w.en)&&(!w.alias||str(w.alias))&&Number.isInteger(w.count)&&w.count>=1&&w.count<=9999)&&list(x.sigils)&&x.sigils.every(s=>obj(s)&&str(s.id)&&str(s.label)&&list(s.effects)&&s.effects.length>=1&&s.effects.length<=3&&s.effects.every(e=>obj(e)&&str(e.name)&&e.name.length>0&&str(e.value)));
// Material stock and per-build progress are optional for older backups.
const materials=x=>obj(x)&&obj(x.stock)&&Object.entries(x.stock).every(([k,v])=>/^(ja|en):.+$/.test(k)&&Number.isInteger(v)&&v>=0&&v<=9999999)&&obj(x.plans)&&Object.entries(x.plans).every(([k,p])=>/^[a-f0-9]{64}$/.test(k)&&obj(p)&&obj(p.steps)&&Object.entries(p.steps).every(([id,s])=>/^\d+$/.test(id)&&obj(s)&&Number.isInteger(s.choice)&&s.choice>=0&&Number.isInteger(s.done)&&s.done>=0));
// Validation happens before any local storage changes. Reject unknown versions and malformed records.
function validateBackup(raw){
  if(!obj(raw)||raw.format!=='mhf-skill-backup'||raw.version!==1||!obj(raw.data))throw Error('Unsupported backup format/version');
  const d=raw.data;
  if((d.materials!==undefined&&!materials(d.materials))||(d.collection!==undefined&&!collection(d.collection))||!list(d.favorites)||!d.favorites.every(favorite)||!inventory(d.inventory)||!list(d.profiles)||!d.profiles.every(p=>obj(p)&&str(p.name)&&state(p.state))||!['ja','en'].includes(d.lang)||!['light','dark'].includes(d.theme))throw Error('Invalid backup records');
  return d;
}
function makeBackup(data){return {format:'mhf-skill-backup',version:1,created_at:new Date().toISOString(),data};}
// Restore is replace-only, with best-effort rollback on quota or other storage failures.
function restoreBackup(storage,raw){
  const d=validateBackup(raw), previous=keys.map(k=>[k,storage.getItem(k)]);
  const values=[JSON.stringify(d.favorites),JSON.stringify(d.inventory),JSON.stringify(d.profiles),d.lang,d.theme,JSON.stringify(d.collection||{weapons:[],sigils:[]}),JSON.stringify(d.materials||{stock:{},plans:{}})];
  try{keys.forEach((k,i)=>storage.setItem(k,values[i]));}catch(e){
    let failed=false;for(const [k,v] of previous){try{if(v===null)storage.removeItem(k);else storage.setItem(k,v)}catch{failed=true}}
    if(failed)throw Error('Restore and rollback failed; retain the original backup file.');throw e;
  }
  return d;
}


export {keys,makeBackup,validateBackup,restoreBackup};
