# Tiny, short-lived container that serves the browser-based setup wizard,
# then exits once wizard.py's form has been submitted successfully — the
# launcher script (setup-gui.command / .sh / .bat, repo root) waits for this
# container to exit as its signal to proceed with `docker compose up`.
#
# Build context is the REPO ROOT (not this directory) so this can copy
# core/pin_policy.py — see setup-gui.* for the exact build command.
FROM python:3.12-alpine

WORKDIR /app
# School mode verifies the campus key's Ed25519 signature with the API's own
# core/licensing.py, which needs pycryptodome (same pin as the API's lockfile).
RUN pip install --no-cache-dir pycryptodome==3.23.0
COPY homeschool-api/core/pin_policy.py homeschool-api/core/licensing.py homeschool-api/core/__init__.py /app/homeschool-api/core/
COPY scripts/setup_wizard/wizard.py scripts/setup_wizard/install_receipt.py /app/
# The notices shown first; the family notice's hash is written to .env and both
# are hashed into the installation receipt. wizard.py refuses to start without
# them.
COPY homeschool-api/data/consent_notice.txt /app/consent_notice.txt
COPY homeschool-api/data/school_data_notice.txt /app/school_data_notice.txt
COPY site/assets/bede-portrait.png /app/BedeIcon.png
# Optional spoken narration (see generate_narration.py) — copies whatever's
# committed there, even if empty; wizard.py degrades gracefully either way.
COPY scripts/setup_wizard/audio/ /app/audio/

EXPOSE 8765
CMD ["python3", "wizard.py"]
