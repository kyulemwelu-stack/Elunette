(() => {
    const invitation = document.getElementById('studio-invitation');
    if (!invitation || typeof invitation.showModal !== 'function') return;
    const previousFocus = document.activeElement;
    invitation.querySelector('.invitation-close').addEventListener('click', () => invitation.close());
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
