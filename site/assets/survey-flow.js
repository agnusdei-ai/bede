/* Progressive enhancement: without this script, the complete form is visible.
   No browser storage or network calls; feedback-form.js owns delivery. */
(() => {
  const survey = document.querySelector('.survey-flow');
  if (!survey) return;
  const steps = [...survey.querySelectorAll('.survey-step')];
  const back = survey.querySelector('#survey-back');
  const next = survey.querySelector('#survey-next');
  const send = survey.querySelector('#survey-send');
  const progress = survey.querySelector('#survey-progress');
  const review = survey.querySelector('#survey-review');
  let current = 0;

  function validStep() {
    return [...steps[current].querySelectorAll('input, select, textarea')]
      .every(control => control.reportValidity());
  }

  function showStep(focus = true) {
    steps.forEach((step, index) => { step.hidden = index !== current; });
    back.hidden = current === 0;
    next.hidden = current === steps.length - 1;
    send.hidden = current !== steps.length - 1;
    progress.textContent = `Step ${current + 1} of ${steps.length}`;
    if (current === steps.length - 1) {
      review.replaceChildren();
      for (const control of survey.querySelectorAll('[name="setting"], [name="experience"], [name="impression"], [name="needs"]')) {
        const label = survey.querySelector(`label[for="${control.id}"]`);
        const line = document.createElement('p');
        const title = document.createElement('strong');
        title.textContent = label.textContent.replace(/\s*\((?:optional|required)\)/g, '') + ': ';
        line.append(title, document.createTextNode(control.value.trim() || 'Not answered'));
        review.append(line);
      }
      review.hidden = false;
    }
    if (focus) steps[current].querySelector('h2').focus();
  }
  back.addEventListener('click', () => { if (current > 0) { current--; showStep(); } });
  next.addEventListener('click', () => {
    if (validStep() && current < steps.length - 1) { current++; showStep(); }
  });
  // Enter advances the current step; never submit before the review screen.
  survey.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target.matches('input:not([type="checkbox"]), select') && current < steps.length - 1) {
      event.preventDefault();
      next.click();
    }
  });
  survey.addEventListener('submit', event => {
    if (current !== steps.length - 1 || !validStep()) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
  showStep(false);
})();
