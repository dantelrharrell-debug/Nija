/**
 * Legacy subscription tiers and checkout are disabled pending store-policy
 * review and a verified native billing implementation.
 */
function showSubscriptionModal() {
    if (document.getElementById('subscription-modal')) return;
    const modal = document.createElement('div');
    modal.id = 'subscription-modal';
    modal.className = 'subscription-modal active';
    const panel = document.createElement('div');
    panel.className = 'subscription-modal-content';
    const heading = document.createElement('h2');
    heading.textContent = 'Mobile purchases unavailable';
    const message = document.createElement('p');
    message.textContent = 'In-app subscriptions are not available while store billing and verification are being prepared. No purchase has been made.';
    const close = document.createElement('button');
    close.textContent = 'Close';
    close.addEventListener('click', closeSubscriptionModal);
    panel.append(heading, message, close);
    modal.appendChild(panel);
    document.body.appendChild(modal);
}
function closeSubscriptionModal() {
    document.getElementById('subscription-modal')?.remove();
}
