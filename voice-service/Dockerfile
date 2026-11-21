# SPDX-License-Identifier: GPL-3.0-or-later
# Bede's local voice (server.py + Piper). Its own image and its own process:
# Bede's API reaches it only over HTTP. See README.md.
FROM python:3.12-slim

RUN useradd --no-create-home --shell /bin/false voice

WORKDIR /app
# Hash-locked, like the API's CI install (requirements.in is the intent).
COPY requirements.lock.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock.txt

COPY server.py COPYING README.md bede-voice.json fetch_voice.py ./
# Bede's voice (bede-voice.json), fetched now and kept only if every pinned
# SHA-256 matches. With hashes not yet pinned, no network, or a mismatch, no
# voice is kept and Bede is text-first; this step never fails the build.
RUN python -I fetch_voice.py bede-voice.json /app/voices

USER voice
EXPOSE 5000
# The built-in voice is /app/voices; another can be mounted read-only at
# /voices and named by BEDE_VOICE_EN / BEDE_VOICE_ES. Nothing is downloaded
# at run time.
CMD ["python", "-I", "server.py"]
