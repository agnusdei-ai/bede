# Tiny, short-lived container that serves the browser-based setup wizard,
# then exits once wizard.py's form has been submitted successfully — the
# launcher script (setup-gui.command / .sh / .bat, repo root) waits for this
# container to exit as its signal to proceed with `docker compose up`.
#
# Build context is the REPO ROOT (not this directory) so this can copy
# core/pin_policy.py — see setup-gui.* for the exact build command.
FROM python:3.12-alpine

WORKDIR /app
COPY homeschool-api/core/pin_policy.py homeschool-api/core/__init__.py /app/homeschool-api/core/
COPY scripts/setup_wizard/wizard.py /app/wizard.py

EXPOSE 8765
CMD ["python3", "wizard.py"]
