from contextlib import closing
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
import questionnaire_engine as engine


def example(field,catalog):
    kind=field['type']
    if kind=='single_choice':
        options=field['options']
        preferred=next((o['value'] for o in options if o['value'] in ('no','none','recommend','designer','new','digital','free','quote')),None)
        return preferred or options[0]['value']
    if kind=='multi_choice': return [field['options'][0]['value']]
    if kind=='repeater': return [{f['id']:example(f,catalog) for f in field['item_fields'] if f.get('required')}]
    if kind=='money': return {'amount':'100.00','currency':'KES'}
    if kind=='date': return '2027-05-10'
    if kind=='time': return '10:00'
    if kind=='url': return 'https://example.com/brief'
    if kind=='integer': return 1
    if kind=='boolean': return False
    if kind=='color_multi_picker': return ['#123456']
    if kind=='palette_select': return catalog['palettes'][0]['id']
    if kind=='currency': return 'KES'
    if kind in ('asset_reference','file_upload'): return 1
    return 'Approved client wording'


def complete(service, overrides=None):
    catalog=engine.load_catalog(); groups=engine.sections(catalog,service)
    answers={'META01':'Test project','META02':service}; answers.update(overrides or {})
    for _ in range(20):
        active=engine.active_fields(groups,answers)
        missing={k:example(f,catalog) for k,f in active.items() if f.get('required') and k not in answers}
        if not missing: break
        answers.update(missing)
    return answers


class Engine(unittest.TestCase):
    def setUp(self): self.catalog=engine.load_catalog()

    def test_schema_integrity_all_fields_types_and_dependencies(self):
        for service in engine.services(self.catalog):
            groups=engine.sections(self.catalog,service['value']); fields=engine.fields_for(groups)
            self.assertEqual(len(fields),sum(len(g['fields']) for g in groups))
            def check(node,scope):
                if isinstance(node,dict):
                    if 'op' in node:
                        self.assertIn(node['field'],scope)
                        engine.condition(node,{})
                    if 'type' in node: self.assertIn(node['type'],engine.TYPES)
                    for key,value in node.items(): check(value,scope | {f['id'] for f in node.get('item_fields',[])})
                elif isinstance(node,list):
                    for value in node: check(value,scope)
            check(groups,set(fields))
        self.assertEqual(len(self.catalog['posters_flyers']['category_branches']),9)
        self.assertEqual(len(self.catalog['posters_flyers']['main_question_groups']),17)

    def test_condition_operators_and_missing_negative_ancestor(self):
        for op,value,expected in [('eq','x',True),('ne','y',True),('in',None,True),('not_in',None,False),('not_empty',None,True)]:
            self.assertEqual(engine.condition({'field':'a','op':op,'value':value,'values':['x']},{'a':'x'}),expected)
        self.assertTrue(engine.condition({'any':[{'field':'a','op':'contains','value':'x'}]},{'a':['x']}))
        self.assertFalse(engine.condition({'field':'absent','op':'ne','value':'yes'},{}))
        with self.assertRaises(ValueError): engine.condition({'field':'a','op':'eval'}, {})

    def test_all_seven_services_and_nine_poster_categories(self):
        scenarios=[(s['value'],{}) for s in engine.services(self.catalog)]
        scenarios += [('posters_flyers',{'PF02A':b['id'],'PF02C':'no'}) for b in self.catalog['posters_flyers']['category_branches']]
        for service,overrides in scenarios:
            with self.subTest(service=service,overrides=overrides):
                answers=complete(service,overrides); groups=engine.sections(self.catalog,service)
                result=engine.assessment(groups,answers,self.catalog,lambda asset:True)
                self.assertEqual(result['errors'],{})
                self.assertEqual(result['percentage'],100)

    def test_scripture_hidden_event_and_reversible_subtypes(self):
        groups=engine.sections(self.catalog,'posters_flyers')
        answers=complete('posters_flyers',{'PF02A':'religious_community','PF02K':'scripture','PF02C':'no','EV01A':'Hidden event','PF02D':'other'})
        active=engine.active_fields(groups,answers)
        self.assertNotIn('EV01A',active); self.assertNotIn('PF02L',active)
        self.assertNotIn('EV01A',{i['field_id'] for i in engine.snapshot(groups,answers)})
        answers['PF02C']='yes'; self.assertIn('EV01A',engine.active_fields(groups,answers))

    def test_named_acceptance_branches(self):
        cases=[('posters_flyers',{'PF02A':'religious_community','PF02K':'youth','PF02C':'yes'}),('posters_flyers',{'PF02A':'business_promotion','PF02E':'launch','BIZ04A':'yes','PF02C':'yes'}),('posters_flyers',{'PF02A':'celebrations','PF02J':'birthday','PF02C':'yes'}),('posters_flyers',{'PF02A':'recruitment','PF02I':'job','PF02C':'no'}),('brochures_menus',{'BROCHURES_MENUS00':'restaurant','BM06':'yes'}),('packaging_design',{'PACKAGING_DESIGN00':'label','PK09':'yes'})]
        for service,overrides in cases:
            with self.subTest(service=service,overrides=overrides):
                answers=complete(service,overrides)
                self.assertFalse(engine.assessment(engine.sections(self.catalog,service),answers,self.catalog,lambda asset:True)['errors'])

    def test_validation_types_repeaters_money_dates_qr_and_forgery(self):
        groups=engine.sections(self.catalog,'posters_flyers')
        for overrides,key in [({'PF01A':'forged'},'PF01A'),({'FORGED':'x'},'FORGED'),({'PF13A':[{'unknown':'bad'}]},'PF13A'),({'PF17A':'range','PF17B':{'amount':'-1','currency':'KES'}},'PF17B'),({'PF02C':'yes','EV02A':'range','EV02C':'2027-05-20','EV02D':'2027-05-10'},'EV02D'),({'PF08E':'yes','PF08F':'http://127.0.0.1'},'PF08F'),({'PF05A':['public','youth']},'PF05A')]:
            answers=complete('posters_flyers',overrides)
            self.assertIn(key,engine.assessment(groups,answers,self.catalog)['errors'])
        self.assertFalse(engine.public_url('javascript:alert(1)'))
        self.assertFalse(engine.public_url('https://user:password@example.com'))
        self.assertTrue(engine.public_url('https://example.com/action'))

    def test_hidden_incomplete_repeater_does_not_block_active_submission(self):
        answers=complete('posters_flyers',{'PF02A':'religious_community','PF02K':'scripture','PF02C':'no','EV05C':[{}]})
        result=engine.assessment(engine.sections(self.catalog,'posters_flyers'),answers,self.catalog)
        self.assertNotIn('EV05C',result['errors'])

    def test_sale_offer_contacts_currency_and_two_deliverables(self):
        groups=engine.sections(self.catalog,'posters_flyers')
        answers=complete('posters_flyers',{'PF02A':'business_promotion','PF02E':'sale','BIZ04A':'no'})
        self.assertIn('BIZ04C',engine.active_fields(groups,answers))
        answers['BIZ04C']='Save 150%'; self.assertIn('BIZ04C',engine.assessment(groups,answers,self.catalog)['errors'])
        field=engine.fields_for(groups)['PF08D']
        with self.assertRaises(ValueError): engine.normalize(field,[{'method':'email','value':'bad'}],self.catalog,partial=False)
        with self.assertRaises(ValueError): engine.normalize({'type':'money'},{'amount':'1','currency':'ZZZ'},self.catalog)
        answers=complete('posters_flyers',{'PF01A':'both','PF01B':'different'})
        self.assertIn('PF_CONTENT_VARIANTS',engine.assessment(groups,answers,self.catalog)['errors'])
        row=answers['PF_CONTENT_VARIANTS'][0]; answers['PF_CONTENT_VARIANTS']=[dict(row,deliverable='poster'),dict(row,deliverable='flyer')]
        self.assertNotIn('PF_CONTENT_VARIANTS',engine.assessment(groups,answers,self.catalog)['errors'])

    def test_required_optional_drafts_pending_and_asset_ownership(self):
        groups=engine.sections(self.catalog,'posters_flyers')
        self.assertFalse(engine.validate(groups,{'META01':'Draft'},self.catalog)[1])
        self.assertTrue(engine.assessment(groups,{},self.catalog)['errors'])
        answers=complete('posters_flyers',{'PF02C':'yes','EV02A':'pending'})
        result=engine.assessment(groups,answers,self.catalog)
        self.assertFalse(result['errors']); self.assertFalse(result['ready']); self.assertTrue(result['issues'])
        answers=complete('posters_flyers',{'PF07A':'ready','PF07B':'upload','PF07D':123})
        self.assertIn('PF07D',engine.assessment(groups,answers,self.catalog)['errors'])


