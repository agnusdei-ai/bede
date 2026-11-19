export const evidenceFiles = ["faq-1.pdf", "faq-2.pdf", "clipboard-denied.png"];

export function validatePrerequisites({ pinned, installed, display, ci, customChromium, executableExists }) {
  if (installed !== pinned) throw new Error(`Playwright must be ${pinned}; found ${installed}`);
  if (!display) throw new Error("A real DISPLAY is required. On headless Linux run this command under xvfb-run -a.");
  if (ci && customChromium) throw new Error("CI must use the Chromium revision bundled with the pinned Playwright dependency, not FAQ_CHROMIUM_PATH.");
  if (!executableExists) throw new Error("Chromium is missing. Install Chromium with the pinned Playwright CLI before running the gate.");
}

export function assertNoSkippedTests(tap) {
  if (!/^# skipped 0$/m.test(tap)) throw new Error("Release checks must report zero skipped tests.");
}

export function exportEngines(value = "firefox,webkit") {
  const names = value.split(",");
  if (!names.length || names.some(name => !["firefox", "webkit"].includes(name)) || new Set(names).size !== names.length) {
    throw new Error("FAQ_EXPORT_ENGINES must name firefox and/or webkit exactly once");
  }
  return names;
}
