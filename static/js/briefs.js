(() => {
    const dialog = document.getElementById("delete-draft-dialog");
    const form = document.getElementById("delete-draft-form");
    if (!dialog || !form || typeof dialog.showModal !== "function") return;

    let trigger;
    document.querySelectorAll("[data-delete-draft]").forEach((link) => {
        link.addEventListener("click", (event) => {
            // Preserve normal link behavior for opening a confirmation page in another tab.
            if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            trigger = link;
            document.getElementById("delete-draft-name").textContent = link.dataset.briefTitle;
            form.action = link.href;
            dialog.showModal();
        });
    });

    dialog.addEventListener("close", () => {
        if (trigger && trigger.isConnected) trigger.focus();
    });
})();
