(() => {
    const invitation = document.getElementById('studio-invitation');
    if (!invitation || typeof invitation.showModal !== 'function') return;
    const previousFocus = document.activeElement;
    let dismissing = false;
    const dismiss = () => {
        if (!invitation.open || dismissing) return;
        dismissing = true;
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || typeof invitation.getAnimations !== 'function') {
            invitation.close();
            return;
        }
        invitation.classList.add('is-dismissing');
        // Native modality/focus isolation stays active until the CSS reveal ends.
        // Animation completion is event-driven: no timers or navigation delay.
        const transitions = invitation.getAnimations();
        Promise.allSettled(transitions.map(animation => animation.finished)).then(() => {
            if (invitation.open) invitation.close();
        });
    };
    invitation.querySelector('.invitation-close').addEventListener('click', dismiss);
    invitation.addEventListener('cancel', event => { event.preventDefault(); dismiss(); });
    invitation.querySelector('.invitation-action').addEventListener('click', event => {
        if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        // The role-checked Studio is already loaded underneath this invitation.
        dismiss();
    });
    invitation.addEventListener('close', () => {
        if (previousFocus && previousFocus !== document.body && previousFocus.isConnected) {
            previousFocus.focus();
        } else {
            const heading = document.querySelector('#studio-main h1');
            if (heading) {
                const hadTabindex = heading.hasAttribute('tabindex');
                if (!hadTabindex) heading.setAttribute('tabindex', '-1');
                heading.focus({ preventScroll: true });
                if (!hadTabindex) heading.addEventListener('blur', () => heading.removeAttribute('tabindex'), { once: true });
            }
        }
    });
    // A cached back/forward page must not replay an already consumed invitation.
    window.addEventListener('pageshow', (event) => { if (event.persisted && invitation.open) invitation.close(); });
    invitation.showModal();
})();
