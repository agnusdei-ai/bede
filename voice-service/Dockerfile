# SPDX-License-Identifier: GPL-3.0-or-later
# Bede's local voice (server.py + Piper). Its own image and its own process:
# Bede's API reaches it only over HTTP. See README.md.
FROM python:3.12-slim

RUN useradd --no-create-home --shell /bin/false voice

WORKDIR /app
# Hash-locked, like the API's CI install (requirements.in is the intent).
COPY requirements.lock.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock.txt

COPY server.py COPYING README.md ./

USER voice
EXPOSE 5000
# Voices are mounted read-only at /voices and named by BEDE_VOICE_EN /
# BEDE_VOICE_ES; this image downloads nothing at run time.
CMD ["python", "-I", "server.py"]
