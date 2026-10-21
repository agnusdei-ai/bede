/* One business-intake form. No demo login, browser storage, or mailto auto-send. */
(() => {
  'use strict';
  const form = document.getElementById('inquiry-form');
  if (!form) return;
  const audience = form.elements.namedItem('audience');
  const button = document.getElementById('inquiry-send');
  const status = document.getElementById('inquiry-status');
  const routing = document.getElementById('inquiry-routing');
  let sending = false;
  function configureAudience() {
    form.querySelectorAll('[data-audiences]').forEach(section => {
      const active = section.dataset.audiences.split(' ').includes(audience.value);
      section.hidden = !active;
      section.querySelectorAll('input').forEach(input => {
        input.disabled = !active;
        input.required = active;
        if (!active) input.value = '';
      });
    });
    routing.textContent = audience.value === 'homeschool'
      ? 'Email to: bede@agnusdei.ai'
      : audience.value ? 'Email to: info@agnusdei.ai'
        : 'Family: bede@agnusdei.ai. Co-op or school: info@agnusdei.ai.';
  }
  function validateSelections() {
    ['grades', 'interests'].forEach(name => {
      const inputs = [...form.querySelectorAll(`input[name="${name}"]`)];
      inputs[0].setCustomValidity(inputs.some(input => input.checked) ? '' : 'Choose at least one option.');
    });
  }
  const requested = new URLSearchParams(window.location.search).get('audience');
  if (['homeschool', 'coop', 'charter_school'].includes(requested)) audience.value = requested;
  configureAudience();
  validateSelections();
  audience.addEventListener('change', configureAudience);
  form.addEventListener('change', validateSelections);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (sending) return;
    validateSelections();
    if (!form.reportValidity()) return;
    const data = new FormData(form);
    const payload = Object.fromEntries(data);
    payload.grades = data.getAll('grades');
    payload.interests = data.getAll('interests');
    payload.consent = data.get('consent') === 'on';
    ['learners', 'families', 'educators', 'sites'].forEach(name => {
      if (data.has(name)) payload[name] = Number(data.get(name));
    });
    const base = String(window.BEDE_API_BASE || '').replace(/\/+$/, '');
    if (!base) {
      status.textContent = 'Your inquiry has not been sent. Please try again later or email info@agnusdei.ai.';
      status.focus();
      return;
    }
    sending = true;
    button.disabled = true;
    button.textContent = 'Sending inquiry…';
    status.textContent = 'Sending your inquiry…';
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(`${base}/inquiries`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        credentials: 'omit',
        signal: controller.signal,
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.sent !== true) throw new Error('Inquiry not accepted');
      form.hidden = true;
      status.textContent = 'Thank you. Our email service accepted your inquiry. We’ll reply by email.';
    } catch {
      status.textContent = 'Your inquiry was not confirmed as sent. Your answers remain here. Retry or email info@agnusdei.ai. If it timed out, check for a reply first.';
    } finally {
      clearTimeout(timeout);
      sending = false;
      button.disabled = false;
      button.textContent = 'Send inquiry →';
      status.focus();
    }
  });
})();
