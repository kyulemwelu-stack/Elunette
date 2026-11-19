"""Catalog routes extending Elunette project_briefs and provider workflows."""
import io
import json
import secrets
import sqlite3
import zipfile
from pathlib import Path
from flask import abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
from flask_wtf.csrf import CSRFError, generate_csrf
from database import get_db
from notifications import record_notification
import questionnaire_engine as engine
from questionnaire_review import build_review, readable_date, readable_time, readable_money
from designer_review import build_designer_review, designer_timestamp


def register(app, current_user, role_required):
    if app.config.get('MAX_CONTENT_LENGTH') is None:
        app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024
    app.config.setdefault('ADAPTIVE_UPLOAD_ROOT', str(Path(app.instance_path) / 'brief_assets'))

    app.add_template_filter(readable_date,'review_date')
    app.add_template_filter(readable_time,'review_time')
    app.add_template_filter(readable_money,'review_money')
    app.add_template_filter(designer_timestamp,'designer_timestamp')
    app.add_template_filter(engine.public_url,'designer_public_url')

    api_endpoints={'adaptive_save','adaptive_draft_state','adaptive_upload','adaptive_submit','adaptive_submission_state'}

    def api_error(code, message, status_code):
        if request.endpoint in ('adaptive_submit','adaptive_submission_state') and code=='session_expired':
            message='Please sign in again in another tab, then try submitting here. Your saved brief is safe.'
        response=jsonify(code=code, errors={'_form':message})
        response.headers['Cache-Control']='no-store'
        return response,status_code

    @app.before_request
    def authenticate_adaptive_api():
        if request.endpoint in api_endpoints and current_user() is None:
            return api_error('session_expired','Please sign in again in another tab, then try saving here. Your answers are still on this page.',401)

    @app.errorhandler(CSRFError)
    def adaptive_csrf_error(error):
        if request.endpoint not in api_endpoints:
            return error
        app.logger.info('Adaptive request rejected by CSRF protection: %s',error.description)
        if current_user() is None:
            return api_error('session_expired','Please sign in again in another tab, then try saving here. Your answers are still on this page.',401)
        return api_error('csrf_refresh_required','Your security check needs refreshing. Please try saving again; your answers are still here.',400)

    @app.errorhandler(HTTPException)
    def adaptive_http_error(error):
        if request.endpoint not in api_endpoints:
            return error
        messages={
            400:('invalid_request','We could not read this save request. Your answers are still on this page.'),
            403:('access_denied','This account cannot edit this brief. Your answers are still on this page.'),
            404:('brief_unavailable','This brief is unavailable to this account. Your answers are still on this page.'),
            409:('draft_conflict','A newer version was saved, or this brief is no longer editable. Your changes are still here; download a copy before reloading.'),
            413:('request_too_large','This request is too large. Try a smaller upload; your answers are still on this page.'),
            500:('save_unavailable','We could not save your draft right now. Your answers are still here. Please try again.')}
        code,message=messages.get(error.code,('save_unavailable','Saving is temporarily unavailable. Your answers are still here. Please try again.'))
        if request.endpoint in ('adaptive_submit','adaptive_submission_state'):
            submit_messages={
                400:('confirmation_required','Please confirm that you have reviewed your brief before submitting.'),
                409:('submission_conflict','This brief has changed or has already been submitted. Check its latest version before trying again.'),
                500:('submission_unavailable','We could not submit your brief right now. Your saved answers are safe. Please try again.')}
            code,message=submit_messages.get(error.code,(code,message))
        return api_error(code,message,error.code)

    def record(brief_id, provider=False, editable=False):
        user=current_user()
        if user is None: abort(401)
        key='assigned_provider_id' if provider else 'client_id'
        row=get_db().execute(f'''SELECT b.*, d.service,d.schema_json,v.questionnaire_id,v.version_number AS definition_version,client.full_name AS client_name,
            a.answers_json,a.revision_response,a.generation FROM project_briefs b
            JOIN adaptive_definitions d ON d.version_id=b.questionnaire_version_id
            JOIN questionnaire_versions v ON v.id=b.questionnaire_version_id
            JOIN users client ON client.id=b.client_id
            JOIN adaptive_drafts a ON a.brief_id=b.id WHERE b.id=? AND b.{key}=?''',(brief_id,user['id'])).fetchone()
        if row is None or (provider and row['status']=='draft'): abort(404)
        if editable and row['status'] not in ('draft','revision_requested'): abort(409)
        return dict(row)

    def context(row, submitted=False):
        catalog=json.loads(row['schema_json'])
        groups=engine.sections(catalog,row['service'])
        answers=json.loads(row['answers_json'])
        if submitted:
            latest=get_db().execute('SELECT * FROM adaptive_submissions WHERE brief_id=? ORDER BY revision_number DESC LIMIT 1',(row['id'],)).fetchone()
            if latest:
                answers={item['field_id']:item['value'] for item in json.loads(latest['answers_json'])}
        allowed=lambda asset: get_db().execute('SELECT 1 FROM brief_assets WHERE id=? AND brief_id=? AND uploader_id=?',(asset,row['id'],row['client_id'])).fetchone() is not None
        result=engine.assessment(groups,answers,catalog,allowed)
        return catalog,groups,answers,allowed,result

    def page(row, review=False, provider=False, status=200):
        catalog,groups,answers,allowed,result=context(row,submitted=provider or row['status'] not in ('draft','revision_requested'))
        history=get_db().execute('SELECT * FROM adaptive_submissions WHERE brief_id=? ORDER BY revision_number DESC',(row['id'],)).fetchall()
        history=[dict(h,items=json.loads(h['answers_json'])) for h in history]
        feedback=get_db().execute('SELECT r.*,u.full_name AS reviewer_name FROM brief_reviews r JOIN users u ON u.id=r.reviewer_id WHERE r.brief_id=? ORDER BY r.id DESC',(row['id'],)).fetchall()
        assets=get_db().execute('SELECT id,original_name,media_type FROM brief_assets WHERE brief_id=?',(row['id'],)).fetchall()
        if provider:
            designer=build_designer_review(groups,answers,result,row,catalog,history)
            return render_template('designer_brief.html',brief=row,designer=designer,catalog=catalog,
                result=result,feedback=feedback,asset_map={a['id']:dict(a) for a in assets},user=current_user()),status
        review_view=not provider and (review or row['status'] not in ('draft','revision_requested'))
        review_data=build_review(groups,answers,result,row,
            lambda field: url_for('adaptive_edit',brief_id=row['id'],question=field,return_to='review')) if review_view else None
        return render_template('adaptive_questionnaire.html',review_view=review_view,review_data=review_data,asset_names={a['id']:a['original_name'] for a in assets},brief=row,catalog=catalog,groups=groups,answers=answers,
            result=result,summary=engine.snapshot(groups,answers),history=history,feedback=feedback,assets=assets,
            fieldmap=engine.fields_for(groups),user=current_user(),review=review,provider=provider,editable=not provider and row['status'] in ('draft','revision_requested')),status

    @app.route('/client/adaptive/new',methods=['GET','POST'])
    @role_required('client')
    def adaptive_new():
        db=get_db()
        catalog=engine.load_catalog()
        providers=db.execute("SELECT id,full_name FROM users WHERE role='service_provider' AND status='active' ORDER BY full_name").fetchall()
        if request.method=='GET': return render_template('adaptive_new.html',catalog=catalog,services=engine.services(catalog),providers=providers,user=current_user())
        title=request.form.get('META01',request.form.get('project_title','')).strip()
        service=request.form.get('META02',request.form.get('questionnaire_id','').removeprefix('service:'))
        provider_id=request.form.get('provider_id',type=int)
        if not title or len(title)>150 or service not in {s['value'] for s in engine.services(catalog)}: abort(400,'Choose a service and a project title of up to 150 characters.')
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM users WHERE id=? AND role='service_provider' AND status='active'",(provider_id,)).fetchone() is None: abort(400,'Choose an available provider.')
        serialized=json.dumps(catalog,sort_keys=True)
        definition=db.execute('''SELECT d.version_id,v.questionnaire_id FROM adaptive_definitions d JOIN questionnaire_versions v ON v.id=d.version_id JOIN questionnaires q ON q.id=v.questionnaire_id WHERE d.service=? AND d.schema_json=? AND q.created_by=?''',(service,serialized,provider_id)).fetchone()
        if definition:
            version_id=definition['version_id']
        else:
            name=next(s['label'] for s in engine.services(catalog) if s['value']==service)
            qid=db.execute("INSERT INTO questionnaires(title,description,created_by,status) VALUES (?,?,?,'active')",(name,'Adaptive design brief · catalog '+catalog['version'],provider_id)).lastrowid
            version_id=db.execute('INSERT INTO questionnaire_versions(questionnaire_id) VALUES (?)',(qid,)).lastrowid
            db.execute('INSERT INTO adaptive_definitions VALUES (?,?,?,?)',(version_id,service,catalog['version'],serialized))
            db.execute('INSERT INTO questionnaire_publications(questionnaire_id,questionnaire_version_id,title_snapshot,description_snapshot) VALUES (?,?,?,?)',(qid,version_id,name,'Adaptive design brief'))
        bid=db.execute("INSERT INTO project_briefs(client_id,assigned_provider_id,questionnaire_version_id,title) VALUES (?,?,?,?)",(current_user()['id'],provider_id,version_id,title)).lastrowid
        db.execute('INSERT INTO adaptive_drafts(brief_id,answers_json) VALUES (?,?)',(bid,json.dumps({'META01':title,'META02':service})))
        db.commit()
        return redirect(url_for('adaptive_edit',brief_id=bid))

    @app.route('/client/briefs/<int:brief_id>/adaptive')
    @role_required('client')
    def adaptive_edit(brief_id): return page(record(brief_id))

    @app.route('/client/briefs/<int:brief_id>/adaptive/save-state')
    @role_required('client')
    def adaptive_draft_state(brief_id):
        row=record(brief_id,editable=True)
        response=jsonify(csrf_token=generate_csrf(),generation=row['generation'],
                         answers=json.loads(row['answers_json']),revision_response=row['revision_response'],assessment=context(row)[4])
        response.headers['Cache-Control']='private, no-store'
        response.headers['Vary']='Cookie'
        return response

    @app.route('/client/briefs/<int:brief_id>/adaptive/save',methods=['POST'])
    @role_required('client')
    def adaptive_save(brief_id):
        db=get_db()
        try:
            return persist_adaptive_draft(brief_id,db)
        except sqlite3.OperationalError:
            db.rollback()
            app.logger.exception('Adaptive draft persistence unavailable for brief %s',brief_id)
            return api_error('save_unavailable','Saving is temporarily unavailable. Your answers are still here. Please try again.',503)
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            app.logger.exception('Adaptive draft persistence failed for brief %s',brief_id)
            return api_error('save_unavailable','We could not save your draft right now. Your answers are still here. Please try again.',500)

    def persist_adaptive_draft(brief_id,db):
        db.execute('BEGIN IMMEDIATE')
        row=record(brief_id,editable=True)
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict) or set(payload)-{'answers','generation','revision_response'}: abort(400)
        if type(payload.get('generation')) is not int or payload['generation']!=row['generation']: abort(409,'A newer draft exists. Reload before saving.')
        catalog,groups,answers,allowed,result=context(row)
        supplied=payload.get('answers')
        if not isinstance(supplied,dict): abort(400)
        if supplied.get('META02',row['service'])!=row['service']: abort(400,'Service cannot change on an existing brief.')
        answers.update(supplied)
        clean,errors=engine.validate(groups,answers,catalog,allowed)
        if len(clean.get('META01',''))>150: errors['META01']='Project title must be at most 150 characters.'
        response=payload.get('revision_response',row['revision_response'])
        if not isinstance(response,str) or len(response)>5000: errors['_response']='Revision response must be at most 5000 characters.'
        if errors:
            db.rollback()
            return jsonify(code='validation_error',errors=errors),400
        result=engine.assessment(groups,clean,catalog,allowed)
        db.execute('UPDATE adaptive_drafts SET answers_json=?,revision_response=?,generation=generation+1,updated_at=CURRENT_TIMESTAMP WHERE brief_id=?',(json.dumps(clean),response,brief_id))
        db.execute('UPDATE project_briefs SET title=?,completeness_percentage=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(clean.get('META01') or row['title'],result['percentage'],brief_id))
        db.commit()
        return jsonify(generation=row['generation']+1,assessment=result)

    @app.route('/client/briefs/<int:brief_id>/adaptive/review')
    @role_required('client')
    def adaptive_review(brief_id): return page(record(brief_id),review=True)

    def submission_receipt(row, submission):
        return {'submission_id':submission['id'],'revision_number':submission['revision_number'],
                'confirmation_url':url_for('adaptive_submission_success',brief_id=row['id'],submission_id=submission['id'])}

    @app.route('/client/briefs/<int:brief_id>/adaptive/submission-state')
    @role_required('client')
    def adaptive_submission_state(brief_id):
        row=record(brief_id)
        latest=get_db().execute('SELECT * FROM adaptive_submissions WHERE brief_id=? ORDER BY revision_number DESC LIMIT 1',(brief_id,)).fetchone()
        result=context(row)[4]
        eligible=row['status'] in ('draft','revision_requested') and not result['errors'] and result['percentage']==100
        if row['status']=='revision_requested' and not row['revision_response'].strip(): eligible=False
        response=jsonify(csrf_token=generate_csrf(),generation=row['generation'],status=row['status'],
                         can_submit=eligible,receipt=submission_receipt(row,latest) if latest else None)
        response.headers['Cache-Control']='private, no-store'
        response.headers['Vary']='Cookie'
        return response

    @app.route('/client/briefs/<int:brief_id>/adaptive/submissions/<int:submission_id>/confirmation')
    @role_required('client')
    def adaptive_submission_success(brief_id,submission_id):
        row=record(brief_id)
        submission=get_db().execute('SELECT * FROM adaptive_submissions WHERE id=? AND brief_id=? AND actor_id=?',
                                   (submission_id,brief_id,current_user()['id'])).fetchone()
        if submission is None: abort(404)
        response=app.make_response(render_template('adaptive_submission_success.html',brief=row,submission=submission,user=current_user()))
        response.headers['Cache-Control']='private, no-store'
        return response

    @app.route('/client/briefs/<int:brief_id>/adaptive/submit',methods=['POST'])
    @role_required('client')
    def adaptive_submit(brief_id):
        db=get_db()
        try:
            return persist_adaptive_submission(brief_id,db)
        except sqlite3.OperationalError:
            db.rollback()
            app.logger.exception('Adaptive submission unavailable for brief %s',brief_id)
            return api_error('submission_unavailable','Submission is temporarily unavailable. Your saved answers are safe. Please try again.',503)
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            app.logger.exception('Adaptive submission failed for brief %s',brief_id)
            return api_error('submission_unavailable','We could not submit your brief right now. Your saved answers are safe. Please try again.',500)

    def persist_adaptive_submission(brief_id,db):
        db.execute('BEGIN IMMEDIATE')
        row=record(brief_id,editable=True)
        if request.form.get('confirm')!='yes': abort(400,'Confirm your review before submitting.')
        if request.form.get('generation',type=int)!=row['generation']: abort(409,'Draft changed. Review again.')
        catalog,groups,answers,allowed,result=context(row)
        if result['errors'] or result['percentage']!=100:
            db.rollback()
            if request.accept_mimetypes.best=='application/json':
                return jsonify(code='brief_incomplete',message='A few required details still need attention. Continue editing your brief, then review it again.',review_url=url_for('adaptive_review',brief_id=brief_id)),400
            return page(row,review=True,status=400)
        response=row['revision_response'].strip()
        if row['status']=='revision_requested' and not response:
            db.rollback()
            return api_error('revision_response_required','Add a short note about your revisions before resubmitting.',400)
        number=db.execute('SELECT COALESCE(MAX(revision_number),0)+1 FROM adaptive_submissions WHERE brief_id=?',(brief_id,)).fetchone()[0]
        cursor=db.execute('INSERT INTO adaptive_submissions(brief_id,revision_number,actor_id,answers_json,assessment_json,response_text) VALUES (?,?,?,?,?,?)',
                          (brief_id,number,current_user()['id'],json.dumps(engine.snapshot(groups,answers)),json.dumps(result),response))
        submission_id=cursor.lastrowid
        updated=db.execute("UPDATE project_briefs SET status='submitted',completeness_percentage=?,submitted_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('draft','revision_requested')",
                           (result['percentage'],brief_id))
        if updated.rowcount!=1: abort(409)
        event = 'resubmitted' if row['status'] == 'revision_requested' else 'submitted'
        record_notification(db, brief_id, event, f'adaptive-submission:{submission_id}')
        db.commit()
        confirmation=url_for('adaptive_submission_success',brief_id=brief_id,submission_id=submission_id)
        if request.accept_mimetypes.best=='application/json':
            return jsonify(ok=True,status='submitted',generation=row['generation'],submission_id=submission_id,revision_number=number,confirmation_url=confirmation)
        return redirect(confirmation)

    @app.route('/provider/briefs/<int:brief_id>/adaptive',methods=['GET','POST'])
    @role_required('service_provider')
    def adaptive_provider(brief_id):
        db=get_db()
        if request.method=='POST': db.execute('BEGIN IMMEDIATE')
        row=record(brief_id,provider=True)
        if request.method=='GET': return page(row,review=True,provider=True)
        if row['status'] not in ('submitted','under_review'): abort(409)
        if 'submission_id' in request.form:
            latest = db.execute(
                'SELECT id FROM adaptive_submissions WHERE brief_id=? ORDER BY revision_number DESC LIMIT 1',
                (brief_id,),
            ).fetchone()
            if request.form.get('submission_id', type=int) != (latest['id'] if latest else 0):
                abort(409, 'This brief changed. Reload to review the latest submission.')
        decision=request.form.get('decision'); comment=request.form.get('comment','').strip()
        if len(comment)>5000: abort(400)
        if decision=='approved':
            result=context(row,submitted=True)[4]
            unresolved=[issue for issue in result['issues'] if not issue.endswith('human verification and approval required.')]
            human_review=any(issue.endswith('human verification and approval required.') for issue in result['issues'])
            if result['errors'] or unresolved or (human_review and request.form.get('verified')!='yes'): abort(409,'Resolve pending information and explicitly verify claims before approval.')
            if human_review: comment += '\n[Human verification recorded during approval.]'
        elif decision=='revision_requested':
            if not comment: abort(400,'Revision feedback is required.')
        else: abort(400)
        review = db.execute('INSERT INTO brief_reviews(brief_id,reviewer_id,decision,comment) VALUES (?,?,?,?)',(brief_id,current_user()['id'],decision,comment))
        db.execute('UPDATE project_briefs SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(decision,brief_id))
        if decision=='revision_requested': db.execute("UPDATE adaptive_drafts SET revision_response='',generation=generation+1 WHERE brief_id=?",(brief_id,))
        record_notification(db, brief_id, decision, f'review:{review.lastrowid}')
        db.commit(); return redirect(url_for('adaptive_provider',brief_id=brief_id))

    @app.route('/client/briefs/<int:brief_id>/adaptive/assets',methods=['POST'])
    @role_required('client')
    def adaptive_upload(brief_id):
        db=get_db(); db.execute('BEGIN IMMEDIATE'); row=record(brief_id,editable=True)
        upload=request.files.get('file')
        if not upload:
            return api_error('upload_invalid', 'Choose a file to upload.', 400)
        data=upload.stream.read(20*1024*1024+1)
        if not data or len(data)>20*1024*1024:
            return api_error('upload_invalid', 'Choose a non-empty file up to 20 MB.', 400)
        name=secure_filename(upload.filename or '')
        if len(name)>200: name=Path(name).stem[:180]+Path(name).suffix
        extension=Path(name).suffix.lower()
        mime=None
        if extension=='.pdf' and data.startswith(b'%PDF-') and b'%%EOF' in data[-2048:]: mime='application/pdf'
        elif extension=='.png' and data.startswith(b'\x89PNG\r\n\x1a\n'): mime='image/png'
        elif extension in ('.jpg','.jpeg') and data.startswith(b'\xff\xd8\xff'): mime='image/jpeg'
        elif extension=='.webp' and data[:4]==b'RIFF' and data[8:12]==b'WEBP': mime='image/webp'
        elif extension=='.txt':
            try:
                decoded=data.decode('utf-8')
                if '\x00' not in decoded and not decoded.lstrip().lower().startswith(('<svg','<!doctype','<html','<script','<?xml')): mime='text/plain'
            except UnicodeDecodeError: pass
        elif extension=='.docx':
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    if '[Content_Types].xml' in archive.namelist() and 'word/document.xml' in archive.namelist() and sum(x.file_size for x in archive.infolist())<100*1024*1024: mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            except zipfile.BadZipFile: pass
        if mime is None:
            return api_error('upload_invalid', 'Choose a valid PDF, DOCX, TXT, PNG, JPEG or WebP file.', 400)
        total=db.execute('SELECT COALESCE(SUM(size),0) FROM brief_assets WHERE brief_id=?',(brief_id,)).fetchone()[0]
        if total+len(data)>200*1024*1024:
            return api_error('upload_invalid', 'This brief has reached its 200 MB upload limit.', 400)
        root=Path(app.config['ADAPTIVE_UPLOAD_ROOT']); root.mkdir(parents=True,exist_ok=True)
        storage=secrets.token_hex(24)+extension; path=root/storage
        try:
            path.write_bytes(data)
            asset_id=db.execute('INSERT INTO brief_assets(brief_id,uploader_id,storage_name,original_name,media_type,size) VALUES (?,?,?,?,?,?)',(brief_id,current_user()['id'],storage,name,mime,len(data))).lastrowid
            db.commit()
        except Exception:
            path.unlink(missing_ok=True); raise
        return jsonify(id=asset_id,name=name)

    @app.route('/brief-assets/<int:asset_id>')
    def adaptive_download(asset_id):
        user=current_user()
        if not user: abort(401)
        asset=get_db().execute('''SELECT a.*,b.client_id,b.assigned_provider_id,b.status FROM brief_assets a JOIN project_briefs b ON b.id=a.brief_id WHERE a.id=?''',(asset_id,)).fetchone()
        if asset is None:
            abort(404)
        owner = user['role'] == 'client' and user['id'] == asset['client_id']
        designer = (user['role'] == 'service_provider' and user['id'] == asset['assigned_provider_id']
                    and asset['status'] != 'draft')
        if not (owner or designer):
            abort(404)
        # Providers may only access files referenced by immutable submitted snapshots.
        if designer:
            row=record(asset['brief_id'],provider=True)
            catalog=json.loads(row['schema_json'])
            fields=engine.fields_for(engine.sections(catalog,row['service']))
            def references(field,value):
                if field['type'] in ('file_upload','asset_reference'): return type(value) is int and value==asset_id
                if field['type']=='repeater' and isinstance(value,list):
                    return any(references(child,item.get(child['id'])) for item in value for child in field['item_fields'] if child['id'] in item)
                return False
            submitted=get_db().execute('SELECT answers_json FROM adaptive_submissions WHERE brief_id=?',(asset['brief_id'],)).fetchall()
            if not any(references(fields[item['field_id']],item['value']) for submission in submitted for item in json.loads(submission['answers_json'])): abort(404)
        preview=request.args.get('preview')=='1' and asset['media_type'] in ('image/png','image/jpeg','image/webp')
        path = Path(app.config['ADAPTIVE_UPLOAD_ROOT']) / asset['storage_name']
        try:
            response=send_file(path,mimetype=asset['media_type'],as_attachment=not preview,download_name=asset['original_name'])
        except FileNotFoundError:
            abort(404)
        if preview:
            response.headers['Content-Security-Policy']="default-src 'none'; sandbox"
            response.headers['X-Frame-Options']='DENY'
        response.headers['X-Content-Type-Options']='nosniff'; response.headers['Cache-Control']='private, no-store'
        return response
