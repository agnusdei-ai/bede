FROM python:3.12-slim

# libsndfile: soundfile audio I/O; ffmpeg: audio format conversion for whisper
# gcc + python3-dev: webrtcvad (a transitive dep of openai-whisper) has no
# prebuilt wheel for this platform and compiles a C extension at install
# time — without a compiler, `pip install -r requirements.txt` below fails
# outright. This was never caught before now because this image had never
# actually been built end-to-end until production-regression.yml's first
# real run (this sandbox has the Docker CLI but no daemon to build with).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 ffmpeg curl gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --no-create-home --shell /bin/false sage

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
