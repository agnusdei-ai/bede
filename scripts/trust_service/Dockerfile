FROM python:3.12-alpine

# Without this, print()'s stdout is fully block-buffered (not line-buffered)
# whenever it's not attached to a TTY — which is always true under
# `docker compose logs` — so nothing shows up until the buffer fills or the
# process exits. Cost real debugging time chasing an empty log during this
# service's first real CI run.
ENV PYTHONUNBUFFERED=1

# segno is pure Python (no C extension) — verified no gcc/build deps needed,
# same lesson learned the hard way from webrtcvad in homeschool-api/Dockerfile.
RUN pip install --no-cache-dir segno==1.6.6

WORKDIR /app
COPY trust_service.py .

# Stays root (no USER drop here) — it needs to read root.crt out of the
# caddy_data volume, which Caddy itself (running as root) writes with
# restrictive permissions; a non-root user here could get a permission
# error that would only ever show up against a real Caddy-written file,
# not in any unit test. Containment comes from cap_drop: ALL + read_only
# in docker-compose.yml instead, the same model already used for the ui
# service before nginx's own privilege drop.
EXPOSE 8080

CMD ["python3", "trust_service.py"]
