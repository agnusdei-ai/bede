FROM python:3.12-slim

# libsndfile: soundfile audio I/O (all audio decoding in this service goes
# through soundfile directly — see services/transcription.py and
# services/voice_auth.py — so no ffmpeg binary is needed here).
# gcc + python3-dev: webrtcvad (a transitive dep of resemblyzer, not
# faster-whisper) has no prebuilt wheel for this platform and compiles a C
# extension at install time — without a compiler, `pip install -r
# requirements.in` below fails outright. This was never caught before now
# because this image had never actually been built end-to-end until
# production-regression.yml's first real run (this sandbox has the Docker
# CLI but no daemon to build with).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 curl gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --no-create-home --shell /bin/false sage

WORKDIR /app
# requirements.in is this image's human-edited, floor-pinned source of
# intent — renamed from requirements.txt when hash-locked, reproducible
# dependency resolution was added (docs/SECURITY.md's closed-gap entry).
# CI (.github/workflows/test.yml) installs from the hash-verified
# requirements.lock.txt/requirements-dev.lock.txt instead, for
# reproducibility; this image intentionally keeps installing from the
# floor-pinned source so the CPU-only torch trick just below (which relies
# on resemblyzer's `torch` dependency being satisfied by whatever's
# already installed, not a hash-pinned exact build) keeps working
# unchanged.
COPY requirements.in .
# Install PyTorch's CPU-only build FIRST, before requirements.in.
# resemblyzer (voice_auth.py's speaker-embedding library — see
# requirements.in's own comment) has a hard `torch` dependency that isn't
# declared here directly, so without this step pip resolves it from the
# DEFAULT PyPI index, which serves the full CUDA-bundled wheel — measured
# directly via `pip download torch`: 526.6MB, versus PyTorch's own
# well-documented CPU-only build at roughly a third of that — even though
# this container has no GPU (cap_drop: ALL, no device passthrough) and runs
# entirely on CPU. Once torch is already installed here, the requirements.in
# install below sees resemblyzer's `torch>=1.0.1` as already satisfied and
# does not reinstall it — the standard, documented workaround for this exact
# class of problem. This is what actually makes faster-whisper's own
# "drops the PyTorch runtime, for a meaningfully smaller/faster Docker
# build" framing (see that dependency's comment below) true at the WHOLE
# image level, not just for the transcription path alone — without this,
# resemblyzer would have silently undone that saving by several times over.
#
# Pinned, not floating. This line installs from a SECOND package index
# (download.pytorch.org) outside the one the rest of requirements.in
# resolves against, so it is its own supply-chain surface and the only
# dependency here with no version constraint at all — an unpinned `torch`
# means two builds of the same commit can ship different runtime code,
# which also makes the pip-audit gate in .github/workflows/test.yml a
# statement about whatever happened to be latest at build time rather
# than about what this image actually contains. Bump deliberately.
#
# 2.13.0 is the current stable release, which is what the unpinned form
# already resolved to — this freezes today's behavior rather than moving
# it. production-regression.yml's `docker compose up -d --build` is what
# actually proves the pin exists on the CPU index; it could not be checked
# from the authoring sandbox, whose egress proxy blocks download.pytorch.org.
RUN pip install --no-cache-dir torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.in

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
