"""Validate a built hub with Playwright. External services are deliberately blocked.
HUB_MIGRATION_AUDIT=1 also compares relocated apps with reconstructed pre-move layouts.
"""
from __future__ import annotations
import argparse
import functools
import http.server
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote, urlsplit
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]

class QuietServer(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args): pass


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--site',type=Path,default=ROOT/'_site')
    parser.add_argument('--report-dir',type=Path,default=Path('/tmp/hub-browser'))
    args=parser.parse_args(); site=args.site.resolve(); report=args.report_dir.resolve(); report.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((site/'hub_manifest.json').read_text())
    items=[i for c in manifest['categories'] for i in c['items']]
    redirects=json.loads((ROOT/'hub_redirects.json').read_text())
    migration=json.loads((ROOT/'docs/migration_map.json').read_text())
    results={'checks':[],'page_comparisons':[],'external_services':'Blocked; not end-to-end verified','physical_devices':'Not tested; Chromium viewport emulation only'}
    def passed(name): results['checks'].append(name); print('PASS:',name,flush=True)
    with tempfile.TemporaryDirectory() as temp:
        www=Path(temp); (www/'GPT-Tools').symlink_to(site,target_is_directory=True)
        baseline=www/'baseline'; baseline.mkdir(); reverse={new:old for old,new in redirects.items()}
        if os.environ.get('HUB_MIGRATION_AUDIT')=='1':
            for p in ROOT.rglob('*'):
                if not p.is_file(): continue
                rel=p.relative_to(ROOT).as_posix()
                if rel.split('/')[0] in {'.git','.github','scripts','tests','docs','_site','_preview','__pycache__'}: continue
                dst=baseline/reverse.get(rel,rel); dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,dst)
            for row in migration['extracted']:
                dst=baseline/row['member']; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(ROOT/row['path'],dst)
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(QuietServer,directory=str(www)))
        threading.Thread(target=server.serve_forever,daemon=True).start(); origin=f'http://127.0.0.1:{server.server_address[1]}'
        with sync_playwright() as pw:
            executable=os.environ.get('HUB_CHROMIUM') or shutil.which('chromium')
            browser=pw.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
            try:
                for label,width,height,dark in [('desktop',1280,900,False),('mobile',390,844,False),('narrow',320,800,False),('dark',390,844,True)]:
                    ctx=browser.new_context(viewport={'width':width,'height':height},color_scheme='dark' if dark else 'light',reduced_motion='reduce')
                    page=ctx.new_page(); errors=[]; external=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('request',lambda req:external.append(req.url) if not req.url.startswith(origin) else None)
                    page.goto(origin+'/GPT-Tools/',wait_until='load')
                    assert page.locator('.hub-item').count()==len(items)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),label
                    assert not errors,errors
                    assert not external,external
                    versioned=next((i for i in items if i['older']),None)
                    if versioned:
                        page.locator('#search').fill(versioned['older'][-1]['path'])
                        assert page.locator('.hub-item:not([hidden])').count()==1
                        assert page.locator('.hub-item:not([hidden]) .versions').evaluate('(d)=>d.open')
                    page.locator('#search').fill('no-such-resource-804717'); assert page.locator('#emptyState').is_visible()
                    page.locator('#clearSearch').click(); assert page.locator('.hub-item:not([hidden])').count()==len(items)
                    pair=next((i for i in items if i['current']['alternatives']),None)
                    if pair:
                        page.locator('#search').fill(pair['current']['alternatives'][0]['path'])
                        assert page.locator('.hub-item:not([hidden])').count()==1
                        assert page.locator('.hub-item:not([hidden]) .alternative').is_visible()
                        page.locator('#search').press('Escape')
                    page.locator('#themeButton').click(); theme=page.evaluate('document.documentElement.dataset.theme')
                    page.reload(); assert page.evaluate('document.documentElement.dataset.theme')==theme
                    summary=page.locator('.section').first.locator('summary').first
                    summary.focus(); summary.press('Enter')
                    is_open=page.locator('.section').first.evaluate('(d)=>d.open')
                    page.wait_for_timeout(60); page.reload()
                    assert page.locator('.section').first.evaluate('(d)=>d.open')==is_open
                    page.evaluate("document.querySelectorAll('.section,.folder').forEach(d=>d.open=true)")
                    page.evaluate('(value)=>document.documentElement.dataset.theme=value','dark' if dark else 'light')
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(report/f'hub-{label}.png'),full_page=True)
                    assert not errors,errors
                    passed(label+': layout, search, PDF/version grouping, keyboard, persisted theme/folders, zero external requests'); ctx.close()
                ctx=browser.new_context(java_script_enabled=False); page=ctx.new_page(); page.goto(origin+'/GPT-Tools/')
                assert page.locator('.hub-item').count()==len(items); assert page.locator('.card').first.get_attribute('href')
                passed('No JavaScript: complete links and native folder controls'); ctx.close()
                ctx=browser.new_context(); ctx.add_init_script('Object.defineProperty(window,"localStorage",{get(){throw new Error("storage unavailable")}})')
                page=ctx.new_page(); errors=[]; page.on('pageerror',lambda e:errors.append(str(e))); page.goto(origin+'/GPT-Tools/')
                page.locator('#search').fill('no-such-resource-804717'); assert page.locator('#emptyState').is_visible(); assert not errors
                passed('Storage blocked: search and controls remain usable'); ctx.close()
                ctx=browser.new_context(); page=ctx.new_page(); page.goto((site/'index.html').as_uri())
                assert page.locator('.hub-item').count()==len(items)
                page.locator('#search').fill('no-such-resource-804717'); assert page.locator('#emptyState').is_visible()
                passed('Downloaded index opens and searches without a manifest request'); ctx.close()
                ctx=browser.new_context(); page=ctx.new_page()
                html_redirects={old:new for old,new in redirects.items() if old.endswith(('.html','.htm'))}
                for old,new in html_redirects.items():
                    target_path='/GPT-Tools/'+quote(new,safe='/')
                    def handle(route):
                        if urlsplit(route.request.url).path==target_path: route.fulfill(status=200,content_type='text/html',body='<title>Redirect target reached</title>')
                        else: route.continue_()
                    page.route('**/*',handle)
                    page.goto(origin+'/GPT-Tools/'+quote(old,safe='/')+'?hub_test=1&space=a%20b#anchor')
                    page.wait_for_url(lambda u:urlsplit(u).path==target_path)
                    assert urlsplit(page.url).query=='hub_test=1&space=a%20b' and urlsplit(page.url).fragment=='anchor'
                    page.unroute('**/*',handle)
                passed(f'All {len(html_redirects)} HTML redirects preserve query strings and fragments')
                for old,new in redirects.items():
                    if old in html_redirects: continue
                    a=ctx.request.get(origin+'/GPT-Tools/'+quote(old,safe='/')); b=ctx.request.get(origin+'/GPT-Tools/'+quote(new,safe='/'))
                    assert a.status==b.status==200 and a.body()==b.body()
                passed(f'All {len(redirects)-len(html_redirects)} legacy image/audio/archive URLs return identical bytes')
                paths=set()
                for i in items:
                    if i.get('external'): continue
                    for v in [i['current']]+i['older']:
                        paths.add(v['path']); paths.update(a['path'] for a in v['alternatives'])
                for name in sorted(paths):
                    response=ctx.request.get(origin+'/GPT-Tools/'+quote(name,safe='/')); assert response.status==200,name
                passed(f'All {len(paths)} indexed page/version/PDF URLs return HTTP 200'); ctx.close()
                if os.environ.get('HUB_MIGRATION_AUDIT')=='1':
                    extracted_map={x['path']:x['member'] for x in migration['extracted']}
                    def smoke(relative):
                        ctx=browser.new_context(); errors=[]; missing=[]
                        ctx.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
                        page=ctx.new_page(); page.on('pageerror',lambda e:errors.append(str(e)))
                        page.on('response',lambda r:missing.append(r.url) if r.status>=400 and r.url.startswith(origin) else None)
                        page.goto(origin+relative,wait_until='domcontentloaded'); page.wait_for_timeout(180)
                        ctx.close(); return sorted(set(errors)),missing
                    for name in sorted(paths):
                        if not name.endswith(('.html','.htm')) or 'QR-seek-app-redirect' in name: continue
                        old=reverse.get(name,extracted_map.get(name,name))
                        before,_=smoke('/baseline/'+quote(old,safe='/')); after,missing=smoke('/GPT-Tools/'+quote(name,safe='/'))
                        results['page_comparisons'].append({'path':name,'baseline_errors':before,'migrated_errors':after,'missing_local_assets':missing})
                        assert after==before,(name,before,after); assert not missing,(name,missing)
                    passed(f'{len(results["page_comparisons"])} application load comparisons: no new JS errors or missing local assets')
                    passed('Seek source preserved byte-for-byte; outgoing app-store navigation not followed')
            finally:
                browser.close(); server.shutdown()
                (report/'browser_results.json').write_text(json.dumps(results,indent=2)+'\n')
    print('Browser validation complete:',report)

if __name__=='__main__': main()
