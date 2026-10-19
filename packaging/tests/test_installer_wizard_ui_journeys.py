"""Synthetic browser journeys for Bede installer wizard.

Only fake data and temporary directories. No live learners, service accounts,
real licenses, Docker volume changes, or production credentials.
"""
import contextlib
import http.server
import os
from pathlib import Path
import tempfile
import threading
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "setup_wizard"))

from playwright.sync_api import sync_playwright

import wizard


def run():
    outcomes = []
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
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
    print("Synthetic browser journeys passed:", ", ".join(outcomes))


if __name__ == "__main__":
    run()
