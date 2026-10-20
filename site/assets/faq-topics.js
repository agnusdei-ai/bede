/* Native fragment navigation, enhanced only when the target is in a disclosure. */
(() => {
  function reveal(hash) {
    let id;
    try { id = decodeURIComponent(hash.replace(/^#/, "")); }
    catch { return; }
    const target = document.getElementById(id);
    if (!target) return;
    const disclosure = target.closest("details");
    if (!disclosure) return;
    for (let node = target; node; node = node.parentElement) {
      if (node.tagName === "DETAILS") node.open = true;
    }
    const focusTarget = target === disclosure ? disclosure.querySelector("summary") : target;
    if (focusTarget) {
      if (!focusTarget.matches("summary, a[href], button, input, select, textarea, [tabindex]")) {
        focusTarget.setAttribute("tabindex", "-1");
        focusTarget.addEventListener("blur", () => focusTarget.removeAttribute("tabindex"), { once: true });
      }
      focusTarget.focus({ preventScroll: true });
    }
    target.scrollIntoView({ block: "start", behavior: "instant" });
  }
  const revealCurrent = () => reveal(window.location.hash);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", revealCurrent, { once: true });
  else revealCurrent();
  window.addEventListener("hashchange", revealCurrent);
  window.addEventListener("pageshow", revealCurrent);
  // Reopening a closed disclosure via the same fragment does not fire hashchange.
  document.addEventListener("click", event => {
    const link = event.target.closest("a[href]");
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey
      || link.hasAttribute("download") || (link.target && link.target !== "_self")) return;
    const url = new URL(link.href, window.location.href);
    if (url.origin === window.location.origin && url.pathname === window.location.pathname
      && url.search === window.location.search && url.hash === window.location.hash) reveal(url.hash);
  });
  // The review iframe has no page URL of its own; its parent supplies the fragment.
  document.addEventListener("bede-topic-navigation", event => reveal(event.detail));
})();
