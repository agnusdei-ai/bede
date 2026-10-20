/* Copy and print all FAQ content without changing reading or navigation state. */
(() => {
  function initialize() {
  const faq = document.querySelector("main .faq");
  const tools = document.querySelector(".faq-reader-tools");
  if (!faq || !tools) return;
  const status = tools.querySelector("#faq-reader-status");
  const copyButton = tools.querySelector("[data-faq-copy]");
  const printButton = tools.querySelector("[data-faq-print]");
  if (!status || !copyButton || !printButton) return;
  tools.hidden = false;

  function faqText() {
    const clone = faq.cloneNode(true);
    clone.querySelectorAll("script, style, button, svg, video, iframe, .classical-device-art, .reading-sequence")
      .forEach(node => node.remove());
    const blocks = new Set(["DIV", "SECTION", "ARTICLE", "DETAILS", "SUMMARY", "P", "UL", "OL", "H1", "H2", "H3", "H4", "DT", "DD"]);
    function text(node) {
      if (node.nodeType === 3) return node.textContent.replace(/\s+/g, " ");
      if (node.nodeType !== 1) return "";
      if (node.tagName === "BR") return "\n";
      const content = Array.from(node.childNodes, text).join("");
      if (node.tagName === "LI") return `\n• ${content.trim()}\n`;
      if (blocks.has(node.tagName)) return `\n\n${content.trim()}\n\n`;
      return content;
    }
    const source = document.querySelector('link[rel="canonical"]')?.href;
    return ["Bede — Frequently Asked Questions", source || "", text(clone)]
      .join("\n\n").replace(/[ \t]+\n/g, "\n").replace(/\n[ \t]+/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  function manualCopy(value) {
    let field = tools.querySelector("textarea");
    if (!field) {
      const label = document.createElement("label");
      label.textContent = "Complete FAQ text";
      field = document.createElement("textarea");
      field.id = "faq-copy-text";
      field.readOnly = true;
      field.rows = 12;
      label.htmlFor = field.id;
      tools.append(label, field);
    }
    field.value = value;
    field.focus();
    field.select();
    status.textContent = "Automatic copying is unavailable in this browser. Copy the selected text below.";
  }

  copyButton.addEventListener("click", async () => {
    const value = faqText();
    copyButton.disabled = true;
    try {
      if (!navigator.clipboard?.writeText) return manualCopy(value);
      await navigator.clipboard.writeText(value);
      const field = tools.querySelector("textarea");
      if (field) { field.previousElementSibling?.remove(); field.remove(); }
      status.textContent = "Complete FAQ copied, including all closed answers.";
    } catch {
      manualCopy(value);
    } finally {
      copyButton.disabled = false;
    }
  });

  let printState = null;
  function preparePrint() {
    if (printState) return;
    printState = Array.from(faq.querySelectorAll("details"), node => [node, node.open]);
    printState.forEach(([node]) => { node.open = true; });
  }
  function restorePrint() {
    if (!printState) return;
    printState.forEach(([node, wasOpen]) => { node.open = wasOpen; });
    printState = null;
  }
  window.addEventListener("beforeprint", preparePrint);
  window.addEventListener("afterprint", restorePrint);
  const media = window.matchMedia?.("print");
  media?.addEventListener?.("change", event => event.matches ? preparePrint() : restorePrint());
  printButton.addEventListener("click", () => {
    preparePrint();
    try { window.print(); }
    catch {
      restorePrint();
      status.textContent = "The print dialog could not open. Use your browser’s Print command.";
    }
  });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, { once: true });
  else initialize();
})();
