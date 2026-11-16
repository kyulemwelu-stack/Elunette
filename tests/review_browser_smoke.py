"""Real Chrome checks for editorial review and exact-question edit links."""
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
    if not Path(chrome).is_file():raise SystemExit('Set CHROME_EXECUTABLE to run browser tests.')
    Integration.setUpClass();fixture=Integration();fixture.setUp()
    server=make_server('127.0.0.1',0,fixture.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    root=Path(tempfile.mkdtemp(prefix='elunette-review-browser-'));process=None;dev=None
    try:
        catalog=engine.load_catalog()
        notice=engine.fields_for(engine.sections(catalog,'posters_flyers'))['EV09A']['options'][0]['value']
        bids=[];full_answers=None
        for incomplete in (True,False):
            bid=fixture.new('posters_flyers')
            upload=fixture.client.post(f'/client/briefs/{bid}/adaptive/assets',data={'csrf_token':fixture.token,'file':(io.BytesIO(b'Approved creative reference'),'graduation-reference.txt')})
            answers=complete('posters_flyers',{'META01':'A graduation to remember','PF02A':'celebrations','PF02J':'graduation','PF02C':'yes','EV09A':[notice],
                  'PF12A':'palette','PF12B':'warm_elegant','PF10A':'yes','PF10C':upload.json['id'],
                  'PF17A':'range','PF17B':{'amount':'1000.00','currency':'KES'},'PF17C':{'amount':'5000.00','currency':'KES'}})
            full_answers=dict(answers)
            if incomplete:
                for key in ('PF06B','EV09B','PF11E','PF13A'):answers.pop(key,None)
            saved=fixture.save(bid,answers);fixture.assertEqual(saved.status_code,200)
            bids.append((bid,saved.json['assessment']['percentage']))
        process=subprocess.Popen([chrome,'--headless','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-extensions','--remote-debugging-port=0',f'--user-data-dir={root / "profile"}','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:port=(root/'profile/DevToolsActivePort').read_text().splitlines()[0];break
            except (OSError,IndexError):time.sleep(.1)
        else:raise RuntimeError('Chrome did not start')
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list') as response:target=next(t for t in json.load(response) if t['type']=='page')
        dev=DevTools(target['webSocketDebuggerUrl']);dev.call('Page.enable');dev.call('Network.enable')
        dev.call('Network.setBlockedURLs',{'urls':['*fonts.googleapis.com*','*fonts.gstatic.com*']})
        base=f'http://127.0.0.1:{server.server_port}'
        dev.call('Network.setCookie',{'name':'session','value':fixture.client.get_cookie('session').value,'url':base})
        dev.call('Page.addScriptToEvaluateOnNewDocument',{'source':"window.browserErrors=[];addEventListener('error',e=>browserErrors.push(e.message));"})
        def evaluate(expression):
            result=dev.call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
            if result.get('exceptionDetails'):raise RuntimeError(result['exceptionDetails'])
            return result.get('result',{}).get('value')
        def wait(expression):
            for _ in range(150):
                if evaluate(expression):return
                time.sleep(.1)
            raise RuntimeError('Browser condition failed: '+expression+' '+str(evaluate('document.body.innerText.slice(-800)')))
        def navigate(path):
            evaluate('window.oldReviewDocument=true')
            dev.call('Page.navigate',{'url':base+path})
            wait("!window.oldReviewDocument && document.readyState==='complete'")
        def screenshot(name):
            evaluate("Promise.all(document.getAnimations().map(animation=>animation.finished))")
            image=dev.call('Page.captureScreenshot',{'format':'png'});(root/name).write_bytes(base64.b64decode(image['data']))
        for width in (1440,820,390,320):
            dev.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':width<600})
            for index,(bid,percentage) in enumerate(bids):
                navigate(f'/client/briefs/{bid}/adaptive/review')
                wait("!!document.querySelector('.review-completion')")
                if evaluate('document.documentElement.scrollWidth>innerWidth+1'):raise RuntimeError('Review overflows horizontally')
                if evaluate('browserErrors.length'):raise RuntimeError(evaluate('browserErrors'))
                if evaluate("Number(document.querySelector('.review-progress').value)")!=percentage:raise RuntimeError('Review progress differs from validated required fields')
                if index==0:
                    if not evaluate("document.querySelectorAll('.review-missing-card').length===4 && document.querySelector('.review-submit-disabled').disabled"):raise RuntimeError('Missing cards/submission gate incorrect')
                else:
                    if not evaluate("document.querySelector('.review-submit-form button').disabled===true && !document.querySelector('[name=confirm]').checked && document.querySelectorAll('.review-missing-card').length===0"):raise RuntimeError('Completed review is not ready')
                screenshot(f'review-{width}-'+('incomplete.png' if index==0 else 'complete.png'))
                evaluate("document.querySelector('.final-submission-card').scrollIntoView({block:'start',behavior:'instant'})")
                screenshot(f'submission-card-{width}-'+('incomplete.png' if index==0 else 'unchecked.png'))
                if index==1:
                    evaluate("document.querySelector('label[for=review-confirm-submit]').click()")
                    if not evaluate("document.querySelector('[name=confirm]').checked && !document.querySelector('#review-submit').disabled"):raise RuntimeError('Confirmation label did not enable submission')
                    screenshot(f'submission-card-{width}-checked.png')
                    evaluate("document.querySelector('[name=confirm]').focus()")
                    dev.call('Input.dispatchKeyEvent',{'type':'keyDown','key':' ','code':'Space','windowsVirtualKeyCode':32,'text':' '})
                    dev.call('Input.dispatchKeyEvent',{'type':'keyUp','key':' ','code':'Space','windowsVirtualKeyCode':32})
                    if not evaluate("!document.querySelector('[name=confirm]').checked && document.querySelector('#review-submit').disabled && getComputedStyle(document.activeElement).outlineStyle!=='none'"):raise RuntimeError('Keyboard confirmation toggle failed')
                evaluate("document.querySelectorAll('.review-answer-details').forEach(section=>section.open=true)")
                if evaluate('document.documentElement.scrollWidth>innerWidth+1'):raise RuntimeError('Expanded answers overflow horizontally')
                if not evaluate("document.querySelector('.review-palette .swatches').children.length===4 && document.querySelector('.review-attachment').textContent.includes('graduation-reference.txt')"):raise RuntimeError('Swatches or file references missing')
                if not evaluate("document.querySelector('.review-answer-list').parentElement.parentElement.open && document.body.innerText.includes('KES 1,000.00') && document.body.innerText.includes('10 May 2027')"):raise RuntimeError('Human-readable values missing')
                permission=evaluate("fetch(document.querySelector('.review-attachment').href).then(response=>response.ok && response.headers.get('Content-Disposition').includes('attachment'))")
                if not permission:raise RuntimeError('Safe attachment download failed')
                evaluate("document.querySelector('.review-answer-details summary').focus()")
                dev.call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'text':'\r'})
                dev.call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Enter','code':'Enter','windowsVirtualKeyCode':13})
                if not evaluate("!document.querySelector('.review-answer-details').open && getComputedStyle(document.activeElement).outlineStyle!=='none'"):raise RuntimeError('Collapsible section keyboard/focus failed')
                if fixture.db.execute('SELECT COUNT(*) FROM adaptive_submissions WHERE brief_id=?',(bid,)).fetchone()[0]!=0:raise RuntimeError('Opening review submitted a brief')
                print(f'Review {width}px '+('incomplete' if index==0 else 'complete')+': passed',flush=True)
        def completed_case():
            created=fixture.new('logo_branding');fixture.save(created,complete('logo_branding'))
            navigate(f'/client/briefs/{created}/adaptive/review')
            wait("!!document.querySelector('#review-submit') && !!document.querySelector('script[src$=\"adaptive-submit.js\"]')")
            evaluate("document.querySelector('label[for=review-confirm-submit]').click()")
            return created
        pending=fixture.new('logo_branding');fixture.save(pending,complete('logo_branding'))
        navigate(f'/client/briefs/{pending}/adaptive?question=CORE02A&return_to=review')
        wait("!!document.querySelector('#adaptive-form') && document.querySelector('#section-select')?.options.length>0")
        reference=root/'pending-reference.txt';reference.write_text('Approved reference to retain before review',encoding='utf-8')
        evaluate("document.querySelector('#CORE02A').value='yes';document.querySelector('#CORE02A').dispatchEvent(new Event('change',{bubbles:true}));window.originalUploadFetch=window.fetch;window.fetch=async(url,options)=>{if(String(url).endsWith('/adaptive/assets')) await new Promise(resolve=>window.finishPendingUpload=resolve);return originalUploadFetch(url,options);};")
        document=dev.call('DOM.getDocument')['root']['nodeId']
        file_input=dev.call('DOM.querySelector',{'nodeId':document,'selector':'#CORE02B-upload'})['nodeId']
        dev.call('DOM.setFileInputFiles',{'nodeId':file_input,'files':[str(reference)]})
        wait("typeof finishPendingUpload==='function'")
        evaluate("document.querySelector('#review').click()")
        if not evaluate("location.pathname.endsWith('/adaptive') && document.querySelector('#save-status').textContent.includes('Finishing your uploads')"):raise RuntimeError('Review discarded an in-flight upload')
        evaluate("window.oldReviewDocument=true;finishPendingUpload()")
        wait("!window.oldReviewDocument && document.readyState==='complete' && !!document.querySelector('.review-completion')")
        if not evaluate("document.querySelector('.review-attachment').textContent.includes('pending-reference.txt')"):raise RuntimeError('Pending upload was not saved before review')
        print('Unsaved upload is completed and persisted before review: passed',flush=True)
        # A slow request and a lost response after the commit must not produce
        # duplicate snapshots, and no success is shown before persistence.
        case=completed_case()
        evaluate("window.realFetch=window.fetch;window.submitCalls=0;window.fetch=async(url,options)=>{if(String(url).endsWith('/adaptive/submit')){submitCalls++;await new Promise(resolve=>window.releaseSubmission=resolve);await realFetch(url,options);throw new TypeError('Simulated lost submission response');}return realFetch(url,options);};document.querySelector('#review-submit').click();document.querySelector('#review-submit').click();")
        wait("submitCalls===1 && typeof releaseSubmission==='function'")
        if not evaluate("document.querySelector('#review-submit').disabled && document.querySelector('[data-submit-label]').textContent==='Submitting...'"):raise RuntimeError('Submitting state/repeated click guard failed')
        if fixture.db.execute('SELECT COUNT(*) FROM adaptive_submissions WHERE brief_id=?',(case,)).fetchone()[0]!=0:raise RuntimeError('Submission reported before commit')
        evaluate("window.oldReviewDocument=true;releaseSubmission()")
        wait("!window.oldReviewDocument && document.readyState==='complete' && !!document.querySelector('.submission-success-card')")
        if fixture.db.execute('SELECT COUNT(*) FROM adaptive_submissions WHERE brief_id=?',(case,)).fetchone()[0]!=1:raise RuntimeError('Lost response created duplicate submissions')
        case=completed_case()
        evaluate("window.realFetch=window.fetch;window.failOnce=true;window.fetch=async(url,options)=>{if(String(url).endsWith('/adaptive/submit') && failOnce){failOnce=false;return new Response(JSON.stringify({code:'submission_unavailable'}),{status:503,headers:{'Content-Type':'application/json'}});}return realFetch(url,options);};document.querySelector('#review-submit').click();")
        wait("!document.querySelector('.submission-error').hidden")
        if not evaluate("document.querySelector('[name=confirm]').checked && !document.querySelector('#review-submit').disabled"):raise RuntimeError('Retry lost the confirmation state')
        if fixture.db.execute('SELECT status FROM project_briefs WHERE id=?',(case,)).fetchone()[0]!='draft':raise RuntimeError('Failed request changed brief state')
        evaluate("window.oldReviewDocument=true;document.querySelector('#review-submit').click()")
        wait("!window.oldReviewDocument && document.readyState==='complete' && !!document.querySelector('.submission-success-card')")
        case=completed_case()
        import time as token_time
        from unittest.mock import patch
        from itsdangerous import URLSafeTimedSerializer
        with fixture.client.session_transaction() as session:raw=session['csrf_token']
        with patch('itsdangerous.timed.time.time',return_value=token_time.time()-3601):expired=URLSafeTimedSerializer(fixture.app.secret_key,salt='wtf-csrf-token').dumps(raw)
        evaluate("window.realFetch=window.fetch;window.expired="+json.dumps(expired)+";window.expireOnce=true;window.fetch=async(url,options)=>{if(String(url).endsWith('/adaptive/submit') && expireOnce){expireOnce=false;options.body.set('csrf_token',expired);options.headers['X-CSRFToken']=expired;}return realFetch(url,options);};window.oldReviewDocument=true;document.querySelector('#review-submit').click();")
        wait("!window.oldReviewDocument && document.readyState==='complete' && !!document.querySelector('.submission-success-card')")
        if fixture.db.execute('SELECT COUNT(*) FROM adaptive_submissions WHERE brief_id=?',(case,)).fetchone()[0]!=1:raise RuntimeError('Expired CSRF retry failed')
        case=completed_case()
        dev.call('Network.deleteCookies',{'name':'session','url':base})
        evaluate("document.querySelector('#review-submit').click()")
        wait("!document.querySelector('.submission-sign-in').hidden")
        if not evaluate("document.querySelector('[name=confirm]').checked"):raise RuntimeError('Expired session lost confirmation')
        if fixture.db.execute('SELECT status FROM project_briefs WHERE id=?',(case,)).fetchone()[0]!='draft':raise RuntimeError('Expired session submitted without authentication')
        fixture.login(1)
        dev.call('Network.setCookie',{'name':'session','value':fixture.client.get_cookie('session').value,'url':base})
        evaluate("window.oldReviewDocument=true;document.querySelector('#review-submit').click()")
        wait("!window.oldReviewDocument && document.readyState==='complete' && !!document.querySelector('.submission-success-card')")
        case=completed_case()
        fixture.save(case,{'LB01':'Newer brand name from another tab'},1)
        evaluate("document.querySelector('#review-submit').click()")
        wait("!document.querySelector('.submission-latest-review').hidden")
        if not evaluate("document.querySelector('#review-submit').disabled"):raise RuntimeError('Stale review remains submittable')
        if fixture.db.execute('SELECT COUNT(*) FROM adaptive_submissions WHERE brief_id=?',(case,)).fetchone()[0]!=0:raise RuntimeError('Stale review submitted newer unseen answers')
        print('Submission retries, session/CSRF recovery, double clicks, lost responses and stale review protection: passed',flush=True)
        bid=bids[0][0]
        navigate(f'/client/briefs/{bid}/adaptive/review')
        for key in ('PF06B','EV09B','PF11E','PF13A'):
            evaluate("window.oldReviewDocument=true;document.querySelector('[data-review-field="+key+"]').click()")
            wait("!window.oldReviewDocument && document.readyState==='complete' && !!document.querySelector('#adaptive-form') && document.activeElement.closest('[data-field]')?.dataset.field==="+json.dumps(key))
            if evaluate("document.querySelector('#section-select').value")!=next(g['id'] for g in engine.sections(catalog,'posters_flyers') if any(f['id']==key for f in g['fields'])):raise RuntimeError('Missing card opened wrong section')
            if key in ('PF06B','EV09B'):
                evaluate("document.getElementById("+json.dumps(key)+").value='Approved graduation details';document.getElementById("+json.dumps(key)+").dispatchEvent(new Event('input',{bubbles:true}));")
            elif key=='PF11E':
                evaluate("document.querySelector('[data-field=PF11E] [data-choice=no]').click()")
            else:
                evaluate("document.querySelector('#PF13A .add-row').click()")
                evaluate("{const row="+json.dumps(full_answers['PF13A'][0])+";for(const [key,value] of Object.entries(row)){const input=[...document.querySelectorAll('#PF13A .repeat-row [data-input]')].find(input=>input.dataset.input===key);input.value=value;input.dispatchEvent(new Event('change',{bubbles:true}));}}")
            if not evaluate("document.querySelector('#review').textContent==='Save & return to review'"):raise RuntimeError('Review return action missing')
            evaluate("window.oldReviewDocument=true;document.querySelector('#review').click()")
            wait("!window.oldReviewDocument && document.readyState==='complete' && location.pathname.endsWith('/adaptive/review')")
            if evaluate("!!document.querySelector('[data-review-field="+key+"]')"):raise RuntimeError('Saved detail still missing in review')
        if not evaluate("!!document.querySelector('.review-submit-form') && Number(document.querySelector('.review-progress').value)===100"):raise RuntimeError('Completing required details did not unlock submission')
        if evaluate("document.querySelector('[name=confirm]').checkValidity()"):raise RuntimeError('Review confirmation not required')
        evaluate("document.querySelector('[name=confirm]').click();window.oldReviewDocument=true;document.querySelector('.review-submit-form button').click()")
        wait("!window.oldReviewDocument && document.readyState==='complete' && !!document.querySelector('.submission-success-card')")
        if fixture.db.execute('SELECT status FROM project_briefs WHERE id=?',(bid,)).fetchone()[0]!='submitted':raise RuntimeError('Final confirmation did not submit')
        if evaluate("!!document.querySelector('.review-submit-form') || !!document.querySelector('.review-section-edit')"):raise RuntimeError('Submitted review remains editable')
        dev.call('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]})
        if evaluate("getComputedStyle(document.querySelector('.submission-success-card')).transitionDuration")!='0s':raise RuntimeError('Reduced motion ignored')
        screenshot('submission-success-320.png')
        dev.call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1000,'deviceScaleFactor':1,'mobile':False})
        screenshot('submission-success-1440.png')
        if not evaluate("document.querySelector('#submission-success-heading').textContent==='Your ideas are on their way.' && [...document.querySelectorAll('a')].some(link=>link.textContent.includes('Return to Studio') && ['/dashboard/client','/dashboard/client-preview'].includes(new URL(link.href).pathname))"):raise RuntimeError('Success receipt message/navigation missing')
        if not evaluate("fetch(document.querySelector('.submission-success-card > .review-primary-action').href).then(response=>response.ok)"):raise RuntimeError('Return to Studio link failed')
        # Exercise the actual provider form, client revision response and second
        # submission in the browser, rather than only changing fixture records.
        fixture.login(2)
        dev.call('Network.setCookie',{'name':'session','value':fixture.client.get_cookie('session').value,'url':base})
        navigate(f'/provider/briefs/{bid}/review')
        evaluate("document.querySelector('#provider-comment').value='Please refine the graduation headline.';window.oldReviewDocument=true;document.querySelector('button[value=revision_requested]').click()")
        wait("!window.oldReviewDocument && document.readyState==='complete'")
        if fixture.db.execute('SELECT status FROM project_briefs WHERE id=?',(bid,)).fetchone()[0]!='revision_requested':raise RuntimeError('Provider revision request failed')
        fixture.login(1)
        dev.call('Network.setCookie',{'name':'session','value':fixture.client.get_cookie('session').value,'url':base})
        navigate(f'/client/briefs/{bid}/adaptive?question=PF06B&return_to=review')
        evaluate("document.querySelector('#PF06B').value='Celebrating the next chapter';document.querySelector('#PF06B').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#revision-response').value='I refined the headline.';document.querySelector('#revision-response').dispatchEvent(new Event('input',{bubbles:true}));window.oldReviewDocument=true;document.querySelector('#review').click()")
        wait("!window.oldReviewDocument && document.readyState==='complete' && !!document.querySelector('#review-submit')")
        evaluate("document.querySelector('label[for=review-confirm-submit]').click();window.oldReviewDocument=true;document.querySelector('#review-submit').click()")
        wait("!window.oldReviewDocument && document.readyState==='complete' && !!document.querySelector('.submission-success-card')")
        if fixture.db.execute('SELECT COUNT(*) FROM adaptive_submissions WHERE brief_id=?',(bid,)).fetchone()[0]!=2:raise RuntimeError('Browser resubmission did not retain both snapshots')
        fixture.login(2)
        dev.call('Network.setCookie',{'name':'session','value':fixture.client.get_cookie('session').value,'url':base})
        navigate(f'/provider/briefs/{bid}/review')
        evaluate("window.oldReviewDocument=true;document.querySelector('button[value=approved]').click()")
        wait("!window.oldReviewDocument && document.readyState==='complete'")
        if fixture.db.execute('SELECT status FROM project_briefs WHERE id=?',(bid,)).fetchone()[0]!='approved':raise RuntimeError('Provider approval failed')
        print('Client submission -> provider review -> revision -> client resubmission -> provider approval: passed',flush=True)
        print('Exact-question links, focus, save/return, required validation, confirmation and final submission: passed',flush=True)
        print('Screenshots:',root)
    finally:
        if dev:dev.socket.close()
        if process:process.terminate();process.wait(timeout=10)
        server.shutdown();server.server_close();fixture.tearDown();Integration.tearDownClass()

if __name__=='__main__':main()
