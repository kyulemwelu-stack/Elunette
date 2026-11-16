(() => {
    'use strict';
    const form = document.getElementById('new-project-form');
    const provider = document.getElementById('provider');
    const service = document.getElementById('questionnaire');
    const options = document.getElementById('provider-questionnaires');
    const status = document.getElementById('questionnaire-status');
    let pending;
    provider.addEventListener('change', async () => {
        pending?.abort();
        const controller = new AbortController();
        pending = controller;
        if (!service.value.startsWith('service:')) service.value = '';
        options.replaceChildren();
        options.hidden = options.disabled = true;
        status.textContent = '';
        if (!provider.value) return;
        const url = new URL(form.action);
        url.searchParams.set('provider_id', provider.value);
        try {
            const response = await fetch(url, {signal: controller.signal});
            if (!response.ok || response.redirected) throw new Error('Unable to load questionnaires.');
            const page = new DOMParser().parseFromString(await response.text(), 'text/html');
            const available = page.querySelector('#provider-questionnaires');
            if (!available) throw new Error('Unable to load questionnaires.');
            options.replaceChildren(...[...available.children].map(option => option.cloneNode(true)));
            options.hidden = options.disabled = !options.children.length;
        } catch (error) {
            if (error.name !== 'AbortError') status.textContent = 'Provider questionnaires could not load. Refresh the page to try again.';
        }
    });
})();
