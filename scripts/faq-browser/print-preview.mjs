import { expect } from "@playwright/test";

// Chromium's native print dialog is a separate target, not a Playwright Page.
// Attach without flattening so commands can reach its real shadow-DOM controls.
export async function cancelPrintPreview(browser) {
  const cdp = await browser.newBrowserCDPSession();
  let target;
  await expect.poll(async () => {
    target = (await cdp.send("Target.getTargets")).targetInfos
      .find(info => info.url === "chrome://print/");
    return Boolean(target);
  }, { timeout: 15000, message: "Native Chromium print preview opens" }).toBe(true);
  const { sessionId } = await cdp.send("Target.attachToTarget", {
    targetId: target.targetId, flatten: false,
  });
  let sequence = 0;
  async function evaluate(expression) {
    const id = ++sequence;
    const response = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        cdp.off("Target.receivedMessageFromTarget", onMessage);
        reject(new Error("Print-preview command timed out"));
      }, 10000);
      function onMessage(event) {
        if (event.sessionId !== sessionId) return;
        const message = JSON.parse(event.message);
        if (message.id !== id) return;
        clearTimeout(timer);
        cdp.off("Target.receivedMessageFromTarget", onMessage);
        if (message.error || message.result?.exceptionDetails) {
          reject(new Error(JSON.stringify(message)));
        } else resolve(message.result.result.value);
      }
      cdp.on("Target.receivedMessageFromTarget", onMessage);
    });
    await cdp.send("Target.sendMessageToTarget", {
      sessionId,
      message: JSON.stringify({
        id, method: "Runtime.evaluate", params: { expression, returnByValue: true },
      }),
    });
    return response;
  }
  try {
    // Wait for a rendered preview, not just the presence of the dialog target.
    await expect.poll(() => evaluate(`(() => {
      const app = document.querySelector('print-preview-app');
      const sidebar = app?.shadowRoot?.querySelector('print-preview-sidebar');
      const strip = sidebar?.shadowRoot?.querySelector('print-preview-button-strip');
      const cancel = strip?.shadowRoot?.querySelector('.cancel-button');
      return !!cancel && !cancel.disabled;
    })()`), { timeout: 20000, message: "Print preview renders before Cancel" }).toBe(true);
    await expect.poll(async () => (await cdp.send("Target.getTargets")).targetInfos.some(info =>
      info.url.startsWith("chrome-untrusted://print/") && info.url.endsWith("/print.pdf")),
    { timeout: 15000, message: "Native preview generated its PDF" }).toBe(true);
    await evaluate(`document.querySelector('print-preview-app').shadowRoot
      .querySelector('print-preview-sidebar').shadowRoot
      .querySelector('print-preview-button-strip').shadowRoot
      .querySelector('.cancel-button').click()`);
    await expect.poll(async () => (await cdp.send("Target.getTargets")).targetInfos
      .some(info => info.targetId === target.targetId)).toBe(false);
  } finally {
    await cdp.detach();
  }
}
