(() => {
    'use strict';
    const form=document.querySelector('.review-submit-form');
    if (!form) return;
    const confirmation=form.querySelector('[name="confirm"]');
    const button=form.querySelector('#review-submit');
    const label=button.querySelector('[data-submit-label]');
    const arrow=button.querySelector('[data-submit-arrow]');
    const spinner=button.querySelector('.submission-spinner');
    const status=form.querySelector('.submission-status');
    const errorPanel=form.querySelector('.submission-error');
    const recovery=form.querySelector('.submission-recovery');
    const signIn=form.querySelector('.submission-sign-in');
    const latest=form.querySelector('.submission-latest-review');
    const eligible=form.dataset.canSubmit==='true';
    const reviewedGeneration=Number(form.dataset.generation);
    const previousSubmission=Number(form.dataset.lastSubmissionId);
    const idleLabel=label.textContent;
    let busy=false,blocked=false;

    class SubmissionError extends Error {
        constructor(code,message) {super(message);this.code=code;}
    }
    function sync() {
        button.disabled=busy || blocked || !eligible || !confirmation.checked;
        confirmation.disabled=busy || !eligible;
        button.setAttribute('aria-busy',String(busy));
        label.textContent=busy ? 'Submitting...' : idleLabel;
        spinner.hidden=!busy;arrow.hidden=busy;
    }
    function clearError() {errorPanel.hidden=true;errorPanel.textContent='';recovery.hidden=true;signIn.hidden=true;latest.hidden=true;}
    function failure(error) {
        const code=error.code;
        errorPanel.textContent=error.message || 'We could not confirm submission. Your saved answers are safe. Please try again.';
        errorPanel.hidden=false;
        signIn.hidden=code!=='session_expired';
        latest.hidden=!['submission_conflict','brief_incomplete','revision_response_required'].includes(code);
        recovery.hidden=signIn.hidden && latest.hidden;
        blocked=!latest.hidden;
        status.textContent='Submission has not been confirmed. Your brief has been kept.';
        errorPanel.focus({preventScroll:true});
    }
    async function requestJSON(url,options={}) {
        const controller=new AbortController();
        const timeout=setTimeout(()=>controller.abort(),15000);
        try {
            const response=await fetch(url,{credentials:'same-origin',cache:'no-store',...options,signal:controller.signal});
            if (response.redirected) throw new SubmissionError('session_expired','Please sign in again in another tab, then retry here. Your saved brief is safe.');
            let body;
            try {body=JSON.parse(await response.text());} catch {body=null;}
            if (!response.ok) {
                const code=body?.code || (response.status===401 ? 'session_expired' : response.status===409 ? 'submission_conflict' : 'submission_unavailable');
                const messages={
                    session_expired:'Please sign in again in another tab, then retry here. Your saved brief is safe.',
                    csrf_refresh_required:'Your security check needs refreshing. Please try submitting again.',
                    submission_conflict:'Your brief has changed or has already been submitted. Check the latest saved brief before trying again.',
                    brief_incomplete:'A few required details still need attention. Continue editing your brief, then review it again.',
                    revision_response_required:'Add a short note about your revisions before resubmitting.',
                    access_denied:'This account cannot submit this brief. Your saved answers have not been changed.',
                    brief_unavailable:'This brief is unavailable to this account. Your saved answers have not been changed.'
                };
                throw new SubmissionError(code,messages[code] || 'We could not submit your brief right now. Your saved answers are safe. Please try again.');
            }
            if (!body || typeof body!=='object') throw new SubmissionError('unexpected_response','We could not confirm submission. Your saved brief is safe. Please try again.');
            return body;
        } catch(error) {
            if (error instanceof SubmissionError) throw error;
            throw new SubmissionError('network_error','We could not reach Elunette to confirm submission. Your saved brief is safe. Check your connection and try again.');
        } finally {clearTimeout(timeout);}
    }
    function matchingReceipt(state) {
        return state.generation===reviewedGeneration && ['submitted','under_review','approved'].includes(state.status) && Number.isInteger(state.receipt?.submission_id) && state.receipt.submission_id>previousSubmission;
    }
    function confirmed(url) {
        const destination=new URL(url,location.origin);
        if (destination.origin!==location.origin || !destination.pathname.endsWith('/confirmation')) throw new SubmissionError('unexpected_response','We could not open your submission receipt. Return to your Studio to check its status.');
        status.textContent='Your brief has been submitted. Opening your confirmation...';
        location.assign(destination.href);
    }
    async function preflight() {
        const state=await requestJSON(form.dataset.stateUrl);
        if (matchingReceipt(state)) return {receipt:state.receipt};
        if (state.generation!==reviewedGeneration || !['draft','revision_requested'].includes(state.status)) throw new SubmissionError('submission_conflict','Your brief has changed since you reviewed it. Your newer answers are safe. Check the latest saved brief before submitting.');
        if (!state.can_submit) throw new SubmissionError('brief_incomplete','Your brief needs a few more details. Continue editing it, then return here to review.');
        if (typeof state.csrf_token!=='string') throw new SubmissionError('unexpected_response','We could not refresh your security check. Your saved brief is safe. Please try again.');
        return {csrf_token:state.csrf_token};
    }
    confirmation.addEventListener('change',()=>{sync();if (!busy && !blocked) status.textContent=confirmation.checked ? 'Ready when you are.' : 'Confirm above to enable submission.';});
    form.addEventListener('submit',async event=>{
        event.preventDefault();
        if (busy || blocked || !eligible || !confirmation.checked || !form.checkValidity()) return;
        const payload=new FormData(form);
        busy=true;clearError();sync();status.textContent='Submitting your brief securely...';
        let attempted=false;
        try {
            let state=await preflight();
            if (state.receipt) {confirmed(state.receipt.confirmation_url);return;}
            let result;
            for (let attempt=0;attempt<2;attempt++) {
                payload.set('csrf_token',state.csrf_token);
                try {
                    attempted=true;
                    result=await requestJSON(form.action,{method:'POST',headers:{Accept:'application/json','X-CSRFToken':state.csrf_token},body:payload});
                    break;
                } catch(error) {
                    if (error.code!=='csrf_refresh_required' || attempt!==0) throw error;
                    state=await preflight();
                    if (state.receipt) {confirmed(state.receipt.confirmation_url);return;}
                }
            }
            if (result.ok!==true || result.status!=='submitted' || result.generation!==reviewedGeneration || !Number.isInteger(result.submission_id)) throw new SubmissionError('unexpected_response','We could not confirm submission. Your saved answers are safe. Please try again.');
            confirmed(result.confirmation_url);
        } catch(error) {
            if (attempted) {
                try {
                    const state=await requestJSON(form.dataset.stateUrl);
                    if (matchingReceipt(state)) {confirmed(state.receipt.confirmation_url);return;}
                } catch { /* A receipt must be positively verified before reporting success. */ }
            }
            busy=false;failure(error);sync();
        }
    });
    sync();
})();