class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bootstrap=tempfile.TemporaryDirectory(); old=os.environ.get('ELUNETTE_DATABASE'); os.environ['ELUNETTE_DATABASE']=str(Path(cls.bootstrap.name)/'bootstrap.db')
        from app import app
        cls.app=app
        if old is None: os.environ.pop('ELUNETTE_DATABASE',None)
        else: os.environ['ELUNETTE_DATABASE']=old
    @classmethod
    def tearDownClass(cls): cls.bootstrap.cleanup()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/'test.db'
        self.app.config.update(TESTING=True,DATABASE=str(self.path),WTF_CSRF_ENABLED=True,ADAPTIVE_UPLOAD_ROOT=str(Path(self.temp.name)/'assets'))
        self.db=sqlite3.connect(self.path); self.db.executescript(Path('schema.sql').read_text(encoding='utf-8'))
        for uid,role in [(1,'client'),(2,'service_provider'),(3,'client'),(4,'service_provider')]: self.db.execute('INSERT INTO users(id,full_name,email,password_hash,role) VALUES (?,?,?,?,?)',(uid,'User '+str(uid),str(uid)+'@example.test','unused',role))
        self.db.commit(); self.client=self.app.test_client(); self.login(1)
    def tearDown(self): self.db.close(); self.temp.cleanup()
    def login(self,uid):
        with self.client.session_transaction() as session: session.clear(); session['user_id']=uid
        self.token=re.search(r'name="csrf_token" value="([^"]+)"',self.client.get('/client/adaptive/new' if uid in (1,3) else '/provider/briefs').get_data(as_text=True)).group(1)
    def new(self,service='logo_branding'):
        response=self.client.post('/client/adaptive/new',data={'csrf_token':self.token,'META01':'Project','META02':service,'provider_id':2})
        self.assertEqual(response.status_code,302); return int(response.location.split('/')[-2])
    def save(self,bid,answers,generation=0,response=''):
        return self.client.post(f'/client/briefs/{bid}/adaptive/save',json={'answers':answers,'generation':generation,'revision_response':response},headers={'X-CSRFToken':self.token})
    def submit(self,bid,generation):
        return self.client.post(f'/client/briefs/{bid}/adaptive/submit',data={'csrf_token':self.token,'confirm':'yes','generation':generation})
    def test_expired_csrf_has_json_error_and_fresh_state_token_saves_partial_draft(self):
        import time
        from unittest.mock import patch
        from itsdangerous import URLSafeTimedSerializer
        bid=self.new('posters_flyers')
        with self.client.session_transaction() as state: raw=state['csrf_token']
        with patch('itsdangerous.timed.time.time',return_value=time.time()-3601):
            expired=URLSafeTimedSerializer(self.app.secret_key,salt='wtf-csrf-token').dumps(raw)
        payload={'generation':0,'answers':{'PF02A':'celebrations','PF02J':'graduation'},'revision_response':''}
        rejected=self.client.post(f'/client/briefs/{bid}/adaptive/save',json=payload,headers={'X-CSRFToken':expired})
        self.assertEqual(rejected.status_code,400)
        self.assertEqual(rejected.json['code'],'csrf_refresh_required')
        self.assertEqual(self.db.execute('SELECT generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone()[0],0)
        state=self.client.get(f'/client/briefs/{bid}/adaptive/save-state')
        self.assertEqual(state.status_code,200);self.assertIn('no-store',state.headers['Cache-Control'])
        response=self.client.post(f'/client/briefs/{bid}/adaptive/save',json=payload,headers={'X-CSRFToken':state.json['csrf_token']})
        self.assertEqual(response.status_code,200,response.data)
        self.assertLess(response.json['assessment']['percentage'],100)
        saved=json.loads(self.db.execute('SELECT answers_json FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone()[0])
        self.assertEqual(saved['PF02J'],'graduation')
        self.assertEqual(self.client.get(f'/client/briefs/{bid}/adaptive').status_code,200)

    def test_lost_session_and_conflicts_are_json_without_mutation(self):
        bid=self.new()
        self.assertEqual(self.save(bid,{'LB01':'Existing draft'}).status_code,200)
        before=self.db.execute('SELECT answers_json,generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone()
        stale=self.save(bid,{'LB01':'Stale attempt'},0)
        self.assertEqual(stale.status_code,409);self.assertEqual(stale.json['code'],'draft_conflict')
        with self.client.session_transaction() as state:state.clear()
        rejected=self.save(bid,{'LB01':'Lost session'},1)
        self.assertEqual(rejected.status_code,401);self.assertEqual(rejected.json['code'],'session_expired')
        self.assertEqual(self.client.get(f'/client/briefs/{bid}/adaptive/save-state').status_code,401)
        self.assertEqual(self.db.execute('SELECT answers_json,generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone(),before)
        self.login(3)
        self.assertEqual(self.client.get(f'/client/briefs/{bid}/adaptive/save-state').status_code,404)

    def test_partial_draft_defers_required_and_cross_field_checks_until_review(self):
        bid=self.new('posters_flyers')
        answers={'META01':'','PF02A':'celebrations','PF02J':'graduation','PF02C':'yes',
                 'EV02A':'range','EV02C':'2027-05-20','EV02D':'2027-05-10',
                 'PF17A':'range','PF17B':{'amount':'200','currency':'KES'},'PF17C':{'amount':'100','currency':'KES'},
                 'PF08A':'contact','PF08C':['email'],'PF08D':[{'method':'phone','value':'123'}],
                 'PF13A':[{}]}
        # Use a catalog-authorized CTA code without assuming its display label.
        answers['PF08A']=next(o['value'] for o in engine.fields_for(engine.sections(engine.load_catalog(),'posters_flyers'))['PF08A']['options'] if o['value'] not in ('none','share','other'))
        response=self.save(bid,answers)
        self.assertEqual(response.status_code,200,response.data)
        self.assertIn('META01',response.json['assessment']['errors'])
        self.assertIn('EV02D',response.json['assessment']['errors'])
        self.assertIn('PF17C',response.json['assessment']['errors'])
        self.assertIn('PF13A',response.json['assessment']['errors'])
        self.assertIn('PF08D',response.json['assessment']['errors'])
        self.assertEqual(self.db.execute('SELECT title FROM project_briefs WHERE id=?',(bid,)).fetchone()[0],'Project')
        self.assertEqual(self.client.get(f'/client/briefs/{bid}/adaptive/review').status_code,200)
        self.assertEqual(self.submit(bid,1).status_code,400)
        self.assertEqual(self.db.execute('SELECT status FROM project_briefs WHERE id=?',(bid,)).fetchone()[0],'draft')
        invalid=self.save(bid,{'PF01A':'forged'},1)
        self.assertEqual(invalid.status_code,400)
        self.assertEqual(invalid.json['code'],'validation_error')
        self.assertEqual(self.db.execute('SELECT generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone()[0],1)

    def test_database_failure_rolls_back_draft_and_returns_safe_json(self):
        bid=self.new()
        self.db.execute("CREATE TRIGGER fail_adaptive_title BEFORE UPDATE ON project_briefs BEGIN SELECT RAISE(ABORT,'simulated persistence failure'); END;")
        self.db.commit()
        before=self.db.execute('SELECT answers_json,generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone()
        with self.assertLogs(self.app.logger,level='ERROR'):
            response=self.save(bid,{'LB01':'Must roll back'})
        self.assertEqual(response.status_code,500)
        self.assertEqual(response.json['code'],'save_unavailable')
        self.assertNotIn('simulated persistence failure',response.get_data(as_text=True))
        self.assertEqual(self.db.execute('SELECT answers_json,generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone(),before)

    def test_review_missing_cards_are_dynamic_and_get_does_not_mutate(self):
        bid=self.new('posters_flyers');catalog=engine.load_catalog()
        notice=engine.fields_for(engine.sections(catalog,'posters_flyers'))['EV09A']['options'][0]['value']
        answers=complete('posters_flyers',{'PF02A':'celebrations','PF02J':'graduation','PF02C':'yes','EV09A':[notice]})
        missing=('PF06B','EV09B','PF11E','PF13A')
        for key in missing:answers.pop(key,None)
        answers['REL01']='Hidden branch answer must stay private'
        response=self.save(bid,answers)
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(set(response.json['assessment']['errors']),set(missing))
        before=self.db.execute('SELECT answers_json,generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone()
        page=self.client.get(f'/client/briefs/{bid}/adaptive/review')
        self.assertEqual(page.status_code,200)
        html=page.get_data(as_text=True)
        self.assertIn('<strong>4</strong> required',html)
        self.assertEqual(html.count('data-review-field='),4)
        for key in missing:
            self.assertIn('question='+key+'&amp;return_to=review',html)
            self.assertEqual(self.client.get(f'/client/briefs/{bid}/adaptive?question={key}&return_to=review').status_code,200)
        self.assertNotIn('This answer is required.',html)
        self.assertNotIn('Hidden branch answer must stay private',html)
        self.assertIn('Complete My Brief',html)
        self.assertIn('data-can-submit="false"',html);self.assertIn('review-submit-disabled',html)
        self.assertIn('data-can-submit="false"',html)
        self.assertEqual(self.db.execute('SELECT answers_json,generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone(),before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM adaptive_submissions WHERE brief_id=?',(bid,)).fetchone()[0],0)

    def test_complete_review_formats_assets_colours_dates_prices_and_confirms_submit(self):
        bid=self.new('posters_flyers')
        upload=self.client.post(f'/client/briefs/{bid}/adaptive/assets',data={'csrf_token':self.token,'file':(io.BytesIO(b'Approved brand copy'),'brand-notes.txt')})
        asset=upload.json['id']
        answers=complete('posters_flyers',{'PF02A':'celebrations','PF02J':'graduation','PF02C':'no',
                'PF12A':'palette','PF12B':'warm_elegant','PF10A':'yes','PF10C':asset,
                'PF17A':'range','PF17B':{'amount':'1000.00','currency':'KES'},'PF17C':{'amount':'5000.00','currency':'KES'},'PF16A':'2027-05-10'})
        response=self.save(bid,answers);self.assertEqual(response.status_code,200,response.data)
        html=self.client.get(f'/client/briefs/{bid}/adaptive/review').get_data(as_text=True)
        self.assertIn('Your brief is ready for review',html)
        self.assertIn('class="review-submit-form"',html)
        self.assertIn('Warm &amp; Elegant',html)
        self.assertIn('class="swatches" role="img"',html)
        self.assertIn('10 May 2027',html);self.assertIn('KES 1,000.00',html)
        self.assertIn('brand-notes.txt',html);self.assertIn('/brief-assets/'+str(asset),html)
        self.assertIn('class="review-answer-details"',html)
        self.assertIn('Dimensions and deliverables',html)
        self.assertNotIn('data-review-field=',html)
        self.assertEqual(self.client.post(f'/client/briefs/{bid}/adaptive/submit',data={'csrf_token':self.token,'generation':1}).status_code,400)
        self.assertEqual(self.submit(bid,1).status_code,302)
        snapshot=json.loads(self.db.execute('SELECT answers_json FROM adaptive_submissions WHERE brief_id=?',(bid,)).fetchone()[0])
        self.assertEqual(next(item['value'] for item in snapshot if item['field_id']=='PF16A'),'2027-05-10')
        submitted=self.client.get(f'/client/briefs/{bid}/adaptive/review').get_data(as_text=True)
        self.assertNotIn('class="review-submit-form"',submitted)
        self.assertNotIn('class="review-section-edit"',submitted)

    def test_review_distinguishes_pending_information_and_omits_hidden_modules(self):
        bid=self.new('posters_flyers')
        answers=complete('posters_flyers',{'PF02A':'celebrations','PF02J':'graduation','PF02C':'yes','EV02A':'pending'})
        self.assertEqual(self.save(bid,answers).status_code,200)
        html=self.client.get(f'/client/briefs/{bid}/adaptive/review').get_data(as_text=True)
        self.assertIn('Pending confirmation',html)
        self.assertIn('Notes for your designer',html)
        self.assertIn('class="review-submit-form"',html)
        self.assertIn('Event and category details',html)

    def test_json_submission_receipt_ownership_duplicate_and_provider_workflow(self):
        bid=self.new('posters_flyers')
        answers=complete('posters_flyers',{'PF02A':'celebrations','PF02J':'graduation','PF02C':'no','REL01':'Hidden religious branch'})
        self.assertEqual(self.save(bid,answers).status_code,200)
        url=f'/client/briefs/{bid}/adaptive/submit'
        def submit_json(generation=1,confirm='yes'):
            return self.client.post(url,data={'generation':generation,'confirm':confirm},headers={'Accept':'application/json','X-CSRFToken':self.token})
        self.assertEqual(self.client.get(f'/client/briefs/{bid}/adaptive/submissions/999/confirmation').status_code,404)
        self.assertEqual(submit_json(confirm='').status_code,400)
        self.assertEqual(submit_json(generation=0).status_code,409)
        self.login(3);self.assertEqual(submit_json().status_code,404)
        self.login(1)
        state=self.client.get(f'/client/briefs/{bid}/adaptive/submission-state')
        self.assertEqual(state.status_code,200);self.assertTrue(state.json['can_submit'])
        response=submit_json();self.assertEqual(response.status_code,200,response.data)
        receipt=response.json;self.assertTrue(receipt['ok'])
        row=self.db.execute('SELECT status,submitted_at,completeness_percentage FROM project_briefs WHERE id=?',(bid,)).fetchone()
        self.assertEqual(row[0],'submitted');self.assertIsNotNone(row[1]);self.assertEqual(row[2],100)
        snapshot=json.loads(self.db.execute('SELECT answers_json FROM adaptive_submissions WHERE brief_id=?',(bid,)).fetchone()[0])
        self.assertNotIn('REL01',{item['field_id'] for item in snapshot})
        success=self.client.get(receipt['confirmation_url']);self.assertEqual(success.status_code,200)
        self.assertIn(b'Your ideas are on their way.',success.data);self.assertIn(b'Return to Studio',success.data)
        self.assertEqual(submit_json().status_code,409)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM adaptive_submissions WHERE brief_id=?',(bid,)).fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT status,submitted_at,completeness_percentage FROM project_briefs WHERE id=?',(bid,)).fetchone(),row)
        self.assertIn('brief_id='+str(bid),self.client.get('/briefs').get_data(as_text=True))
        state=self.client.get(f'/client/briefs/{bid}/adaptive/submission-state')
        self.assertEqual(state.json['receipt']['submission_id'],receipt['submission_id']);self.assertFalse(state.json['can_submit'])
        self.login(3);self.assertEqual(self.client.get(receipt['confirmation_url']).status_code,404)
        self.login(2);self.assertEqual(self.client.get(f'/provider/briefs/{bid}/review').status_code,200)
        revision=self.client.post(f'/provider/briefs/{bid}/adaptive',data={'csrf_token':self.token,'decision':'revision_requested','comment':'Please revise the headline.'})
        self.assertEqual(revision.status_code,302)
        self.login(1)
        self.assertEqual(self.save(bid,{'PF06B':'Updated graduation headline'},2,'Headline updated.').status_code,200)
        second=submit_json(generation=3);self.assertEqual(second.status_code,200,second.data)
        self.assertEqual(second.json['revision_number'],2)
        self.assertNotEqual(second.json['submission_id'],receipt['submission_id'])
        self.login(2)
        approved=self.client.post(f'/provider/briefs/{bid}/adaptive',data={'csrf_token':self.token,'decision':'approved','comment':'Approved'})
        self.assertEqual(approved.status_code,302,approved.data)
        self.assertEqual(self.db.execute('SELECT status FROM project_briefs WHERE id=?',(bid,)).fetchone()[0],'approved')
        self.assertEqual(self.db.execute(
            'SELECT event_type, recipient_id FROM notifications WHERE brief_id=? ORDER BY id', (bid,)
        ).fetchall(), [('submitted', 2), ('revision_requested', 1), ('resubmitted', 2), ('approved', 1)])
        provider_feed = self.client.get('/notifications').get_data(as_text=True)
        self.assertIn(f'href="/provider/briefs/{bid}/review"', provider_feed)
        self.assertIn('A revised project brief is ready for review.', provider_feed)
        self.login(1)
        client_feed = self.client.get('/notifications').get_data(as_text=True)
        client_link = f'/client/briefs/{bid}/adaptive/review'
        self.assertIn(f'href="{client_link}"', client_feed)
        self.assertIn('Your project brief has been approved for design.', client_feed)
        self.assertEqual(self.client.get(client_link).status_code, 200)

    def test_notification_failure_rolls_back_adaptive_submission(self):
        bid = self.new()
        self.assertEqual(self.save(bid, complete('logo_branding')).status_code, 200)
        self.db.execute("""CREATE TRIGGER reject_notification BEFORE INSERT ON notifications
                           BEGIN SELECT RAISE(ABORT, 'test notification write failure'); END""")
        self.assertEqual(self.submit(bid, 1).status_code, 500)
        self.assertEqual(self.db.execute('SELECT status FROM project_briefs WHERE id=?', (bid,)).fetchone()[0], 'draft')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM adaptive_submissions').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0], 0)
        self.db.execute('DROP TRIGGER reject_notification')
        self.assertEqual(self.submit(bid, 1).status_code, 302)

    def test_submission_api_expired_tokens_sessions_and_incomplete_validation(self):
        import time
        from unittest.mock import patch
        from itsdangerous import URLSafeTimedSerializer
        bid=self.new();url=f'/client/briefs/{bid}/adaptive/submit'
        payload={'generation':0,'confirm':'yes'}
        headers={'Accept':'application/json','X-CSRFToken':self.token}
        incomplete=self.client.post(url,data=payload,headers=headers)
        self.assertEqual(incomplete.status_code,400);self.assertEqual(incomplete.json['code'],'brief_incomplete')
        with self.client.session_transaction() as state:raw=state['csrf_token']
        with patch('itsdangerous.timed.time.time',return_value=time.time()-3601):expired=URLSafeTimedSerializer(self.app.secret_key,salt='wtf-csrf-token').dumps(raw)
        rejected=self.client.post(url,data=payload,headers={'Accept':'application/json','X-CSRFToken':expired})
        self.assertEqual(rejected.status_code,400);self.assertEqual(rejected.json['code'],'csrf_refresh_required')
        with self.client.session_transaction() as state:state.clear()
        rejected=self.client.post(url,data=payload,headers=headers)
        self.assertEqual(rejected.status_code,401);self.assertEqual(rejected.json['code'],'session_expired')
        self.assertEqual(self.client.get(f'/client/briefs/{bid}/adaptive/submission-state').status_code,401)
        self.assertEqual(self.db.execute('SELECT status FROM project_briefs WHERE id=?',(bid,)).fetchone()[0],'draft')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM adaptive_submissions WHERE brief_id=?',(bid,)).fetchone()[0],0)

    def test_submission_transaction_failure_rolls_back_and_allows_safe_retry(self):
        bid=self.new();self.assertEqual(self.save(bid,complete('logo_branding')).status_code,200)
        before=self.db.execute('SELECT answers_json,generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone()
        self.db.execute("CREATE TRIGGER fail_submission BEFORE UPDATE ON project_briefs WHEN NEW.status='submitted' BEGIN SELECT RAISE(ABORT,'simulated submission failure'); END;");self.db.commit()
        url=f'/client/briefs/{bid}/adaptive/submit';data={'confirm':'yes','generation':1};headers={'Accept':'application/json','X-CSRFToken':self.token}
        with self.assertLogs(self.app.logger,level='ERROR'):response=self.client.post(url,data=data,headers=headers)
        self.assertEqual(response.status_code,500);self.assertEqual(response.json['code'],'submission_unavailable')
        self.assertNotIn('simulated submission failure',response.get_data(as_text=True))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM adaptive_submissions WHERE brief_id=?',(bid,)).fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT status,submitted_at FROM project_briefs WHERE id=?',(bid,)).fetchone(),('draft',None))
        self.assertEqual(self.db.execute('SELECT answers_json,generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone(),before)
        self.db.execute('DROP TRIGGER fail_submission');self.db.commit()
        response=self.client.post(url,data=data,headers=headers);self.assertEqual(response.status_code,200)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM adaptive_submissions WHERE brief_id=?',(bid,)).fetchone()[0],1)

    def test_designer_workspace_keeps_completeness_distinct_from_verification(self):
        from html.parser import HTMLParser
        class Visible(HTMLParser):
            def __init__(self):super().__init__();self.parts=[]
            def handle_data(self,data):self.parts.append(data)
        bid=self.new('posters_flyers')
        fields=engine.fields_for(engine.sections(engine.load_catalog(),'posters_flyers'))
        cta=next(o['value'] for o in fields['PF08A']['options'] if o['value'] not in ('none','share','other'))
        answers=complete('posters_flyers',{'META01':'Graduation studio review','PF02A':'celebrations','PF02J':'graduation','PF02C':'no',
                         'PF08A':cta,'PF08C':['website'],'REL01':'Hidden religious answer',
                         'PF06B':'<script>window.shouldNotRun=true</script>Graduation headline'})
        result=self.save(bid,answers);self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['assessment']['percentage'],100)
        self.assertTrue(result.json['assessment']['issues'])
        self.assertEqual(self.submit(bid,1).status_code,302)
        before=self.db.execute('SELECT answers_json,generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone()
        snapshot=self.db.execute('SELECT answers_json FROM adaptive_submissions WHERE brief_id=?',(bid,)).fetchone()[0]
        self.login(2);page=self.client.get(f'/provider/briefs/{bid}/review');self.assertEqual(page.status_code,200)
        html=page.get_data(as_text=True);visible=Visible();visible.feed(html);text=' '.join(visible.parts)
        self.assertIn('Designer review summary',text);self.assertIn('Contact destinations',text)
        self.assertIn('Questionnaire completeness and independent verification are separate checks.',text)
        self.assertIn('required answers complete',text);self.assertIn('Details to verify',text)
        self.assertIn('>100<',html);self.assertIn('data-blocked="true"',html)
        self.assertIn('User 1',text);self.assertIn('Posters & Flyers',text)
        for internal in ('META01','META02','PF02','EV01','posters_flyers','celebrations','graduation'):
            self.assertNotIn(internal,text)
        self.assertNotIn('Hidden religious answer',text)
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>window.shouldNotRun',html)
        self.assertIn('data-expand-sections="open"',html);self.assertIn('designer-decision-dialog',html)
        self.assertEqual(self.client.post(f'/provider/briefs/{bid}/adaptive',data={'csrf_token':self.token,'decision':'approved','comment':'Cannot bypass warnings'}).status_code,409)
        self.assertEqual(self.db.execute('SELECT answers_json,generation FROM adaptive_drafts WHERE brief_id=?',(bid,)).fetchone(),before)
        self.assertEqual(self.db.execute('SELECT answers_json FROM adaptive_submissions WHERE brief_id=?',(bid,)).fetchone()[0],snapshot)
        self.assertEqual(self.client.post(f'/client/briefs/{bid}/adaptive/save',json={'generation':1,'answers':{}},headers={'X-CSRFToken':self.token}).status_code,403)
        self.login(4);self.assertEqual(self.client.get(f'/provider/briefs/{bid}/review').status_code,404)

    def test_designer_image_previews_use_existing_authorisation_and_safe_types(self):
        import base64
        bid=self.new('posters_flyers');assets=[]
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVzUAAAAASUVORK5CYII=')
        for filename,content in [('brand.png',png),('brand-guide.txt',b'Approved brand guide'),('private-draft.png',png)]:
            upload=self.client.post(f'/client/briefs/{bid}/adaptive/assets',data={'csrf_token':self.token,'file':(io.BytesIO(content),filename)})
            self.assertEqual(upload.status_code,200);assets.append(upload.json['id'])
        answers=complete('posters_flyers',{'PF02A':'celebrations','PF02J':'graduation','PF02C':'no','PF10A':'yes','PF10C':assets[0],'PF11E':'yes','PF11F':assets[1],'PF12A':'palette','PF12B':'warm_elegant','PF08E':'yes','PF08F':'https://example.com/design'})
        self.assertEqual(self.save(bid,answers).status_code,200);self.assertEqual(self.submit(bid,1).status_code,302)
        self.login(2)
        page=self.client.get(f'/provider/briefs/{bid}/review').get_data(as_text=True)
        self.assertIn('designer-image-preview',page);self.assertIn('brand-guide.txt',page);self.assertIn('Warm &amp; Elegant',page)
        self.assertNotIn('private-draft.png',page)
        self.assertIn('href="https://example.com/design"',page);self.assertIn('rel="noopener noreferrer"',page)
        response=self.client.get(f'/brief-assets/{assets[0]}?preview=1');self.assertEqual(response.status_code,200)
        self.assertEqual(response.mimetype,'image/png');self.assertIn('inline',response.headers['Content-Disposition'])
        self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff');self.assertIn('sandbox',response.headers['Content-Security-Policy']);response.close()
        response=self.client.get(f'/brief-assets/{assets[1]}?preview=1');self.assertIn('attachment',response.headers['Content-Disposition']);response.close()
        self.assertEqual(self.client.get(f'/brief-assets/{assets[2]}?preview=1').status_code,404)
        self.login(4);self.assertEqual(self.client.get(f'/brief-assets/{assets[0]}?preview=1').status_code,404)
        self.login(3);self.assertEqual(self.client.get(f'/brief-assets/{assets[0]}?preview=1').status_code,404)

    def test_all_services_render_in_designer_workspace_without_draft_mutation(self):
        for service in engine.services(engine.load_catalog()):
            self.login(1);bid=self.new(service['value'])
            self.assertEqual(self.save(bid,complete(service['value'])).status_code,200)
            self.assertEqual(self.submit(bid,1).status_code,302)
            self.login(2);response=self.client.get(f'/provider/briefs/{bid}/review')
            self.assertEqual(response.status_code,200)
            self.assertIn(b'designer-current-sections',response.data)
            self.assertIn(service['label'],response.get_data(as_text=True).replace('&amp;','&'))
            self.assertEqual(self.db.execute('SELECT status FROM project_briefs WHERE id=?',(bid,)).fetchone()[0],'submitted')

    def test_all_services_render_and_resume_through_dashboard_links(self):
        page=self.client.get('/briefs/new').get_data(as_text=True)
        self.assertNotIn('Start a guided brief',page)
        self.assertEqual(page.count('class="new-brief-form"'),1)
        self.assertIn('Back to My Briefs',page)
        for service in engine.services(engine.load_catalog()):
            creation=self.client.post('/briefs/new',data={'csrf_token':self.token,'project_title':'Project','provider_id':2,'questionnaire_id':'service:'+service['value']})
            self.assertEqual(creation.status_code,302)
            bid=int(creation.location.split('/')[-2]); response=self.client.get(f'/client/briefs/{bid}/adaptive')
            self.assertEqual(response.status_code,200); self.assertIn(b'Your ideas',response.data)
            self.assertEqual(self.save(bid,{'META01':'Renamed'}).status_code,200)
            qid=self.db.execute('SELECT v.questionnaire_id FROM project_briefs b JOIN questionnaire_versions v ON v.id=b.questionnaire_version_id WHERE b.id=?',(bid,)).fetchone()[0]
            self.assertEqual(self.client.get(f'/client/questionnaires/{qid}?brief_id={bid}').status_code,302)
        self.assertEqual(self.client.get('/dashboard/client').status_code,200)
    def test_submit_revision_approval_and_immutable_snapshots(self):
        bid=self.new(); answers=complete('logo_branding'); response=self.save(bid,answers); self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(self.submit(bid,1).status_code,302)
        self.assertEqual(self.client.get(f'/client/briefs/{bid}/adaptive/review').status_code,200)
        original=self.db.execute('SELECT answers_json FROM adaptive_submissions WHERE brief_id=?',(bid,)).fetchone()[0]
        self.assertEqual(self.save(bid,answers,1).status_code,409)
        self.login(2); self.assertEqual(self.client.get(f'/provider/briefs/{bid}/review').status_code,200)
        response=self.client.post(f'/provider/briefs/{bid}/adaptive',data={'csrf_token':self.token,'decision':'revision_requested','comment':'Please refine the brand name.'}); self.assertEqual(response.status_code,302)
        self.login(1); answers['LB01']='Revised name'
        self.assertEqual(self.save(bid,answers,2,'Brand name updated.').status_code,200)
        self.assertEqual(self.submit(bid,3).status_code,302)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM adaptive_submissions').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT answers_json FROM adaptive_submissions ORDER BY id LIMIT 1').fetchone()[0],original)
        self.login(2); response=self.client.post(f'/provider/briefs/{bid}/adaptive',data={'csrf_token':self.token,'decision':'approved','comment':'Approved'}); self.assertEqual(response.status_code,302,response.data)
        self.assertEqual(self.db.execute('SELECT status FROM project_briefs WHERE id=?',(bid,)).fetchone()[0],'approved')
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute("UPDATE adaptive_submissions SET response_text='tamper'")
        self.db.rollback()
    def test_incomplete_tampered_csrf_stale_and_cross_user_requests(self):
        bid=self.new()
        self.assertEqual(self.submit(bid,0).status_code,400)
        self.assertEqual(self.save(bid,{'FORGED':'answer'}).status_code,400)
        self.assertEqual(self.save(bid,{'META02':'packaging_design'}).status_code,400)
        self.assertEqual(self.client.post(f'/client/briefs/{bid}/adaptive/save',json={'answers':{}}).status_code,400)
        self.assertEqual(self.save(bid,{}).status_code,200)
        self.assertEqual(self.save(bid,{},0).status_code,409)
        self.assertEqual(self.client.post(f'/briefs/{bid}/submit',data={'csrf_token':self.token,'confirm_submit':'yes'}).status_code,409)
        self.login(3)
        self.assertEqual(self.client.get(f'/client/briefs/{bid}/adaptive').status_code,404)
        self.assertEqual(self.save(bid,{}).status_code,404)
        self.login(4); self.assertEqual(self.client.get(f'/provider/briefs/{bid}/adaptive').status_code,404)
    def test_pending_essentials_and_human_verification_gate_approval(self):
        bid=self.new('packaging_design'); answers=complete('packaging_design',{'PK09':'yes'})
        self.assertEqual(self.save(bid,answers).status_code,200)
        self.assertEqual(self.submit(bid,1).status_code,302)
        self.login(2)
        payload={'csrf_token':self.token,'decision':'approved','comment':'Reviewed legal copy.'}
        self.assertEqual(self.client.post(f'/provider/briefs/{bid}/adaptive',data=payload).status_code,409)
        payload['verified']='yes'
        self.assertEqual(self.client.post(f'/provider/briefs/{bid}/adaptive',data=payload).status_code,302)

    def test_provider_downloads_only_submitted_asset_references(self):
        bid=self.new(); endpoint=f'/client/briefs/{bid}/adaptive/assets'
        uploaded=[]
        for name in ('submitted.txt','draft-private.txt'):
            response=self.client.post(endpoint,data={'csrf_token':self.token,'file':(io.BytesIO(b'Client supplied text'),name)})
            uploaded.append(response.json['id'])
        answers=complete('logo_branding',{'CORE02A':'yes','CORE02B':uploaded[0]})
        self.assertEqual(self.save(bid,answers).status_code,200)
        self.assertEqual(self.submit(bid,1).status_code,302)
        self.login(2)
        response=self.client.get(f'/brief-assets/{uploaded[0]}'); self.assertEqual(response.status_code,200); response.close()
        self.assertEqual(self.client.get(f'/brief-assets/{uploaded[1]}').status_code,404)
        self.assertIn(b'Download supplied asset',self.client.get(f'/provider/briefs/{bid}/adaptive').data)

    def test_populated_database_backup_and_repeatable_upgrade(self):
        from flask import Flask
        from database import init_app
        path=Path(self.temp.name)/'legacy.db'
        with closing(sqlite3.connect(path)) as database:
            database.executescript("CREATE TABLE users (id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', created_at TEXT); INSERT INTO users VALUES (9,'Preserved','preserved@example.test','unused','client','active',CURRENT_TIMESTAMP);")
        old=os.environ.get('ELUNETTE_DATABASE'); os.environ['ELUNETTE_DATABASE']=str(path)
        try:
            app=Flask('upgrade',root_path=str(Path.cwd())); init_app(app); init_app(app)
        finally:
            if old is None: os.environ.pop('ELUNETTE_DATABASE',None)
            else: os.environ['ELUNETTE_DATABASE']=old
        backups=list(Path(self.temp.name).glob('legacy.pre-adaptive-*.db'))
        self.assertEqual(len(backups),1)
        with closing(sqlite3.connect(backups[0])) as backup: self.assertEqual(backup.execute('SELECT full_name FROM users WHERE id=9').fetchone()[0],'Preserved')
        with closing(sqlite3.connect(path)) as database:
            self.assertEqual(database.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(database.execute('SELECT full_name FROM users WHERE id=9').fetchone()[0],'Preserved')

    def test_upload_sniffing_ownership_and_download_permissions(self):
        bid=self.new(); endpoint=f'/client/briefs/{bid}/adaptive/assets'
        for filename,content in [('script.svg',b'<svg><script>bad</script></svg>'),('fake.png',b'<html>bad</html>')]:
            response=self.client.post(endpoint,data={'csrf_token':self.token,'file':(io.BytesIO(content),filename)})
            self.assertEqual(response.status_code,400)
        response=self.client.post(endpoint,data={'csrf_token':self.token,'file':(io.BytesIO(b'Approved client copy'),'../../copy.txt')})
        self.assertEqual(response.status_code,200); asset=response.json['id']
        response=self.client.get(f'/brief-assets/{asset}'); self.assertEqual(response.status_code,200); self.assertIn('attachment',response.headers['Content-Disposition']); response.close()
        other=self.new(); self.assertEqual(self.save(other,{'CORE02B':asset}).status_code,400)
        self.login(3); self.assertEqual(self.client.get(f'/brief-assets/{asset}').status_code,404)
        self.login(2); self.assertEqual(self.client.get(f'/brief-assets/{asset}').status_code,404)

if __name__=='__main__': unittest.main()
