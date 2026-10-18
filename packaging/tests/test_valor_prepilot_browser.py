"""Browser acceptance test for the self-contained, fictional Valor prepilot.

Requires playwright + local Chromium. Opens the HTML as file:// with no backend,
credentials, Docker, network calls or real learner information.
"""
from pathlib import Path
import json

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / "packaging" / "bundle" / "Valor-Prepilot-Walkthrough.html"


def main():
    assert HTML.exists()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        errors, outbound = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: outbound.append(req.url) if req.url.startswith(("http://", "https://")) else None)
        page.goto(HTML.as_uri())
        assert page.get_by_text("Interactive simulation only.").count() == 1
        assert page.locator("#panel-official").is_visible()

        # An unreviewed official result cannot accidentally be finalized.
        page.locator("#saveOfficial").click()
        assert "Confirm you reviewed" in page.locator("#official-error").inner_text()

        # Explicit skipped/nonadministered statuses remain null, NEVER numeric 0.
        page.locator("#measureStatus").select_option("skipped")
        assert page.locator("#rawScore").is_disabled()
        page.locator("#noScoreReason").fill("Unadministered by rule in this fictional demonstration")
        page.locator("#verified").check()
        page.locator("#saveOfficial").click()
        assert page.locator("#panel-observation").is_visible()
        assert "no numeric score" in page.locator("#savedOfficial").inner_text()
        page.locator("#saveObservation").click()
        assert page.locator("#panel-review").is_visible()

        # Teacher approves: never connects to a learner session.
        page.locator('button[data-decision="approve"]').click()
        assert page.locator("#panel-audit").is_visible()
        assert "NOT_REQUESTED" in page.locator("#reviewSummary").inner_text()
        with page.expect_download() as download_info:
            page.locator("#export").click()
        download = download_info.value
        payload = json.loads(Path(download.path()).read_text())
        assert payload["kind"] == "BEDE_VALOR_SYNTHETIC_PREPILOT"
        assert payload["server_audited"] is False
        assert payload["real_student_data"] is False
        assert payload["official"][-1]["raw_score"] is None
        assert payload["official"][-1]["measure_status"] == "skipped"
        assert payload["decisions"][-1]["delivery_state"] == "NOT_REQUESTED"
        assert [row["seq"] for row in payload["events"]] == list(range(1, len(payload["events"]) + 1))
        # Browser-tab state survives a simple reload for reviewer convenience.
        page.reload()
        page.locator('[data-step="audit"]').click()
        assert "approve" in page.locator("#reviewSummary").inner_text()

        # Corrections retain a linked old record instead of overwriting it.
        page.locator('[data-step="official"]').click()
        page.locator("#measureStatus").select_option("scored")
        page.locator("#rawScore").fill("61")
        page.locator("#verified").check()
        page.locator("#saveOfficial").click()
        assert "Not recorded" in page.locator("#sideObs").inner_text()
        assert "Awaiting review" in page.locator("#sideDecision").inner_text()
        page.locator('[data-step="review"]').click()
        page.locator('button[data-decision="approve"]').click()
        assert "Record the official result and an observation" in page.locator("#review-error").inner_text()
        page.locator('[data-step="audit"]').click()
        with page.expect_download() as correction_info:
            page.locator("#export").click()
        changed = json.loads(Path(correction_info.value.path()).read_text())
        assert len(changed["official"]) == 2
        assert changed["official"][0]["raw_score"] is None
        assert changed["official"][1]["raw_score"] == 61
        assert changed["official"][1]["supersedes_id"] == changed["official"][0]["id"]

        assert not outbound, f"Walkthrough should be entirely offline, but made requests: {outbound}"
        assert not errors, f"Uncaught browser errors: {errors}"
        context.close()
        browser.close()
    print("PASS: simulated official result, skip-null, observation, decision, correction, export, offline")


if __name__ == "__main__":
    main()
