"""Real Chromium regressions for persisted filtering, proof colours and source UI."""
import json,os,re,runpy,shutil,tempfile,time,sys
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from web_api import create_app
ROOT=Path(__file__).parent

def main():
 # Preserve and execute all previous browser checks unchanged.
 if '--only-new' not in sys.argv:runpy.run_path(str(ROOT/'verify_v130_browser.py'),run_name='__main__')
 fixtures=json.loads((ROOT/'ci/v120_regression_builds.json').read_text(encoding='utf-8'))
 html=(ROOT/'web/index.html').read_text();html=re.sub(r'<script src="/static/app.js[^>]*></script>','',html);html=re.sub(r'<link[^>]*href="/static/[^>]*>','',html)
 with tempfile.TemporaryDirectory() as folder,TestClient(create_app(os.environ['MHF_TEST_DB'],candidate_cache_path=Path(folder)/'cache.json')) as client,sync_playwright() as pw:
  service=client.app.state.candidates;service.prepare_index();service.index_thread.join(40);assert service.index_status()['state']=='ready'
  browser=pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),args=['--no-sandbox']);page=browser.new_page();errors=[];calls=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  def api(url,opts):
   method=opts.get('method','GET');calls.append((method,url));r=client.request(method,url,json=json.loads(opts['body']) if opts.get('body') else None);return {'status':r.status_code,'data':r.json()}
  page.expose_function('testApi',api);page.set_content(html);page.add_style_tag(content=(ROOT/'web/style.css').read_text())
  page.evaluate("""()=>{const m=new Map([['mhf.liveSearch','off']]);const storage={getItem:k=>m.get(k)??null,setItem:(k,v)=>m.set(k,String(v)),removeItem:k=>m.delete(k)};Object.defineProperty(window,'localStorage',{value:storage});Object.defineProperty(window,'sessionStorage',{value:storage});window.fetch=async(url,opts={})=>{const r=await testApi(url,opts);return {ok:r.status<300,status:r.status,json:async()=>r.data}}}""")
  page.add_script_tag(content=(ROOT/'web/app.js').read_text());page.wait_for_function('live.ready')
  q=page.evaluate('makeBuild(true,true)');build=fixtures['road16']['build'];report=service.evaluate(build)
  service.ingest(q,{'results':[{'build':build,'evaluation':report}]})
  page.evaluate("""()=>{required=[];live.enabled=true;live.key=null;renderSkills();scheduleLive()}""")
  page.wait_for_function('result?.results?.length>0');before=sum(u=='/api/search' for _,u in calls)
  with patch('web_api.subprocess.Popen',side_effect=AssertionError('Confirmed skill edits must not launch a solver')):
   for skill in ['磁斬鎚技【磁星】','剛撃+6','不退ノ構']:
    page.locator('#skillQuery').fill(skill);page.locator('#skillRows .skill-quick-add').first.click();page.wait_for_timeout(250)
    assert page.evaluate('result.results.length>0')
   assert sum(u=='/api/search' for _,u in calls)==before
  # Colour states use server proof completeness, never zero cached counts alone.
  page.evaluate("""()=>{const s=skills.find(x=>x.ja==='耳栓強化+1');required.push({...s});renderSkills()}""")
  assert page.locator('[data-source-skill]').count()>=4
  page.locator('[data-source-skill][data-provider=weapon]').first.uncheck()
  assert page.evaluate("Object.values(JSON.parse($('zenithSourceRules').value))[0].length") == 3
  page.locator('#liveToggle').uncheck();page.wait_for_function('live.task===null')
  page.evaluate("""()=>{$('skillQuery').value='';$('skillCategory').value='';skillPage=0;renderSkills();const targets=skills.slice(0,3);live.enabled=true;live.remoteCounts={[targets[0].id+'|'+targets[0].points]:1};live.remoteStates=Object.fromEntries(targets.map((s,i)=>[s.id+'|'+s.points,{state:['confirmed','proven_infeasible','unknown'][i]}]));paintLiveCounts()}""")
  assert page.locator('.skill-confirmed').count()>0
  assert page.locator('.skill-proven').count()>0
  assert page.locator('.skill-unknown').count()>0
  timing=page.evaluate("""h=>{result={status:'confirmed',results:[h],confirmed_builds:1};const samples={paint:[],display:[],display_cards:1};for(let i=0;i<20;i++){let start=performance.now();paintLiveCounts();samples.paint.push(performance.now()-start);start=performance.now();renderResults();samples.display.push(performance.now()-start)}if($('resultCards').querySelectorAll('article.result').length!==1)throw Error('Result card expected');return samples}""",{'build':build,'evaluation':report})
  (ROOT/'.local/v140-browser-timings.json').write_text(json.dumps(timing,indent=2),encoding='utf-8')
  page.screenshot(path=str(ROOT/'.local/v140-browser.png'),full_page=True)
  assert not errors,errors;browser.close()
 print('1.4.0: persisted confirmed edits without solver, Zenith supply controls, green/proven-red/unknown colours passed',flush=True)

if __name__=='__main__':main()
