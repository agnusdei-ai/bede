FROM python:3.12-slim

# libsndfile: soundfile audio I/O (all audio decoding in this service goes
# through soundfile directly — see services/transcription.py and
# services/voice_auth.py — so no ffmpeg binary is needed here).
# gcc + python3-dev: webrtcvad (a transitive dep of resemblyzer, not
# faster-whisper) has no prebuilt wheel for this platform and compiles a C
# extension at install time — without a compiler, `pip install -r
# requirements.txt` below fails outright. This was never caught before now
# because this image had never actually been built end-to-end until
# production-regression.yml's first real run (this sandbox has the Docker
# CLI but no daemon to build with).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 curl gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --no-create-home --shell /bin/false sage

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the faster-whisper fallback-STT model weights into the image
# at build time. The api container below runs read_only:true in production
# (docker-compose.yml) with no writable volume outside a 64MB /tmp tmpfs, so
# a first-use runtime download (faster-whisper's normal behavior otherwise)
# has nowhere to write and fails — silently, since services/transcription.py
# treats any load failure as "fallback STT unavailable" and degrades rather
# than crashing. Baking the model in here makes it a plain read-only file
# the running container only ever reads. Must stay in sync with
# transcription.py's MODEL_DIR/model-size constants.
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8', download_root='/app/models/whisper')"

COPY . .
RUN chown -R sage:sage /app

USER sage

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -sf http://localhost:8000/health || exit 1

# --proxy-headers with forwarded-allow-ips='*' is required on every hosting
# platform that fronts this container with its own reverse proxy (Render,
# Fly.io, Heroku, etc.): the container is never reached directly, so the only
# peer uvicorn ever sees is that platform's proxy, and uvicorn's own default
# (forwarded_allow_ips=127.0.0.1) would silently ignore X-Forwarded-For in
# that setup — collapsing every real visitor's IP into one, which broke the
# per-IP rate limiter (core/middleware.py) and audit log IP attribution
# (core/audit.py) for anyone not running this literally on localhost.
#
# --timeout-graceful-shutdown 120: on redeploy, the hosting platform sends
# SIGTERM to this container before replacing it. uvicorn's default response
# to SIGTERM is to stop accepting new connections but only wait a short,
# unspecified window for requests already in flight before killing them —
# nowhere near long enough for a real Socratic turn's own SSE stream
# (multiple tool calls, then OpenAI TTS synthesis afterward can easily
# run several seconds to over a minute end to end). 120s gives any
# in-flight request genuine room to finish naturally instead of being cut
# off mid-response the moment a deploy starts — this does NOT by itself
# solve session continuity across a full container replacement (in-memory
# demo state — core/demo_code_session.py, core/diagnostic_preview_quota.py
# — still doesn't survive one; that's a separate, larger decision, not
# something this flag can fix), only that whatever's actively streaming
# when the deploy begins gets to complete.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*", "--timeout-graceful-shutdown", "120"]
