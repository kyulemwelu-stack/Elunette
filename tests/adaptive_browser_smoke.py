"""Real Chrome smoke checks against temporary SQLite records, including autosave."""
import base64
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
from test_adaptive import Integration, complete
from questionnaire_engine import load_catalog, services
from browser_smoke import DevTools
from werkzeug.serving import make_server


def main():
    chrome=os.environ.get('CHROME_EXECUTABLE','C:/Program Files/Google/Chrome/Application/chrome.exe')
    if not Path(chrome).is_file(): raise SystemExit('Set CHROME_EXECUTABLE to run browser tests.')
    fixture=Integration(); Integration.setUpClass(); fixture.setUp()
    server=make_server('127.0.0.1',0,fixture.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    root=Path(tempfile.mkdtemp(prefix='elunette-adaptive-browser-'))
    process=None; dev=None
    try:
        bid=fixture.new('posters_flyers'); cookie=fixture.client.get_cookie('session').value
        qid=fixture.db.execute("INSERT INTO questionnaires(title,description,created_by,status) VALUES ('Provider custom brief','Custom',2,'active')").lastrowid
        vid=fixture.db.execute('INSERT INTO questionnaire_versions(questionnaire_id) VALUES (?)',(qid,)).lastrowid
        fixture.db.execute('INSERT INTO questionnaire_publications(questionnaire_id,questionnaire_version_id,title_snapshot,description_snapshot) VALUES (?,?,?,?)',(qid,vid,'Provider custom brief','Custom'))
        fixture.db.commit()
        process=subprocess.Popen([chrome,'--headless','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-extensions','--remote-debugging-port=0',f'--user-data-dir={root / "profile"}','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                port=(root/'profile/DevToolsActivePort').read_text().splitlines()[0];break
            except (OSError,IndexError): time.sleep(.1)
        else: raise RuntimeError('Chrome did not start')
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list') as response: target=next(t for t in json.load(response) if t['type']=='page')
        dev=DevTools(target['webSocketDebuggerUrl']); dev.call('Page.enable'); dev.call('Network.enable'); dev.call('Network.setBlockedURLs',{'urls':['*fonts.googleapis.com*','*fonts.gstatic.com*']})
        dev.call('Network.setCookie',{'name':'session','value':cookie,'url':f'http://127.0.0.1:{server.server_port}'})
        dev.call('Page.addScriptToEvaluateOnNewDocument',{'source':"window.browserErrors=[];addEventListener('error',e=>browserErrors.push(e.message));"})
        def evaluate(expression):
            result=dev.call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
            if result.get('exceptionDetails'): raise RuntimeError(result['exceptionDetails'])
            return result.get('result',{}).get('value')
        def wait(expression):
            for _ in range(100):
                if evaluate(expression): return
                time.sleep(.1)
            raise RuntimeError('Browser condition failed: '+expression+' '+str(evaluate("JSON.stringify({ready:document.readyState,errors:window.browserErrors,form:!!document.querySelector('#adaptive-form'),script:document.querySelector('script[src]')?.outerHTML,data:document.querySelector('#adaptive-data')?.textContent.slice(0,100),nav:document.querySelector('#section-nav')?.innerHTML,sections:document.querySelectorAll('[data-section]').length,text:document.body.innerText.slice(-200)})")))
        for width in (1440,820,390,320):
            dev.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':960,'deviceScaleFactor':1,'mobile':width<600})
            dev.call('Page.navigate',{'url':f'http://127.0.0.1:{server.server_port}/briefs/new'})
            wait("document.readyState==='complete' && !!document.querySelector('#new-project-form')")
            if evaluate('document.documentElement.scrollWidth>innerWidth+1'): raise RuntimeError('Create brief horizontal overflow')
            if not evaluate("document.querySelectorAll('.new-brief-form').length===1 && !document.querySelector('.new-brief-intro').textContent.includes('Start a guided brief') && document.querySelectorAll('#questionnaire optgroup[label=\"Design services\"] option').length===7"): raise RuntimeError('Create brief structure changed')
            evaluate("document.querySelector('#provider').value='2';document.querySelector('#provider').dispatchEvent(new Event('change',{bubbles:true}));")
            wait("document.querySelector('#provider-questionnaires').children.length===1")
            evaluate("document.querySelector('.new-brief-section').scrollIntoView()")
            image=dev.call('Page.captureScreenshot',{'format':'png'});(root/f'create-brief-{width}.png').write_bytes(base64.b64decode(image['data']))
            print(f'Create brief {width}px: passed',flush=True)
            dev.call('Page.navigate',{'url':f'http://127.0.0.1:{server.server_port}/client/briefs/{bid}/adaptive'})
            wait("document.readyState==='complete' && document.querySelector('#section-select')?.options.length>0")
            if evaluate('document.documentElement.scrollWidth>innerWidth+1'): raise RuntimeError('Horizontal page overflow')
            if evaluate('browserErrors.length'): raise RuntimeError(evaluate('browserErrors'))
            if not evaluate("document.querySelector('#META01').value==='Project'"): raise RuntimeError('Draft not restored')
            evaluate("Promise.all(document.getAnimations().map(animation=>animation.finished))")
            image=dev.call('Page.captureScreenshot',{'format':'png'});(root/f'consultation-{width}.png').write_bytes(base64.b64decode(image['data']))
            if not evaluate("document.querySelector('#completion').getBoundingClientRect().height===4 && document.querySelectorAll('#section-nav button').length===0"): raise RuntimeError('Progress/navigation design regressed')
            if evaluate("document.body.innerText.includes('Subtype fields depend')"): raise RuntimeError('Technical notes exposed')
            evaluate("document.querySelector('#next').click();document.querySelector('[data-field=PF01A] [data-choice=both]').click();")
            if not evaluate("document.querySelector('#PF01A').value==='both' && document.querySelector('#section-select option[value=META]').dataset.state==='complete'"): raise RuntimeError('Option card or completed section state failed')
            if not evaluate("!document.querySelector('[data-field=PF01B]').hidden"): raise RuntimeError('Conditional follow-up missing')
            evaluate("document.querySelector('#PF01B').value='different';document.querySelector('#PF01B').dispatchEvent(new Event('change',{bubbles:true}));")
            if not evaluate("!document.querySelector('[data-field=PF_CONTENT_VARIANTS]').hidden"): raise RuntimeError('Deliverable variants missing')
            evaluate("{const nav=document.querySelector('#section-select');nav.value='PF12';nav.dispatchEvent(new Event('change'));} document.querySelector('#PF12A').value='palette';document.querySelector('#PF12A').dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('[data-palette=bold_energetic]').click();")
            if not evaluate("document.querySelector('#PF12B').value==='bold_energetic'"): raise RuntimeError('Palette selection failed')
            evaluate("document.querySelector('#PF12A').value='custom';document.querySelector('#PF12A').dispatchEvent(new Event('change',{bubbles:true}));if (!document.querySelector('#PF12C [data-hex]')) document.querySelector('#PF12C .add-colour').click();")
            if not evaluate("document.querySelector('#PF12C [data-hex]').value==='#653D30'"): raise RuntimeError('Colour picker failed')
            evaluate("{const nav=document.querySelector('#section-select');nav.value='PF13';nav.dispatchEvent(new Event('change'));}document.querySelector('#PF13A .add-row').click();")
            if not evaluate("document.querySelectorAll('#PF13A .repeat-row').length>0"): raise RuntimeError('Repeater failed')
            evaluate("document.querySelector('#save').click()")
            wait("document.querySelector('#save-status').textContent.startsWith('Draft saved.')")
            if evaluate('browserErrors.length'): raise RuntimeError(evaluate('browserErrors'))
            if not evaluate("document.querySelector('.wizard-section:not([hidden])').getBoundingClientRect().bottom <= document.querySelector('.wizard-footer').getBoundingClientRect().top"): raise RuntimeError('Navigation overlaps questionnaire content')
            evaluate("document.querySelector('#back').focus()")
            dev.call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
            dev.call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
            if not evaluate("document.activeElement.id==='save' && getComputedStyle(document.activeElement).outlineStyle!=='none'"): raise RuntimeError('Keyboard focus is not visible')
            image=dev.call('Page.captureScreenshot',{'format':'png'});(root/f'wizard-{width}.png').write_bytes(base64.b64decode(image['data']))
            print(f'Wizard {width}px: passed',flush=True)
            evaluate("{const nav=document.querySelector('#section-select');nav.value='PF12';nav.dispatchEvent(new Event('change'));} document.querySelector('#PF12A').value='palette';document.querySelector('#PF12A').dispatchEvent(new Event('change',{bubbles:true}));")
            if not evaluate("document.querySelector('#PF12B').value==='bold_energetic' && document.querySelector('[data-palette=bold_energetic]').getAttribute('aria-pressed')==='true'"): raise RuntimeError('Hidden palette answer not retained')
            evaluate("Promise.all(document.getAnimations().map(animation=>animation.finished));")
            evaluate("document.querySelector('[data-section=PF12]').scrollIntoView({block:'start',behavior:'instant'})")
            image=dev.call('Page.captureScreenshot',{'format':'png'});(root/f'palettes-{width}.png').write_bytes(base64.b64decode(image['data']))
            evaluate("document.querySelector('#save').click()")
            wait("document.querySelector('#save-status').textContent.startsWith('Draft saved.')")
        reference=root/'reference.txt'; reference.write_text('Approved questionnaire reference',encoding='utf-8')
        invalid=root/'invalid.txt'; invalid.write_text('<html>Invalid reference</html>',encoding='utf-8')
        evaluate("{const nav=document.querySelector('#section-select');nav.value='PF07';nav.dispatchEvent(new Event('change'));}document.querySelector('#PF07A').value='ready';document.querySelector('#PF07A').dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#PF07B').value='upload';document.querySelector('#PF07B').dispatchEvent(new Event('change',{bubbles:true}));")
        node=dev.call('DOM.getDocument')['root']['nodeId']
        upload=dev.call('DOM.querySelector',{'nodeId':node,'selector':'#PF07D-upload'})['nodeId']
        dev.call('DOM.setFileInputFiles',{'nodeId':upload,'files':[str(invalid)]})
        wait("document.querySelector('[data-field=PF07D] .upload-status').textContent.startsWith('Choose a valid PDF')")
        wait("document.querySelector('#PF07D-upload').value === ''")
        dev.call('DOM.setFileInputFiles',{'nodeId':upload,'files':[str(reference)]})
        wait("document.querySelector('[data-field=PF07D] .upload-status').textContent.startsWith('Uploaded ')")
        if not evaluate("Number(document.querySelector('#PF07D').value)>0"): raise RuntimeError('Uploaded file not attached to its question')
        evaluate("""{
          const choose=(key,value)=>{
            const input=document.getElementById(key);
            input.value=value;
            input.dispatchEvent(new Event('change',{bubbles:true}));
          };
          choose('PF02A','celebrations');
          choose('PF02J','graduation');
          choose('PF02C','no');
        }""")
        if not evaluate("!document.querySelector('#event-details-hint').hidden && document.querySelector('[data-field=EV01A]').hidden"):
            raise RuntimeError('Event subtype with no event details needs a non-blocking hint')
        evaluate("""{
          document.querySelector('#PF02C').value='yes';
          document.querySelector('#PF02C').dispatchEvent(new Event('change',{bubbles:true}));
          document.querySelector('#EV06A').value='yes';
          document.querySelector('#EV06A').dispatchEvent(new Event('change',{bubbles:true}));
          document.querySelector('#EV06B .add-row').click();
        }""")
        if not evaluate("document.querySelector('#event-details-hint').hidden"):
            raise RuntimeError('Event hint stayed visible after the event module was enabled')
        if not evaluate("""(() => {
          const select = document.querySelector('#EV06B select[data-kind=asset_reference]');
          const upload = document.querySelector('#EV06B input[type=file]');
          return [...select.options].some(option => option.textContent === 'reference.txt') &&
            Boolean(document.getElementById(upload.getAttribute('aria-describedby')));
        })()"""): raise RuntimeError('New repeater row could not reuse an upload or lacked its format label')
        evaluate("document.querySelector('#EV06B .remove-row').click()")
        evaluate("document.querySelector('#save').click()")
        wait("document.querySelector('#save-status').textContent.startsWith('Draft saved.')")
        evaluate("document.querySelector('#PF07B').value='type';document.querySelector('#PF07B').dispatchEvent(new Event('change',{bubbles:true}));")
        if not evaluate("document.querySelector('[data-field=PF07D]').hidden && !document.querySelector('[data-field=PF07C]').hidden"): raise RuntimeError('Conditional upload branch failed')
        evaluate("document.querySelector('#PF07B').value='upload';document.querySelector('#PF07B').dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#save').click();")
        wait("document.querySelector('#save-status').textContent.startsWith('Draft saved.')")
        evaluate("window.beforeDraftReload=true")
        dev.call('Page.reload')
        wait("!window.beforeDraftReload && document.readyState==='complete' && document.querySelector('#section-select')?.options.length>0")
        if not evaluate("Number(document.querySelector('#PF07D').value)>0 && document.querySelector('#PF12B').value==='bold_energetic'"): raise RuntimeError('Uploaded asset or palette did not resume')
        dev.call('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
        if not evaluate("getComputedStyle(document.querySelector('#next')).transitionDuration==='0s'"): raise RuntimeError('Reduced motion ignored')
        print('Upload, branch retention, resumption, keyboard focus and reduced motion: passed',flush=True)
        # Exercise failures against the real Flask server without touching any
        # production database or replacing the questionnaire's DOM values.
        evaluate("window.originalFetch=window.fetch;window.saveCalls=0;window.saveInFlight=0;window.saveMaximum=0;window.holdOne=true;window.fetch=async(url,options)=>{if(String(url).endsWith('/adaptive/save')){saveCalls++;saveInFlight++;saveMaximum=Math.max(saveMaximum,saveInFlight);try{if(holdOne){holdOne=false;await new Promise(resolve=>window.releaseSave=resolve);}return await originalFetch(url,options);}finally{saveInFlight--;}}return originalFetch(url,options);};")
        evaluate("document.querySelector('#PF06B').value='First edit';document.querySelector('#PF06B').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#save').click();document.querySelector('#save').click();")
        wait("saveCalls===1 && typeof releaseSave==='function'")
        evaluate("document.querySelector('#PF06B').value='Latest edit while saving';document.querySelector('#PF06B').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#save').click();releaseSave();")
        wait("document.querySelector('#save-status').textContent.startsWith('Draft saved.')")
        if not evaluate("saveCalls===2 && saveMaximum===1"):raise RuntimeError('Duplicate or overlapping save writes')
        saved=fixture.db.execute('SELECT answers_json FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone()[0]
        if json.loads(saved)['PF06B']!='Latest edit while saving':raise RuntimeError('Edit made during saving was lost')
        evaluate("window.fetch=async(url,options)=>{if(String(url).endsWith('/adaptive/save')){saveCalls++;const response=await originalFetch(url,options);window.fetch=originalFetch;throw new TypeError('Simulated lost response after persistence');}return originalFetch(url,options);};document.querySelector('#PF06B').value='Saved despite a lost response';document.querySelector('#PF06B').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#save').click();")
        wait("document.querySelector('#save-status').textContent.startsWith('Not saved yet.')")
        persisted_generation=fixture.db.execute('SELECT generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone()[0]
        if not evaluate("document.querySelector('#PF06B').value==='Saved despite a lost response' && !document.querySelector('#save-recovery').hidden && !document.querySelector('#errors').innerText.includes('_form:')"):raise RuntimeError('Failed save lost values or exposed technical text')
        evaluate("document.querySelector('#save').click()")
        wait("document.querySelector('#save-status').textContent.startsWith('Draft saved.')")
        if fixture.db.execute('SELECT generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone()[0]!=persisted_generation:raise RuntimeError('An already persisted request was duplicated')
        import time as token_time
        from unittest.mock import patch
        from itsdangerous import URLSafeTimedSerializer
        with fixture.client.session_transaction() as session:raw=session['csrf_token']
        with patch('itsdangerous.timed.time.time',return_value=token_time.time()-3601):expired=URLSafeTimedSerializer(fixture.app.secret_key,salt='wtf-csrf-token').dumps(raw)
        evaluate("window.expiredToken="+json.dumps(expired)+";window.csrfRejections=0;window.fetch=async(url,options)=>{if(String(url).endsWith('/adaptive/save') && csrfRejections===0){csrfRejections++;options={...options,headers:{...options.headers,'X-CSRFToken':expiredToken}};}return originalFetch(url,options);};document.querySelector('#PF06B').value='Saved after expired security token';document.querySelector('#PF06B').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#save').click();")
        wait("document.querySelector('#save-status').textContent.startsWith('Draft saved.')")
        if not evaluate("csrfRejections===1 && document.querySelector('#PF06B').value==='Saved after expired security token'"):raise RuntimeError('Expired security token recovery failed')
        evaluate("window.fetch=originalFetch")
        dev.call('Network.deleteCookies',{'name':'session','url':f'http://127.0.0.1:{server.server_port}'})
        evaluate("document.querySelector('#PF06B').value='Keep this edit through sign in';document.querySelector('#PF06B').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#save').click();")
        wait("document.querySelector('#save-status').textContent.startsWith('Sign in again')")
        if not evaluate("document.querySelector('#PF06B').value==='Keep this edit through sign in' && !document.querySelector('#save-sign-in').hidden"):raise RuntimeError('Expired session did not preserve editable values')
        fixture.login(1)
        dev.call('Network.setCookie',{'name':'session','value':fixture.client.get_cookie('session').value,'url':f'http://127.0.0.1:{server.server_port}'})
        evaluate("document.querySelector('#save').click()")
        wait("document.querySelector('#save-status').textContent.startsWith('Draft saved.')")
        if json.loads(fixture.db.execute('SELECT answers_json FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone()[0])['PF06B']!='Keep this edit through sign in':raise RuntimeError('Recovered session failed to persist edits')
        completed=fixture.new('logo_branding')
        fixture.save(completed,complete('logo_branding'))
        dev.call('Page.navigate',{'url':f'http://127.0.0.1:{server.server_port}/client/briefs/{completed}/adaptive'})
        wait("document.readyState==='complete' && document.querySelector('#section-select')?.options.length>0")
        evaluate("document.querySelector('#review').click()")
        wait("document.readyState==='complete' && location.pathname.endsWith('/adaptive/review')")
        if not evaluate("document.querySelector('form[action$=\"/adaptive/submit\"] button')?.disabled===true && !document.querySelector('[name=confirm]').checked"):raise RuntimeError('Completed brief review failed')
        dev.call('Page.navigate',{'url':f'http://127.0.0.1:{server.server_port}/client/briefs/{bid}/adaptive'})
        wait("document.readyState==='complete' && document.querySelector('#section-select')?.options.length>0")
        current=fixture.db.execute('SELECT generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone()[0]
        fixture.save(bid,{'PF06B':'A different tab saved this'},current)
        evaluate("document.querySelector('#PF06B').value='My unsaved local edit';document.querySelector('#PF06B').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#save').click();")
        wait("document.querySelector('#save-status').textContent.startsWith('A newer version exists.')")
        if not evaluate("document.querySelector('#PF06B').value==='My unsaved local edit'"):raise RuntimeError('Conflict overwrote local form values')
        if json.loads(fixture.db.execute('SELECT answers_json FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone()[0])['PF06B']!='A different tab saved this':raise RuntimeError('Stale browser overwrote newer database answers')
        print('Save coalescing, in-flight edits, lost response, expired token/session, completed review and conflict protection: passed',flush=True)
        branches = {
            'posters_flyers': {'PF02C':'yes', 'EV02A':'single', 'EV03A':'fixed'},
            'logo_branding': {'LOGO_BRANDING00':'stationery', 'CORE03B':'brand'},
            'websites_applications': {'WEBSITES_APPLICATIONS00':'ecommerce', 'WA06':['store','roles','api']},
            'social_media_design': {'SOCIAL_MEDIA_DESIGN00':'carousel', 'CORE03B':'custom'},
            'events_invitations': {'EVENTS_INVITATIONS00':'wedding', 'EI07':'yes'},
            'brochures_menus': {'BROCHURES_MENUS00':'restaurant', 'BM06':'yes'},
            'packaging_design': {'PACKAGING_DESIGN00':'label', 'PK09':'yes', 'PK11':'yes'},
        }
        for service in services(load_catalog()):
            code=service['value']
            brief=fixture.new(code)
            saved=fixture.save(brief,complete(code,branches[code]))
            if saved.status_code!=200: raise RuntimeError(f'{code} fixture could not save: {saved.json}')
            for width in (1440,390,320):
                dev.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':960,'deviceScaleFactor':1,'mobile':width<600})
                dev.call('Page.navigate',{'url':f'http://127.0.0.1:{server.server_port}/client/briefs/{brief}/adaptive'})
                wait("document.readyState==='complete' && document.querySelector('#section-select')?.options.length>0")
                layout=evaluate("""(() => {
                  const nav=document.querySelector('#section-select');
                  for (const option of [...nav.options]) {
                    nav.value=option.value;
                    nav.dispatchEvent(new Event('change'));
                    const step=document.querySelector('.wizard-section:not([hidden])');
                    if (document.documentElement.scrollWidth>innerWidth+1 ||
                        step.getBoundingClientRect().bottom>document.querySelector('.wizard-footer').getBoundingClientRect().top)
                        return option.value;
                  }
                  return browserErrors.join(';');
                })()""")
                if layout: raise RuntimeError(f'{code} at {width}px: {layout}')
            else:
                if code=='posters_flyers' and not evaluate("document.querySelector('#EV02B').type==='date' && document.querySelector('#EV03B').type==='time'"): raise RuntimeError('Native date or time input missing')
                if code=='websites_applications':
                    evaluate("""{
                      const rows=document.querySelector('#WA05');
                      rows.querySelector('.add-row').click();
                      const name=rows.querySelector('.repeat-row:last-child input');
                      name.value='Updated checkout';
                      name.dispatchEvent(new Event('input',{bubbles:true}));
                      rows.querySelector('.repeat-row:first-child .remove-row').click();
                      document.querySelector('#save').click();
                    }""")
                    wait("document.querySelector('#save-status').textContent.startsWith('Draft saved.')")
                    dev.call('Page.reload')
                    wait("document.readyState==='complete' && document.querySelector('#section-select')?.options.length>0")
                    if not evaluate("document.querySelectorAll('#WA05 .repeat-row').length===1 && document.querySelector('#WA05 .repeat-row input').value==='Updated checkout'"):
                        raise RuntimeError('Repeater add, edit, remove or restore failed')
            print(f"{service['label']} active questionnaire sections at 1440px, 390px and 320px: passed",flush=True)
        print('Screenshots:',root)
    finally:
        if dev: dev.socket.close()
        if process: process.terminate();process.wait(timeout=10)
        server.shutdown();server.server_close();fixture.tearDown();Integration.tearDownClass()

if __name__=='__main__': main()
