"""Synthetic browser journeys for Bede installer wizard.

Only fake data and temporary directories. No live learners, service accounts,
real licenses, Docker volume changes, or production credentials.
"""
import base64
import json
import os
from pathlib import Path
import tempfile
import threading
import sys
from itertools import product
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "setup_wizard"))

from playwright.sync_api import sync_playwright

import wizard


def run():
    outcomes = []
    evidence_dir = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / "bede-installer-ui-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        wizard.REPO_DIR = scratch
        wizard.ENV_PATH = str(Path(scratch) / ".env")
        wizard._shutdown_event.clear()
        wizard._cancel_event.clear()
        server = wizard.ThreadingHTTPServer(("127.0.0.1", 0), wizard.Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                errors = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                page.goto(base)
                page.get_by_role("heading", name="Welcome to Bede").wait_for()
                assert page.title() == "Welcome to Bede"
                outcomes.append("welcome title and branding")

                page.get_by_role("button", name="Set up Bede").click()
                assert not Path(wizard.ENV_PATH).exists()
                outcomes.append("blank submission fails closed")

                page.goto(base)
                page.locator('[name="parent_password"]').fill("Password")
                page.get_by_role("button", name="Set up Bede").click()
                assert not Path(wizard.ENV_PATH).exists()
                outcomes.append("weak recovery credential cannot create config")

                page.goto(base)
                page.locator('[name="license_key"]').fill("bad-activation")
                page.get_by_role("button", name="Set up Bede").click()
                assert not Path(wizard.ENV_PATH).exists()
                outcomes.append("bad activation cannot create config")

                page.goto(base)
                page.get_by_role("button", name="Cancel setup for now").click()
                page.get_by_role("heading", name="Setup stopped").wait_for()
                assert wizard._cancel_event.wait(2)
                assert not Path(wizard.ENV_PATH).exists()
                outcomes.append("cancel is visible and leaves no config")
                # Agent-style deterministic state exploration: exercise each
                # combination through the real browser and server boundary.
                def synthetic_license(kind, context):
                    payload = {
                        "id": "synthetic-only",
                        "licensee": "Synthetic UI Test",
                        "tier": "campus_location" if context == "campus" else "trial",
                        "expires": "2025-01-01" if kind == "expired" else "2099-12-31",
                    }
                    if context == "campus":
                        payload["location_id"] = "another-campus" if kind == "wrong_campus" else "pilot-campus"
                    encoded = base64.urlsafe_b64encode(
                        json.dumps(payload).encode("utf-8")
                    ).decode("ascii").rstrip("=")
                    return encoded + ".unsigned-synthetic-test"

                test_matrix = [
                    (context, credential, problem)
                    for context, credential, problem in product(
                        ("campus", "homeschool"),
                        ("Password", "strong-recovery-credential-5678"),
                        ("expired", "malformed", "wrong_campus"),
                    )
                    if credential == "Password" or problem != "wrong_campus"
                    or context == "campus"
                ]
                for context, credential, problem in test_matrix:
                    wizard.DEPLOYMENT_CONTEXT = context
                    wizard.APPROVED_CAMPUS_ID = "pilot-campus" if context == "campus" else ""
                    page.goto(base)
                    page.get_by_role("heading", name="Welcome to Bede").wait_for()
                    page.locator('[name="anthropic_key"]').fill("synthetic-provider-credential")
                    page.locator('[name="parent_password"]').fill(credential)
                    if context == "homeschool":
                        page.locator('[name="child_pin"]').fill(wizard.SUGGESTED_CHILD_PIN)
                    code = "malformed" if problem == "malformed" else synthetic_license(problem, context)
                    page.locator('[name="license_key"]').fill(code)
                    page.get_by_role("button", name="Set up Bede").click()
                    page.locator(".error").first.wait_for()
                    assert not Path(wizard.ENV_PATH).exists(), (context, credential, problem)
                    error_text = page.locator(".error").first.inner_text().lower()
                    if credential != "Password":
                        expected = {"expired": "expired", "malformed": "format is invalid",
                                    "wrong_campus": "different campus"}[problem]
                        assert expected in error_text, (context, problem, error_text)
                    outcomes.append(f"{context}/{problem}/{'weak' if credential == 'Password' else 'strong'}")

                # Positive journey: submit a fake local-model configuration
                # and verify the UI handoff plus scoped .env creation. The
                # unsigned test entitlement is NOT valid for a live backend.
                wizard.DEPLOYMENT_CONTEXT = "homeschool"
                wizard.APPROVED_CAMPUS_ID = ""
                page.goto(base)
                page.locator('input[name="provider"][value="local"]').check()
                page.locator('[name="local_base_url"]').fill("http://127.0.0.1:8999/v1")
                page.locator('[name="parent_password"]').fill("synthetic-recovery-credential-4619")
                page.locator('[name="child_pin"]').fill(wizard.SUGGESTED_CHILD_PIN)
                page.locator('[name="license_key"]').fill(synthetic_license("valid", "homeschool"))
                page.get_by_role("button", name="Set up Bede").click()
                page.get_by_role("heading", name="Starting Bede").wait_for()
                body = Path(wizard.ENV_PATH).read_text(encoding="utf-8")
                assert "BEDE_ADAPTER_ORDER=local" in body
                assert "LOCAL_LLM_BASE_URL=http://127.0.0.1:8999/v1" in body
                assert "WEBAUTHN_ORIGIN=https://localhost" in body
                assert 'href="https://localhost"' not in page.content()
                outcomes.append("synthetic local-model setup and safe native handoff")

                assert not errors, errors
                browser.close()
        except Exception as error:
            # All fixture inputs are synthetic, so a screenshot is safe for CI.
            if "page" in locals():
                try:
                    page.screenshot(path=str(evidence_dir / "failed-journey.png"), full_page=True)
                except Exception:
                    pass
            (evidence_dir / "failure.txt").write_text(
                f"UI journey failure ({type(error).__name__}). Completed journeys: "
                + ", ".join(outcomes) + "\\n", encoding="utf-8"
            )
            raise
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
    (evidence_dir / "scenarios.json").write_text(json.dumps({"result": "pass", "scenarios": outcomes}, indent=2) + "\\n", encoding="utf-8")
    print("Synthetic browser journeys passed:", ", ".join(outcomes))


if __name__ == "__main__":
    run()
