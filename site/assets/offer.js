// The home page's membership chooser (#membership in index.html).
//
// Everything that matters works without this file: plans are native radio
// inputs styled by site.css, and every button is an ordinary link. This only
// adds two conveniences:
//   1. the per-child figure under the annual plan follows the slider, and
//   2. a click anywhere on a plan card chooses it, not just on its heading.
// Served as its own file (not inline) so the site's CSP can keep
// script-src 'self' with no 'unsafe-inline' (see site/_headers).
(function () {
  'use strict';

  // Annual price, from the page's own data-annual attribute, divided by
  // twelve months and by the number of children (the slider's own min/max).
  function perChildMonthly(annual, children) {
    return Math.round((annual / 12 / children) * 100) / 100;
  }

  function money(v) {
    return '$' + v.toFixed(2);
  }

  var box = document.querySelector('.per-child');
  if (box) {
    var annual = Number(box.getAttribute('data-annual'));
    var range = box.querySelector('input[type=range]');
    var count = box.querySelector('.per-child-n');
    var amount = box.querySelector('.per-child-amount');
    var update = function () {
      var n = Number(range.value);
      count.textContent = String(n);
      amount.textContent = money(perChildMonthly(annual, n));
    };
    if (range && count && amount && annual > 0) {
      range.addEventListener('input', update);
      update();
    }
  }

  var plans = document.querySelectorAll('.offer .plan');
  for (var i = 0; i < plans.length; i++) {
    plans[i].addEventListener('click', function (e) {
      // Links and the slider keep their own behaviour.
      if (e.target.closest('a, input[type=range], label')) return;
      var radio = this.querySelector('.plan-radio');
      if (radio && !radio.checked) {
        radio.checked = true;
        radio.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
  }
})();
