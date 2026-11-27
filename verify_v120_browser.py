"""Optional browser regression harness. Requires Playwright and Chromium; API calls use TestClient."""
import sys,json,re,os,shutil,tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parent))
from web_api import create_app
root=Path(__file__).resolve().parent; db=Path(os.environ['MHF_TEST_DB'])
html=(root/'web/index.html').read_text();html=re.sub(r'<script src="/static/app.js[^>]*></script>','',html);html=re.sub(r'<link[^>]*href="/static/[^>]*>','',html)
with tempfile.TemporaryDirectory(prefix='mhf-browser-test-') as cache_dir, TestClient(create_app(db,candidate_cache_path=Path(cache_dir)/'search-cache.json')) as client, sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),args=['--no-sandbox']);errors=[];calls=[]
 def new_page(data=None):
  page=browser.new_page(viewport={'width':1400,'height':900});page.on('pageerror',lambda e:errors.append(str(e)))
  def api_call(url,opts):
   method=opts.get('method','GET');body=opts.get('body');calls.append((method,url));res=client.request(method,url,json=json.loads(body) if body else None);return {'status':res.status_code,'data':res.json()}
  page.expose_function('testApi',api_call)
  page.set_content(html);page.add_style_tag(content=(root/'web/style.css').read_text());page.evaluate('''data=>{const makeStorage=initial=>{const m=new Map(Object.entries(initial||{}));return {getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,String(v)),removeItem:k=>m.delete(k),dump:()=>Object.fromEntries(m)}};Object.defineProperty(window,'localStorage',{value:makeStorage(data)});Object.defineProperty(window,'sessionStorage',{value:makeStorage()});window.fetch=async(url,opts={})=>{const r=await testApi(url,opts);return {ok:r.status>=200&&r.status<300,status:r.status,json:async()=>r.data}}}''',data or {})
  page.add_script_tag(content=(root/'web/app.js').read_text());page.wait_for_function('typeof live !== "undefined" && live.ready',timeout=20000);return page
 page=new_page();print('init',page.locator('#liveStatus').inner_text(),flush=True)
 page.wait_for_function('result?.results?.length > 0',timeout=30000);assert page.locator('#liveSampleList').is_visible();assert page.evaluate('result.results.every(h=>h.evaluation.valid)');print('baseline candidates',page.evaluate('result.results.length'),flush=True)
 page.locator('#liveToggle').uncheck();page.locator('#skillQuery').fill('剛撃+6');page.locator('#skillRows .skill-quick-add').first.click();assert '剛撃+6' in page.locator('#required').inner_text()
 page.locator('[data-tab=manual]').click();assert page.locator('#workspace-tab-gear').get_attribute('aria-selected')=='true';page.locator('#wt').select_option('SnS');page.locator('[data-workspace-tab=external]').click()
 page.locator('[data-tab=search]').click();assert page.locator('#workspace-tab-skills').get_attribute('aria-selected')=='true';assert page.locator('#wt').input_value()=='MS';assert '剛撃+6' in page.locator('#required').inner_text()
 page.locator('[data-tab=manual]').click();assert page.locator('#wt').input_value()=='SnS';assert page.locator('#workspace-tab-external').get_attribute('aria-selected')=='true';page.locator('[data-tab=search]').click()
 page.wait_for_timeout(800);data=page.evaluate('localStorage.dump()');page.close();page=new_page(data);assert page.locator('#workspace-tab-skills').get_attribute('aria-selected')=='true';assert '剛撃+6' in page.locator('#required').inner_text();assert page.locator('#skillQuery').input_value()=='剛撃+6'
 page.locator('#liveToggle').check();page.wait_for_function('live.task !== null',timeout=10000)
 page.locator('#skillQuery').fill('一閃+3');page.locator('#skillRows .skill-quick-add').first.click();page.wait_for_timeout(1000);assert page.evaluate('required.length')==2
 page.locator('#liveToggle').uncheck();page.wait_for_function('live.task===null',timeout=15000)
 print('tab state, reload, live cancellation passed; errors:',errors,flush=True);assert not errors,errors;print('POSTs',sum(m=='POST' and u=='/api/search' for m,u in calls),'DELETEs',sum(m=='DELETE' for m,u in calls));
 # Search the reported four-skill case through the actual live UI, then replay
 # exactly the same build through the manual API endpoint.
 before=sum(m=='POST' and u=='/api/search' for m,u in calls)
 page.evaluate("""()=>{required=['磁斬鎚技【磁星】','不退ノ構','剛撃+6','一閃+2'].map(n=>skills.find(s=>s.ja===n));if(required.some(x=>!x))throw Error('tier missing');renderSkills();live.enabled=true;live.key=null;scheduleLive()}""")
 page.wait_for_function("result?.results?.length>0 && result.results.every(h=>required.every(s=>liveAchieved(h.evaluation,s.id,s.points)))",timeout=45000)
 assert sum(m=='POST' and u=='/api/search' for m,u in calls)>before
 hit=page.evaluate('result.results[0]')
 manual=client.post('/api/evaluate',json=hit['build']).json()
 assert manual['evaluation']==hit['evaluation']
 assert '一閃' in page.locator('#resultCards').inner_text()
 # Every real select option must invoke immediate rerender without another POST.
 page.locator('#liveToggle').uncheck();page.wait_for_function('live.task===null',timeout=15000)
 before=len(calls)
 for key in page.locator('#sort option').evaluate_all('(nodes)=>nodes.map(n=>n.value)'):
  page.locator('#sort').select_option(key)
 assert len(calls)==before
 root.joinpath('.local').mkdir(exist_ok=True)
 page.screenshot(path=str(root/'.local/v112-browser.png'),full_page=True)
 print('four required live search, manual API replay, overlap display, all UI sorts passed',flush=True)
 assert not errors,errors
 
 # New 1.2.0 UI regressions: scroll policy, virtual slots and an actually verified
 # reservoir large enough that ordinary skill changes must not invoke MILP.
 import copy,sqlite3,time
 from contextlib import closing
 from search_engine import Searcher
 from candidate_validation import validate
 fixtures=json.loads((root/'ci/v120_regression_builds.json').read_text(encoding='utf-8'))
 page.close();page=new_page({'mhf.liveSearch':'off'})
 page.locator('#skillRows').evaluate('(n)=>n.scrollTop=240')
 page.locator('#skillNext').click();assert page.locator('#skillRows').evaluate('(n)=>n.scrollTop')==0
 page.locator('#skillRows').evaluate('(n)=>n.scrollTop=240')
 page.locator('#skillPrev').click();assert page.locator('#skillRows').evaluate('(n)=>n.scrollTop')==0
 page.locator('#skillRows').evaluate('(n)=>n.scrollTop=240')
 page.locator('#skillRows .skill-quick-add').nth(3).evaluate('(n)=>n.click()')
 assert page.locator('#skillRows').evaluate('(n)=>n.scrollTop')==240
 page.locator('[data-tab=manual]').click();page.locator('[data-tab=search]').click()
 assert page.locator('#skillRows').evaluate('(n)=>n.scrollTop')==240
 page.locator('[data-workspace-tab=gear]').click()
 page.locator('#weaponMode').select_option('virtual')
 for capacity in range(4):
  page.locator('#virtualSlots').select_option(str(capacity))
  virtual=page.evaluate('makeBuild(true,true).weapon')
  assert virtual['virtual'] is True and virtual['slots']==capacity and 'page' not in virtual
 page.locator('#virtualSlots').select_option('3');page.locator('#virtualSlotMode').select_option('shared');page.locator('#sigils').select_option('2')
 assert page.evaluate('makeBuild(true,true).weapon.sigils')==2
 page.locator('#virtualSlotMode').select_option('decoration');assert page.locator('#sigils').input_value()=='0'
 h15=client.post('/api/evaluate',json=fixtures['road15']['build']).json()
 h16=client.post('/api/evaluate',json=fixtures['road16']['build']).json()
 page.evaluate('async h=>await loadHit(h)',h16)
 assert page.locator('#weaponMode').input_value()=='virtual'
 assert page.evaluate('makeBuild(false).weapon.virtual') is True
 manual=client.post('/api/evaluate',json=page.evaluate('makeBuild(false)')).json()
 assert manual['evaluation']==h16['evaluation']
 # Set a broad valid context and preload 48 independently evaluated distinct heads.
 page.evaluate("""async h=>{await loadHit(h);switchTab('search',true);armor={};weapon=null;$('weaponMode').value='none';$('armorLevelMode').value='first';required=[];optional=[];forbidden=[];$('fixCuffs').checked=true;renderEquipment();renderSkills()}""",h15)
 broad=page.evaluate('makeBuild(true,true)');hits=[]
 with closing(sqlite3.connect(db)) as raw:
  engine=Searcher(raw);prepared=engine.prepare_request(broad)
  wanted=engine.requirement({'skill':'剛撃+1'})
  for eid,row in engine.by_kind['head'].items():
   build=copy.deepcopy(fixtures['road15']['build']);build['armor']['head']['item']=eid
   if not any(lv[0]=='L1' and lv[1]==3 for lv in engine.levels[eid]):continue
   report,reasons=validate(engine,prepared,build)
   if report and engine.achieved(report,*wanted):
    hits.append({'build':build,'evaluation':report,'new_jewels':15})
   if len(hits)>=48:break
 assert len(hits)==48
 client.app.state.candidates.ingest(broad,{'results':hits})
 before=sum(m=='POST' and u=='/api/search' for m,u in calls)
 page.locator('#liveToggle').check()
 page.wait_for_function('live.task===null&&result?.confirmed_builds>=48',timeout=20000)
 assert sum(m=='POST' and u=='/api/search' for m,u in calls)==before
 page.evaluate("""()=>{required=[skills.find(s=>s.ja==='剛撃+1')];renderSkills();scheduleLive()}""")
 assert page.evaluate('result.results.length')>0
 page.wait_for_function('live.task===null&&result?.confirmed_builds>=48',timeout=20000)
 page.wait_for_timeout(600)
 assert sum(m=='POST' and u=='/api/search' for m,u in calls)==before
 page.evaluate('()=>{required=[];renderSkills();scheduleLive()}')
 page.wait_for_timeout(800);page.wait_for_function('live.task===null&&result?.confirmed_builds>=48',timeout=10000)
 assert sum(m=='POST' and u=='/api/search' for m,u in calls)==before
 page.locator('#liveToggle').uncheck();page.wait_for_function('live.task===null',timeout=10000)
 # A real probe witness must appear synchronously when promoted to required.
 page.evaluate("""async data=>{await loadHit(data.hit);switchTab('search',true);for(const a of Object.values(armor))a.jewels=[];cuffs=[];$('fixCuffs').checked=false;required=data.required.map(x=>skills.find(s=>s.ja===x.skill));optional=[];forbidden=[];renderEquipment();renderSkills()}""",{'hit':h15,'required':fixtures['road15']['required']})
 req=page.evaluate('makeBuild(true,true)')
 job=client.post('/api/search',json={**req,'probe':{'candidates':[{'skill':'耳栓強化+1'}],'seconds':8}}).json()['id']
 deadline=time.monotonic()+20
 while time.monotonic()<deadline:
  status=client.get('/api/search/'+job).json()
  if status['status']!='running':break
  time.sleep(.1)
 assert status['status']=='done',status
 probe=status['result'];assert probe['results'][0]['status']=='found',probe
 page.evaluate('data=>{const spec=liveSpec(data.req);rememberLive(spec,data.hits)}',{'req':req,'hits':probe['results']})
 count=page.evaluate("""()=>{live.enabled=true;required.push(skills.find(s=>s.ja==='耳栓強化+1'));renderSkills();live.key=null;scheduleLive();return result.results.length}""")
 assert count>0,'Known earplug witness was lost before the background debounce'
 page.evaluate('async()=>{live.enabled=false;await stopLive()}')
 # The cuff-unlock action must preserve the current required skills and filters,
 # rather than taking the unrelated manual editor's draft.
 page.evaluate("$('seconds').value='27'")
 page.evaluate('async h=>await searchFromHit(h,true)',h15)
 rebuilt=page.evaluate('makeBuild(true,true)')
 assert 'cuffs' not in rebuilt and len(rebuilt['armor'])==5
 assert all(not a['jewels'] for a in rebuilt['armor'].values())
 assert rebuilt['seconds']==27
 assert any(x['skill']==page.evaluate("skills.find(s=>s.ja==='耳栓強化+1').id") for x in rebuilt['required'])
 page.evaluate("""data=>{required=data.req.required.map(x=>skills.find(s=>s.id===x.skill&&s.points===x.points));result={...data.probe,proof_key:probeProofKey(data.req)};renderSkills();renderResults()}""",{'req':req,'probe':probe})
 page.locator('[data-workspace-tab=gear]').click()
 page.locator('#fixCuffs').check(force=True)
 assert page.evaluate('result.proof_stale') is True
 assert '以前の条件' in page.locator('#resultCards').inner_text()
 page.locator('#fixCuffs').uncheck(force=True)
 assert page.evaluate('result.proof_stale') is False
 page.locator('[data-workspace-tab=skills]').click()
 page.screenshot(path=str(root/'.local/v120-browser.png'),full_page=True)
 assert not errors,errors
 print('1.2.0: pagination scroll, virtual 0..3/shared slots, virtual manual replay, 48 verified candidates with zero solver restarts, immediate probe witness passed',flush=True)
 browser.close()

