(() => {
'use strict';
const data = JSON.parse(document.getElementById('adaptive-data').textContent);
const form = document.getElementById('adaptive-form');
let csrf = document.querySelector('meta[name="csrf-token"]').content;
const status = document.getElementById('save-status');
const groups = data.groups;
const navigationParams=new URLSearchParams(location.search);
const returningToReview=navigationParams.get('return_to')==='review';
let generation = data.generation, sectionIndex = 0, timer, saving = null, rowCounter = 0;
let dirty = false, previousActive='', currentGroupId=groups[0]?.id, visibleGroups=[], validationErrors={}, editVersion=0;
let uncertainSave=null, lastSaveResult=null, uploadsInFlight=0, reviewing=false;
const recovery=document.getElementById('save-recovery');
const signIn=document.getElementById('save-sign-in');
const fieldNodes = [...form.querySelectorAll('[data-field]')];
const empty = value => value == null || value === '' || (Array.isArray(value) && !value.length);
function condition(p, answers) {
  if (!p) return true;
  if (p.all) return p.all.every(item => condition(item, answers));
  if (p.any) return p.any.some(item => condition(item, answers));
  const value = answers[p.field];
  if (empty(value)) return false;
  switch (p.op) {
    case 'eq': return value === p.value;
    case 'ne': return value !== p.value;
    case 'in': return p.values.includes(value);
    case 'not_in': return !p.values.includes(value);
    case 'contains': return Array.isArray(value) && value.includes(p.value);
    case 'not_empty': return true;
    default: throw new Error('Unsupported questionnaire condition');
  }
}
function read(node) {
  switch (node.dataset.kind) {
    case 'multi_choice': return [...node.querySelectorAll('input:checked')].map(input => input.value);
    case 'color_multi_picker': return [...node.querySelectorAll('[data-hex]')].map(input => input.value.trim());
    case 'money': {
      const amount=node.querySelector('[data-amount]').value.trim();
      return amount ? {amount, currency:node.querySelector('[data-currency]').value.trim().toUpperCase()} : null;
    }
    case 'repeater': return [...node.querySelector('.rows').children].map(row => Object.fromEntries([...row.querySelectorAll('[data-input]')].filter(child => child.closest('.repeat-row')===row).map(child => [child.dataset.input,read(child)])));
    case 'boolean': return node.checked;
    case 'integer': return node.value === '' ? null : Number(node.value);
    case 'asset_reference': case 'file_upload': return node.value ? Number(node.value) : null;
    default: return node.value.trim();
  }
}
function answers() {
  return Object.fromEntries(fieldNodes.map(node => { const input=node.querySelector('[data-input]'); return [node.dataset.field,read(input)]; }));
}
function active(all) {
  const fields=groups.flatMap(group => group.fields.map(field => ({field,group})));
  let enabled = new Set();
  for (let n=0;n<=fields.length;n++) {
    const context=Object.fromEntries(Object.entries(all).filter(([key]) => enabled.has(key)));
    const next = new Set(fields.filter(({field,group}) => condition(group.when,context) && condition(field.when,context)).map(({field}) => field.id));
    if (next.size===enabled.size && [...next].every(key => enabled.has(key))) return next;
    enabled=next;
  }
  throw new Error('Cyclic questionnaire conditions');
}
function completeField(field, value) {
  if (empty(value)) return false;
  if (field.type==='repeater') return value.every(row => field.item_fields.every(child => !condition(child.when,row) || !child.required || completeField(child,row[child.id])));
  if (field.type==='money') return !!value.amount && Number.isFinite(Number(value.amount)) && Number(value.amount)>=0 && /^[A-Z]{3}$/.test(value.currency);
  if (field.type==='color_multi_picker') return value.every(colour => /^#[0-9a-f]{6}$/i.test(colour));
  return true;
}
function update() {
  const all=answers(), enabled=active(all);
  const signature=[...enabled].join(',');
  if (previousActive && signature!==previousActive) document.getElementById('visibility-status').textContent='Your questions have updated to match your answers.';
  previousActive=signature;
  for (const node of fieldNodes) {
    const newlyVisible=node.hidden && enabled.has(node.dataset.field);
    node.hidden=!enabled.has(node.dataset.field);
    if (newlyVisible) {node.classList.remove('field-reveal'); void node.offsetWidth; node.classList.add('field-reveal');}
    const input=node.querySelector('[data-input]');
    input.setAttribute('aria-describedby','error-'+node.dataset.field);
    const label=node.querySelector('.question-label'); label.id='label-'+node.dataset.field;
    input.setAttribute('aria-labelledby',label.id);
    const field=groups.flatMap(group=>group.fields).find(field=>field.id===node.dataset.field);
    input.setAttribute('aria-required',String(!!field.required && enabled.has(field.id)));
    if (input.tagName==='DIV') input.setAttribute('role','group');
    for (const radio of node.querySelectorAll('[data-choice]')) radio.checked=radio.value===input.value;
    for (const palette of node.querySelectorAll('[data-palette]')) palette.setAttribute('aria-pressed',String(palette.dataset.palette===input.value));
  }
  visibleGroups=groups.filter(group => group.fields.some(field => enabled.has(field.id)));
  const preserved=visibleGroups.findIndex(group=>group.id===currentGroupId);
  sectionIndex=preserved>=0 ? preserved : Math.min(sectionIndex,visibleGroups.length-1);
  currentGroupId=visibleGroups[sectionIndex]?.id;
  const current=visibleGroups[sectionIndex];
  for (const node of form.querySelectorAll('.wizard-section')) node.hidden=node.dataset.section!==currentGroupId;
  const selection=document.getElementById('section-select');
  const hadFocus=document.activeElement===selection;
  selection.replaceChildren();
  visibleGroups.forEach((group,index) => {
    const applicable=group.fields.filter(field=>enabled.has(field.id));
    const required=applicable.filter(field=>field.required);
    const done=required.every(field=>completeField(field,all[field.id]) && !validationErrors[field.id]) && (required.length>0 || applicable.some(field=>!empty(all[field.id])));
    const state=index===sectionIndex ? 'Current' : done ? 'Complete' : 'To do';
    const option=new Option(`${String(index+1).padStart(2,'0')} \u00b7 ${group.title} \u2014 ${state}`,group.id,index===sectionIndex,index===sectionIndex);
    option.dataset.state=state.toLowerCase().replace(' ','-');
    selection.add(option);
    const heading=document.querySelector(`[data-section="${group.id}"] .section-position`);
    heading.textContent=`Step ${String(index+1).padStart(2,'0')} / ${String(visibleGroups.length).padStart(2,'0')}`;
  });
  if (hadFocus) selection.focus();
  document.getElementById('current-step').textContent=`Step ${sectionIndex+1} of ${visibleGroups.length}`;
  selection.setAttribute('aria-label',`Current section: ${current?.title}. Choose another section`);
  const required=groups.flatMap(group=>group.fields).filter(field=>enabled.has(field.id) && field.required);
  const percent=required.length ? Math.round(100*required.filter(field=>completeField(field,all[field.id]) && !validationErrors[field.id]).length/required.length) : 100;
  document.getElementById('completion').value=percent;
  document.getElementById('progress-label').textContent=percent+'%';
  document.getElementById('back').disabled=sectionIndex<=0;
  const last=sectionIndex===visibleGroups.length-1;
  document.getElementById('next-label').textContent=last ? 'Review brief' : 'Continue';
  document.getElementById('review').hidden=last && !returningToReview;
  document.getElementById('review').textContent=returningToReview ? 'Save & return to review' : 'Review your brief';
}
function goTo(index) {
  const destination=visibleGroups[index];
  if (!destination) return;
  currentGroupId=destination.id; sectionIndex=index; update(); focusSection();
}
document.getElementById('section-select').addEventListener('change',event=>{
  goTo(visibleGroups.findIndex(group=>group.id===event.target.value));
});
function focusSection() {
  const title=form.querySelector('.wizard-section:not([hidden]) h2');
  if (title) { title.tabIndex=-1; title.focus({preventScroll:true}); title.closest('.wizard-section').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'}); }
}
function showErrors(errors) {
  const panel=document.getElementById('errors'); panel.replaceChildren();
  for (const node of form.querySelectorAll('.field-error')) node.textContent='';
  for (const node of form.querySelectorAll('[aria-invalid]')) node.removeAttribute('aria-invalid');
  for (const [key,message] of Object.entries(errors || {})) {
    const field=groups.flatMap(group=>group.fields).find(item=>item.id===key);
    const line=document.createElement('p'); line.textContent=key.startsWith('_') ? message : (field?.label || 'An answer')+': '+message; panel.append(line);
    const node=fieldNodes.find(node=>node.dataset.field===key);
    const inline=node?.querySelector('.field-error');
    if (inline) {inline.textContent=message;node.querySelector('[data-input]').setAttribute('aria-invalid','true');}
  }
}
class SaveError extends Error {
  constructor(code,message,errors) {super(message);this.code=code;this.errors=errors || {_form:message};}
}
function responseError(response,body) {
  const messages={
    400:'We could not save these changes. Your answers are still on this page.',
    401:'Please sign in again in another tab, then try saving here. Your answers are still on this page.',
    403:'This account cannot edit this brief. Your answers are still on this page.',
    404:'This brief is unavailable to this account. Your answers are still on this page.',
    409:'A newer version was saved, or this brief is no longer editable. Your changes are still here; download a copy before reloading.',
    413:'This request is too large. Your answers are still on this page.',
    500:'We could not save your draft right now. Your answers are still here. Please try again.',
    503:'Saving is temporarily unavailable. Your answers are still here. Please try again.'
  };
  const code=body?.code || (response.status===401 ? 'session_expired' : response.status===409 ? 'draft_conflict' : 'save_unavailable');
  return new SaveError(code,messages[response.status] || 'Saving is temporarily unavailable. Your answers are still on this page.',body?.errors);
}
async function requestJSON(url,options={}) {
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),15000);
  try {
    const response=await fetch(url,{credentials:'same-origin',cache:'no-store',...options,signal:controller.signal});
    if (response.redirected) throw new SaveError('session_expired','Please sign in again in another tab, then try saving here. Your answers are still on this page.');
    const text=await response.text();
    let body;
    try {body=JSON.parse(text);} catch {if (!response.ok) throw responseError(response);throw new SaveError('unexpected_response','We could not confirm that your draft was saved. Your answers are still here. Please try again.');}
    if (!response.ok) throw responseError(response,body);
    return body;
  } catch(error) {
    if (error instanceof SaveError) throw error;
    throw new SaveError('network_error','We could not reach Elunette to confirm saving. Your answers are still here. Check your connection and try again.');
  } finally {clearTimeout(timeout);}
}
// Compare normalized storage shapes only to acknowledge an uncertain previous
// write. Never use a newer server generation to overwrite different answers.
function storageShape(value) {
  if (Array.isArray(value)) return value.map(storageShape);
  if (value && typeof value==='object') return Object.fromEntries(Object.keys(value).sort().filter(key=>!empty(value[key]) && !(typeof value[key]==='object' && !Array.isArray(value[key]) && !Object.keys(value[key]).length)).map(key=>[key,storageShape(value[key])]));
  return value;
}
function acknowledge(body,version) {
  if (!Number.isInteger(body.generation) || !body.assessment || !Number.isFinite(body.assessment.percentage)) throw new SaveError('unexpected_response','We could not confirm that your draft was saved. Your answers are still here. Please try again.');
  generation=body.generation;dirty=editVersion!==version;lastSaveResult=body;
  if (!dirty) {
    validationErrors=body.assessment.errors;update();
    document.getElementById('completion').value=body.assessment.percentage;
    document.getElementById('progress-label').textContent=body.assessment.percentage+'%';
  }
  recovery.hidden=true;signIn.hidden=true;showErrors({});
  status.textContent=dirty ? 'Saving your latest changes...' : 'Draft saved. Come back whenever you are ready.';
}
async function saveNow() {
  status.textContent='Saving your draft...';
  const state=await requestJSON(data.stateUrl);
  if (!Number.isInteger(state.generation) || typeof state.csrf_token!=='string') throw new SaveError('unexpected_response','We could not confirm your saved version. Your answers are still on this page.');
  csrf=state.csrf_token;
  if (state.generation!==generation) {
    const previous=uncertainSave;
    if (previous && state.generation===previous.payload.generation+1 && state.revision_response===previous.payload.revision_response && JSON.stringify(storageShape(state.answers))===JSON.stringify(storageShape(previous.payload.answers))) {
      acknowledge(state,previous.version);uncertainSave=null;
      if (!dirty) return state;
    } else {
      throw new SaveError('draft_conflict','A newer version was saved in another tab. Your changes are still here. Download a copy before reloading; we will not overwrite the newer version.');
    }
  }
  const version=editVersion;
  const payload={answers:answers(),generation,revision_response:document.getElementById('revision-response')?.value || ''};
  uncertainSave={payload,version};
  let body;
  for (let attempt=0;attempt<2;attempt++) {
    try {
      body=await requestJSON(data.saveUrl,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify(payload)});
      break;
    } catch(error) {
      if (error.code!=='csrf_refresh_required' || attempt!==0) throw error;
      const refreshed=await requestJSON(data.stateUrl);
      if (refreshed.generation!==generation) throw new SaveError('draft_conflict','A newer version has been saved. Your changes are still here; download a copy before reloading.');
      csrf=refreshed.csrf_token;
    }
  }
  acknowledge(body,version);uncertainSave=null;
  return body;
}
function save() {
  clearTimeout(timer);
  if (saving) return saving;
  if (!dirty && lastSaveResult) return Promise.resolve(lastSaveResult);
  saving=(async()=>{
    let body;
    do {body=await saveNow();} while (dirty);
    return body;
  })().catch(error=>{
    dirty=true;recovery.hidden=false;signIn.hidden=error.code!=='session_expired';
    showErrors(error.errors || {_form:'We could not confirm saving. Your answers are still on this page. Please try again.'});
    status.textContent=error.code==='session_expired' ? 'Sign in again to save. Keep this tab open.' : error.code==='draft_conflict' ? 'A newer version exists. Your changes have been kept on this page.' : 'Not saved yet. Your changes are still on this page.';
    throw error;
  }).finally(()=>{saving=null;});
  return saving;
}
document.getElementById('download-unsaved').addEventListener('click',()=>{
  const snapshot={project:document.querySelector('h1').textContent,answers:answers(),revision_response:document.getElementById('revision-response')?.value || '',saved_at:new Date().toISOString(),note:'A copy of the answers currently on this page; this does not confirm a server save.'};
  const url=URL.createObjectURL(new Blob([JSON.stringify(snapshot,null,2)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download='elunette-unsaved-answers.json';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
});
function changed(event) {
  if (event?.target?.matches('[data-choice]')) event.target.closest('[data-field]').querySelector('select[data-input]').value=event.target.value;
  if (event?.target?.type==='color') event.target.closest('label').querySelector('[data-hex]').value=event.target.value.toUpperCase();
  if (event?.target?.hasAttribute('data-hex') && /^#[0-9a-f]{6}$/i.test(event.target.value)) event.target.closest('label').querySelector('[type="color"]').value=event.target.value;
  editVersion++;
  const key=event?.target?.closest('[data-field]')?.dataset.field;
  if (key) delete validationErrors[key];
  dirty=true; update(); clearTimeout(timer); timer=setTimeout(()=>save().catch(()=>{}),1800);
}
form.addEventListener('submit',event=>event.preventDefault());
form.addEventListener('input',changed);
form.addEventListener('change',event=>{
  if (event.target.matches('[data-choice]')) event.target.closest('[data-field]').querySelector('select[data-input]').value=event.target.value;
  if (event.target.matches('select[data-kind=file_upload],select[data-kind=asset_reference]')) {
    const upload=event.target.closest('.child-field, .adaptive-field').querySelector('[data-upload]');
    if (upload) {delete upload.dataset.uploadFailed;upload.value='';}
  }
  changed(event);
});
form.addEventListener('click',event=>{
  const button=event.target.closest('button'); if (!button) return;
  if (button.classList.contains('add-row')) {
    const repeater=button.closest('[data-kind="repeater"]');
    if (repeater.querySelector('.rows').children.length>=Number(repeater.dataset.max)) return;
    const fragment=repeater.querySelector('template').content.cloneNode(true); const suffix=String(++rowCounter);
    for (const node of fragment.querySelectorAll('[id]')) node.id=node.id.replace('-NEW-','-new'+suffix+'-');
    for (const node of fragment.querySelectorAll('[for]')) node.htmlFor=node.htmlFor.replace('-NEW-','-new'+suffix+'-');
    repeater.querySelector('.rows').append(fragment); changed();
  }
  if (button.classList.contains('remove-row')) { button.closest('.repeat-row').remove(); changed(); }
  if (button.dataset.palette) {
    const field=button.closest('[data-field]'); field.querySelector('select').value=button.dataset.palette;
    for (const choice of field.querySelectorAll('[data-palette]')) choice.setAttribute('aria-pressed',String(choice===button)); changed({target:button});
  }
  if (button.classList.contains('add-colour')) {
    const rows=button.parentElement.querySelector('.colour-rows'); if (rows.children.length>=40) return;
    const label=document.createElement('label'); label.append('HEX colour ');
    const colour=document.createElement('input'); colour.type='color'; colour.value='#653d30'; colour.setAttribute('aria-label','Choose colour');
    const hex=document.createElement('input'); hex.dataset.hex=''; hex.value='#653D30'; hex.setAttribute('aria-label','HEX value');
    const remove=document.createElement('button'); remove.type='button'; remove.className='remove-colour'; remove.textContent='Remove colour';
    label.append(colour,hex,remove); rows.append(label); changed();
  }
  if (button.classList.contains('remove-colour')) { button.closest('label').remove(); changed(); }
});
form.addEventListener('input',event=>{
  if (event.target.type==='color') event.target.closest('label').querySelector('[data-hex]').value=event.target.value.toUpperCase();
  if (event.target.hasAttribute('data-hex') && /^#[0-9a-f]{6}$/i.test(event.target.value)) event.target.closest('label').querySelector('[type="color"]').value=event.target.value;
});
form.addEventListener('change',async event=>{
  const input=event.target; if (!input.dataset.upload) return;
  if (!input.files.length) {delete input.dataset.uploadFailed;return;}
  uploadsInFlight++;delete input.dataset.uploadFailed;
  const note=input.parentElement.querySelector('.upload-status'); note.textContent='Uploading…';
  const upload=new FormData(); upload.append('file',input.files[0]);
  try {
    const state=await requestJSON(data.stateUrl);csrf=state.csrf_token;
    const asset=await requestJSON(data.uploadUrl,{method:'POST',headers:{'X-CSRFToken':csrf},body:upload});
    for (const select of form.querySelectorAll('select[data-kind="file_upload"],select[data-kind="asset_reference"]')) select.add(new Option(asset.name,String(asset.id)));
    const target=input.closest('.child-field, .adaptive-field').querySelector('select'); target.value=asset.id;
    note.textContent='Uploaded '+asset.name; changed();
  } catch (error) { input.dataset.uploadFailed='true';note.textContent=error.message; }
  finally {uploadsInFlight--;if (!uploadsInFlight) form.dispatchEvent(new Event('adaptive-uploads-finished'));}
});
document.getElementById('back').onclick=()=>goTo(sectionIndex-1);
document.getElementById('next').onclick=()=>{if (sectionIndex===visibleGroups.length-1) openReview(); else goTo(sectionIndex+1);};
document.getElementById('save').onclick=()=>{clearTimeout(timer);save().catch(()=>{});};
async function openReview() {
  if (reviewing) return;
  reviewing=true;clearTimeout(timer);
  try {
    if (uploadsInFlight) {
      status.textContent='Finishing your uploads before saving...';
      await new Promise(resolve=>form.addEventListener('adaptive-uploads-finished',resolve,{once:true}));
    }
    if (form.querySelector('[data-upload-failed=true]')) {
      status.textContent='Please retry your upload or choose a saved file before reviewing. Your answers are still here.';
      showErrors({_form:status.textContent});return;
    }
    await save();location.assign(data.reviewUrl);
  } catch { /* Saving already explains the problem and preserves this page. */ }
  finally {reviewing=false;}
}
document.getElementById('review').onclick=openReview;
window.addEventListener('beforeunload',event=>{ if(dirty) {event.preventDefault();event.returnValue='';} });
update();
const requestedQuestion=navigationParams.get('question');
if (requestedQuestion) {
  const target=fieldNodes.find(node=>node.dataset.field===requestedQuestion);
  const enabled=active(answers());
  if (target && enabled.has(requestedQuestion)) {
    const section=target.closest('[data-section]');
    currentGroupId=section.dataset.section;update();
    requestAnimationFrame(()=>{
      const control=[...target.querySelectorAll('input,select,textarea,button')].find(node=>!node.disabled && node.getAttribute('aria-hidden')!=='true' && node.getClientRects().length);
      if (control) control.focus({preventScroll:true});
      target.classList.add('review-edit-target');
      target.scrollIntoView({block:'center',behavior:'instant'});
    });
  } else if (requestedQuestion==='revision-response') {
    const response=document.getElementById('revision-response');
    if (response) {response.focus({preventScroll:true});response.scrollIntoView({block:'center',behavior:'instant'});}
  }
}
})();
