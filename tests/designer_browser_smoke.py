"""Provider review, privacy, native disclosure and decision-confirmation checks."""
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_adaptive import Integration,complete
from browser_smoke import DevTools
from werkzeug.serving import make_server
import questionnaire_engine as engine


def main():
    chrome=os.environ.get('CHROME_EXECUTABLE','C:/Program Files/Google/Chrome/Application/chrome.exe')
    if not Path(chrome).is_file():raise SystemExit('Set CHROME_EXECUTABLE to run browser checks.')
    Integration.setUpClass();fixture=Integration();fixture.setUp()
    root=Path(tempfile.mkdtemp(prefix='elunette-designer-browser-'));process=None;dev=None
    server=make_server('127.0.0.1',0,fixture.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        scenes=[];image_id=None
        fields=engine.fields_for(engine.sections(engine.load_catalog(),'posters_flyers'))
        cta=next(o['value'] for o in fields['PF08A']['options'] if o['value'] not in ('none','share','other'))
        for warning in (False,True):
            bid=fixture.new('posters_flyers')
            png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVzUAAAAASUVORK5CYII=')
            image=fixture.client.post(f'/client/briefs/{bid}/adaptive/assets',data={'csrf_token':fixture.token,'file':(io.BytesIO(png),'brand-image.png')}).json['id']
            document=fixture.client.post(f'/client/briefs/{bid}/adaptive/assets',data={'csrf_token':fixture.token,'file':(io.BytesIO(b'Approved creative references'),'creative-reference.txt')}).json['id']
            overrides={'META01':'A graduation to remember','PF02A':'celebrations','PF02J':'graduation','PF02C':'no',
                       'PF10A':'yes','PF10C':image,'PF11E':'yes','PF11F':document,'PF12A':'palette','PF12B':'warm_elegant',
                       'PF17A':'range','PF17B':{'amount':'1000.00','currency':'KES'},'PF17C':{'amount':'5000.00','currency':'KES'},
                       'PF06B':'A new chapter, thoughtfully celebrated.','REL01':'Hidden ministry answer'}
            if warning:overrides.update(PF08A=cta,PF08C=['website'])
            saved=fixture.save(bid,complete('posters_flyers',overrides));fixture.assertEqual(saved.status_code,200)
            fixture.assertEqual(saved.json['assessment']['percentage'],100)
            fixture.assertEqual(fixture.submit(bid,1).status_code,302)
            scenes.append((bid,'clarification' if warning else 'ready'));image_id=image
        bid=fixture.new('packaging_design');fixture.save(bid,complete('packaging_design',{'META01':'A thoughtful product label','PK09':'yes'}));fixture.submit(bid,1);scenes.append((bid,'verification'))
        qid=fixture.db.execute("INSERT INTO questionnaires(title,description,created_by,status) VALUES ('Custom provider brief','Existing questionnaire',2,'active')").lastrowid
        vid=fixture.db.execute('INSERT INTO questionnaire_versions(questionnaire_id) VALUES (?)',(qid,)).lastrowid
        question=fixture.db.execute("INSERT INTO questions(questionnaire_version_id,question_text,question_type,position,is_required,is_active) VALUES (?,'Project direction','text',1,1,1)",(vid,)).lastrowid
        fixture.db.execute('INSERT INTO questionnaire_publications(questionnaire_id,questionnaire_version_id,title_snapshot,description_snapshot) VALUES (?,?,?,?)',(qid,vid,'Custom provider brief','Existing questionnaire'))
        legacy=fixture.db.execute("INSERT INTO project_briefs(client_id,assigned_provider_id,questionnaire_version_id,title,status,completeness_percentage,submitted_at) VALUES (1,2,?,'An existing custom project','submitted',100,CURRENT_TIMESTAMP)",(vid,)).lastrowid
        fixture.db.execute("INSERT INTO brief_responses(brief_id,question_id,answer_text) VALUES (?,?,'Warm, confident and clear.')",(legacy,question));fixture.db.commit()
        fixture.login(2)
        process=subprocess.Popen([chrome,'--headless','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-extensions','--remote-debugging-port=0',f'--user-data-dir={root / "profile"}','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:port=(root/'profile/DevToolsActivePort').read_text().splitlines()[0];break
            except (OSError,IndexError):time.sleep(.1)
        else:raise RuntimeError('Chrome did not start')
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list') as response:target=next(t for t in json.load(response) if t['type']=='page')
        dev=DevTools(target['webSocketDebuggerUrl']);dev.call('Page.enable');dev.call('Network.enable')
        dev.call('Network.setBlockedURLs',{'urls':['*fonts.googleapis.com*','*fonts.gstatic.com*']})
        base=f'http://127.0.0.1:{server.server_port}'
        def cookie():dev.call('Network.setCookie',{'name':'session','value':fixture.client.get_cookie('session').value,'url':base})
        cookie();dev.call('Page.addScriptToEvaluateOnNewDocument',{'source':"window.browserErrors=[];addEventListener('error',e=>browserErrors.push(e.message));"})
        def evaluate(expression):
            result=dev.call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
            if result.get('exceptionDetails'):raise RuntimeError(result['exceptionDetails'])
            return result.get('result',{}).get('value')
        def wait(expression):
            for _ in range(150):
                if evaluate(expression):return
                time.sleep(.1)
            raise RuntimeError('Browser condition failed: '+expression+' '+str(evaluate('document.body.innerText.slice(-700)')))
        def navigate(path):
            evaluate('window.oldDesignerDocument=true');dev.call('Page.navigate',{'url':base+path})
            wait("!window.oldDesignerDocument && document.readyState==='complete'")
        def screenshot(name):
            evaluate('Promise.all(document.getAnimations().map(animation=>animation.finished))')
            image=dev.call('Page.captureScreenshot',{'format':'png'});(root/name).write_bytes(base64.b64decode(image['data']))
        for width in (1440,820,390,320):
            dev.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':width<600})
            for bid,state in scenes:
                navigate(f'/provider/briefs/{bid}/review')
                wait("!!document.querySelector('.designer-summary')")
                if evaluate('document.documentElement.scrollWidth>innerWidth+1'):raise RuntimeError('Designer page overflows')
                if evaluate('browserErrors.length'):raise RuntimeError(evaluate('browserErrors'))
                if not evaluate("Number(document.querySelector('.designer-summary progress').value)===100"):raise RuntimeError('Verification warning changed required completeness')
                screenshot(f'designer-{width}-{state}.png')
                evaluate("document.querySelector('[data-expand-sections=open]').click()")
                if not evaluate("[...document.querySelectorAll('.designer-current-sections > details')].every(section=>section.open)"):raise RuntimeError('Expand all failed')
                if evaluate("['META01','META02','PF02','EV01','posters_flyers','Hidden ministry answer'].some(text=>document.body.innerText.includes(text))"):raise RuntimeError('Internal codes or hidden answers exposed')
                if state!='verification':
                    if not evaluate("document.querySelector('.designer-swatches').children.length===4 && document.body.innerText.includes('KES 1,000.00') && document.body.innerText.includes('10 May 2027')"):raise RuntimeError('Typed answer display failed')
                    evaluate("document.querySelector('.designer-image-preview').scrollIntoView({block:'center',behavior:'instant'})")
                    wait("document.querySelector('.designer-image-preview').naturalWidth>0")
                if evaluate('document.documentElement.scrollWidth>innerWidth+1'):raise RuntimeError('Expanded answer content overflows')
                evaluate("document.querySelector('[data-expand-sections=close]').click()")
                if not evaluate("[...document.querySelectorAll('.designer-current-sections > details')].every(section=>!section.open)"):raise RuntimeError('Collapse all failed')
                if state=='clarification':
                    if not evaluate("document.querySelector('.designer-attention strong').textContent==='1' && document.querySelector('button[value=approved]').disabled && document.body.innerText.includes('Contact destinations')"):raise RuntimeError('Contact warning or approval eligibility lost')
                    evaluate("document.querySelector('[data-reveal-answer]').click()")
                    if not evaluate("document.activeElement.classList.contains('designer-answer') && document.activeElement.closest('details').open"):raise RuntimeError('Related-answer warning link failed')
                    evaluate("document.querySelector('.designer-verification').scrollIntoView({block:'start',behavior:'instant'})")
                    screenshot(f'verification-{width}.png')
                if state=='verification':
                    if not evaluate("document.querySelector('button[value=approved]').disabled"):raise RuntimeError('Unverified claims can approve in UI')
                    evaluate("document.querySelector('[name=verified]').click()")
                    if not evaluate("!document.querySelector('button[value=approved]').disabled"):raise RuntimeError('Human verification did not enable the existing action')
                evaluate("document.querySelector('.designer-current-sections summary').focus()")
                dev.call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'text':'\r'})
                dev.call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Enter','code':'Enter','windowsVirtualKeyCode':13})
                if not evaluate("document.querySelector('.designer-current-sections details').open && getComputedStyle(document.activeElement).outlineStyle!=='none'"):raise RuntimeError('Native accordion keyboard/focus failed')
                print(f'Designer {width}px {state}: passed',flush=True)
            navigate(f'/provider/briefs/{legacy}/review')
            if evaluate('document.documentElement.scrollWidth>innerWidth+1'):raise RuntimeError('Legacy review overflows')
            evaluate("document.querySelector('[data-expand-sections=close]').click()")
            if not evaluate("!document.querySelector('.designer-legacy-responses').open"):raise RuntimeError('Legacy disclosure control failed')
            screenshot(f'legacy-{width}.png');print(f'Legacy {width}px: passed',flush=True)
        ready,warning,human=scenes[0][0],scenes[1][0],scenes[2][0]
        navigate(f'/provider/briefs/{warning}/review')
        evaluate("document.querySelector('#provider-comment').value='Please confirm the website destination.';document.querySelector('button[value=revision_requested]').click()")
        wait("document.querySelector('#designer-decision-dialog').open")
        if fixture.db.execute('SELECT status FROM project_briefs WHERE id=?',(warning,)).fetchone()[0]!='submitted':raise RuntimeError('Opening confirmation changed status')
        evaluate("document.querySelector('[data-cancel-decision]').click()")
        wait("!document.querySelector('#designer-decision-dialog').open && document.activeElement.value==='revision_requested'")
        evaluate("document.querySelector('button[value=revision_requested]').click();window.oldDesignerDocument=true;document.querySelector('[data-confirm-decision]').click()")
        wait("!window.oldDesignerDocument && document.readyState==='complete'")
        if fixture.db.execute('SELECT status FROM project_briefs WHERE id=?',(warning,)).fetchone()[0]!='revision_requested':raise RuntimeError('Revision request failed')
        fixture.login(1);generation=fixture.db.execute('SELECT generation FROM adaptive_drafts WHERE brief_id=?',(warning,)).fetchone()[0]
        fixture.save(warning,{'PF06B':'Private draft revision not submitted'},generation,'Private response not submitted')
        navigate(f'/provider/briefs/{warning}/review')
        if evaluate("document.body.innerText.includes('Private draft revision not submitted') || document.body.innerText.includes('Private response not submitted')"):raise RuntimeError('Pending draft leaked to provider')
        if not evaluate("!!document.querySelector('.designer-history-version') && !document.querySelector('.designer-decision-form')"):raise RuntimeError('History or closed-state review actions incorrect')
        navigate(f'/provider/briefs/{ready}/review')
        evaluate("document.querySelector('#provider-comment').value='Reviewed and ready for design.';document.querySelector('button[value=approved]').click();window.oldDesignerDocument=true;document.querySelector('[data-confirm-decision]').click()")
        wait("!window.oldDesignerDocument && document.readyState==='complete'")
        if fixture.db.execute('SELECT status FROM project_briefs WHERE id=?',(ready,)).fetchone()[0]!='approved':raise RuntimeError('Approval failed')
        navigate(f'/provider/briefs/{human}/review')
        evaluate("document.querySelector('[name=verified]').click();document.querySelector('button[value=approved]').click();window.oldDesignerDocument=true;document.querySelector('[data-confirm-decision]').click()")
        wait("!window.oldDesignerDocument && document.readyState==='complete'")
        if fixture.db.execute('SELECT status FROM project_briefs WHERE id=?',(human,)).fetchone()[0]!='approved':raise RuntimeError('Verified-content approval failed')
        navigate(f'/provider/briefs/{legacy}/review')
        evaluate("document.querySelector('#approval-comment').value='Legacy requirements reviewed.';document.querySelector('button[value=approve]').click();window.oldDesignerDocument=true;document.querySelector('[data-confirm-decision]').click()")
        wait("!window.oldDesignerDocument && document.readyState==='complete'")
        if fixture.db.execute('SELECT status FROM project_briefs WHERE id=?',(legacy,)).fetchone()[0]!='approved':raise RuntimeError('Legacy approval action failed')
        fixture.login(4);cookie();navigate(f'/provider/briefs/{ready}/review')
        if evaluate("!!document.querySelector('.designer-header') || document.body.innerText.includes('A graduation to remember')"):raise RuntimeError('Other provider accessed an assigned brief')
        if evaluate("fetch('/brief-assets/"+str(image_id)+"?preview=1').then(response=>response.status)")!=404:raise RuntimeError('Other provider accessed preview')
        fixture.login(2);cookie();navigate(f'/provider/briefs/{ready}/review')
        dev.call('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
        if evaluate("getComputedStyle(document.querySelector('.designer-expand-controls button')).transitionDuration")!='0s':raise RuntimeError('Reduced motion ignored')
        print('Confirmation, revision/approval, human verification, legacy actions, draft privacy and authorisation: passed',flush=True)
        print('Screenshots:',root)
    finally:
        if dev:dev.socket.close()
        if process:process.terminate();process.wait(timeout=10)
        server.shutdown();server.server_close();fixture.tearDown();Integration.tearDownClass()

if __name__=='__main__':main()
