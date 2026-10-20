/* Production enhancement: no network calls, storage, forms, or iframe messaging. */
(() => {
  "use strict";
  const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
  const stage = document.querySelector("[data-reading-stage]");
  const targets = document.querySelectorAll(
    ".classical-section-heading, .classical-stages article, .bede-curriculum-entry",
  );
  const played = new WeakSet();
  const animations = new Set();
  let stagePlayed = false;
  let timer;
  let observer;
  const settle = () => {
    clearTimeout(timer);
    stage?.classList.remove("is-playing");
    stage?.classList.add("is-settled");
  };
  function playBook() {
    if (!stage || stagePlayed || preference.matches) return;
    stagePlayed = true;
    stage.classList.remove("is-settled");
    stage.classList.add("is-playing");
    const tablet = stage.querySelector(".reading-tablet");
    stage.addEventListener("animationend", event => {
      if (event.target === tablet) settle();
    });
    timer = window.setTimeout(settle, 5200);
  }
  function reveal(element) {
    if (preference.matches || played.has(element)) return;
    played.add(element);
    if (typeof element.animate !== "function") return;
    const animation = element.animate(
      [{ opacity: 0.72, transform: "translateY(10px)" }, { opacity: 1, transform: "translateY(0)" }],
      { duration: 460, easing: "ease-out" },
    );
    animations.add(animation);
    animation.addEventListener("finish", () => animations.delete(animation), { once: true });
  }
  function enhance() {
    if (preference.matches) return;
    document.body.classList.add("bede-intro");
    if (!("IntersectionObserver" in window)) return; // Everything stays visible.
    observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        observer.unobserve(entry.target);
        if (entry.target === stage) playBook();
        else reveal(entry.target);
      });
    }, { threshold: 0.12 });
    targets.forEach(element => observer.observe(element));
    if (stage && !stagePlayed) observer.observe(stage);
  }
  preference.addEventListener("change", event => {
    observer?.disconnect();
    if (event.matches) {
      document.body.classList.remove("bede-intro");
      animations.forEach(animation => animation.cancel());
      animations.clear();
      settle();
    } else enhance();
  });
  enhance();
})();
