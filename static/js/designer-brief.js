(() => {
    'use strict';
    const current=document.querySelector('.designer-current-sections, .designer-legacy-responses');
    document.querySelectorAll('[data-expand-sections]').forEach(button=>button.addEventListener('click',()=>{
        const open=button.dataset.expandSections==='open';
        if (!current) return;
        if (current.tagName==='DETAILS') current.open=open;
        current.querySelectorAll('details').forEach(section=>{section.open=open;});
    }));
    document.querySelectorAll('[data-reveal-answer]').forEach(link=>link.addEventListener('click',event=>{
        const target=document.getElementById(link.hash.slice(1));
        if (!target) return;
        event.preventDefault();
        for (let parent=target.parentElement;parent;parent=parent.parentElement) if(parent.tagName==='DETAILS') parent.open=true;
        target.tabIndex=-1;target.focus({preventScroll:true});
        target.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
    }));
    document.querySelectorAll('[data-focus-review-note]').forEach(link=>link.addEventListener('click',()=>{
        const note=document.getElementById('provider-comment');
        if(note) requestAnimationFrame(()=>note.focus({preventScroll:true}));
    }));
    const dialog=document.getElementById('designer-decision-dialog');
    if (!dialog) return;
    const confirm=dialog.querySelector('[data-confirm-decision]');
    const cancel=dialog.querySelector('[data-cancel-decision]');
    const dialogStatus=dialog.querySelector('.designer-dialog-status');
    let selectedForm,selectedButton,decision,busy=false;
    const approval=value=>value==='approved' || value==='approve';
    document.querySelectorAll('.designer-decision-form').forEach(form=>{
        form.noValidate=true;
        const verified=form.querySelector('[name=verified]');
        const approve=form.querySelector('button[value=approved]');
        if(verified && approve) verified.addEventListener('change',()=>{
            approve.disabled=form.dataset.blocked==='true' || !verified.checked;
        });
        form.addEventListener('submit',event=>{
            if(form.dataset.confirmed==='true') {
                if(form.dataset.sending==='true') {event.preventDefault();return;}
                form.dataset.sending='true';
                form.querySelectorAll('button[type=submit]').forEach(button=>button.disabled=true);
                const status=form.querySelector('.designer-decision-status');if(status) status.textContent='Recording your review...';
                return;
            }
            event.preventDefault();
            if(busy || !event.submitter || event.submitter.disabled) return;
            decision=event.submitter.value;
            const note=form.querySelector('textarea');
            if(form.id==='designer-decision-form' && note) note.required=!approval(decision);
            if(note?.required && !note.value.trim()) {note.setCustomValidity('Add feedback so the client knows what to change.');note.reportValidity();note.addEventListener('input',()=>note.setCustomValidity(''),{once:true});return;}
            if(!form.reportValidity())return;
            selectedForm=form;selectedButton=event.submitter;
            dialog.querySelector('#designer-decision-title').textContent=approval(decision)?'Approve this brief for design?':'Request a revision?';
            dialog.querySelector('#designer-decision-description').textContent=approval(decision)?'Your approval and review note will be recorded. The client questionnaire will remain read-only.':'Your feedback will be recorded and the client will be able to revise and resubmit their brief.';
            confirm.textContent=approval(decision)?'Confirm approval':'Send revision request';
            dialogStatus.textContent='';confirm.disabled=false;dialog.showModal();cancel.focus();
        });
    });
    cancel.addEventListener('click',()=>{if(!busy) dialog.close();});
    dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
    dialog.addEventListener('close',()=>{selectedButton?.focus();});
    confirm.addEventListener('click',async()=>{
        if(busy || !selectedForm)return;
        busy=true;confirm.disabled=true;dialogStatus.textContent='Checking the latest review...';
        const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000);
        try {
            const response=await fetch(selectedForm.action,{credentials:'same-origin',cache:'no-store',signal:controller.signal});
            if(response.redirected && new URL(response.url).pathname.includes('/login'))throw new Error('Please sign in again in another tab, then retry. Your review note is still here.');
            if(!response.ok)throw new Error('We could not refresh this review. Your note is still here. Please try again.');
            const documentCopy=new DOMParser().parseFromString(await response.text(),'text/html');
            const latest=documentCopy.getElementById(selectedForm.id);
            if(!latest || (selectedForm.dataset.submissionId!==undefined && latest.dataset.submissionId!==selectedForm.dataset.submissionId) || latest.dataset.canReview==='false')throw new Error('This brief has changed since you opened it. Keep a copy of your note, then reload to review the latest version.');
            if(approval(decision) && latest.dataset.blocked==='true')throw new Error('The latest brief has details needing clarification before approval.');
            const token=latest.querySelector('[name=csrf_token]')?.value;
            if(!token)throw new Error('We could not refresh the security check. Your note is still here. Please try again.');
            selectedForm.querySelector('[name=csrf_token]').value=token;
            const field=document.createElement('input');field.type='hidden';field.name='decision';field.value=decision;selectedForm.append(field);
            selectedForm.dataset.confirmed='true';dialog.close();selectedForm.requestSubmit();
        } catch(error) {
            dialogStatus.textContent=error.name==='AbortError'?'The check took too long. Your note is still here. Please try again.':error.message;
            confirm.disabled=false;
        } finally {clearTimeout(timeout);busy=false;}
    });
})();
