"""The watchdog must monitor planned closure, not label it an outage."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_watchdog_deadline_and_closed_screen_checks():
    script = r"""
import { publicDemoClosed, verifyClosedDemo } from './scripts/public_demo_beta.mjs';
const makePage = (badEmail = false, entryCount = 0) => ({
  getByRole(role, {name}) {
    return {
      waitFor: async () => {},
      isVisible: async () => true,
      count: async () => role === 'button' ? entryCount : 1,
      getAttribute: async () => name === 'Request onboarding'
        ? '/inquire/' : badEmail ? 'mailto:wrong@example.com' : 'mailto:info@agnusdei.ai',
    };
  },
});
const results = [
  publicDemoClosed(Date.parse('2027-01-01T05:59:59.999Z')),
  publicDemoClosed(Date.parse('2027-01-01T06:00:00Z')),
  publicDemoClosed(Date.parse('2027-01-02T00:00:00Z')),
];
await verifyClosedDemo(makePage(), 'Start Bede demo', 100);
for (const page of [makePage(true), makePage(false, 1)]) {
  try { await verifyClosedDemo(page, 'Start Bede demo', 100); results.push('missed'); }
  catch { results.push('rejected'); }
}
console.log(JSON.stringify(results));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT, check=True, capture_output=True, text=True, timeout=15,
    )
    assert json.loads(result.stdout) == [False, True, True, "rejected", "rejected"]


def test_closed_monitor_branch_runs_before_any_consent_or_demo_access():
    journey = (ROOT / "scripts/sample_journey.mjs").read_text()
    closed_branch = journey.index("if (publicDemoClosed())")
    assert closed_branch < journey.index("await consent.click()")
    assert closed_branch < journey.index("await button.click()")
    branch = journey[closed_branch:journey.index("// ── Step 1b:", closed_branch)]
    assert "await verifyClosedDemo" in branch
    assert "finish(0)" in branch
    assert "fetch(" not in branch
