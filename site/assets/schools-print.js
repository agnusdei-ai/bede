/* Accessible print action in an external file to satisfy the site's CSP. */
document.getElementById('print-school-budget')?.addEventListener('click', () => window.print());
