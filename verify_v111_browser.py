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
 print('tab state, reload, live cancellation passed; errors:',errors,flush=True);assert not errors,errors;print('POSTs',sum(m=='POST' and u=='/api/search' for m,u in calls),'DELETEs',sum(m=='DELETE' for m,u in calls));browser.close()
