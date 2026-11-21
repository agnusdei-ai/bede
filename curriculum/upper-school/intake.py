"""Bounded acquisition of selected review copies, never runtime ingestion."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CATALOG = HERE / "open-resources.json"
DEST = ROOT / "generated-artifacts/upper-school-sources"
MAX_BYTES = 12 * 1024 * 1024
ALLOWED_HOSTS = {"www.wallace.ccfaculty.org", "wallace.ccfaculty.org",
                 "www.gutenberg.org", "gutenberg.org", "docs.python.org"}
HOST_LOCKS = {host.removeprefix("www."): threading.Lock() for host in ALLOWED_HOSTS}
HOST_RETRY_AT = {}


def checked_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Acquisition URL outside the explicit HTTPS source allowlist")
    return url


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url):
    """Serialize each host and stop its queued requests when it asks to wait."""
    host = urlsplit(checked_url(url)).hostname.removeprefix("www.")
    with HOST_LOCKS[host]:
        retry_at = HOST_RETRY_AT.get(host, 0)
        if retry_at > time.time():
            raise RuntimeError(f"Host cooldown until {datetime.fromtimestamp(retry_at, timezone.utc).isoformat()}")
        request = Request(url, headers={
            "User-Agent": "Bede-Curriculum-Review/1.0",
            "Accept": "application/pdf,text/plain;q=0.9"})
        try:
            with build_opener(SafeRedirect()).open(request, timeout=35) as response:
                resolved = checked_url(response.geturl())
                return response.read(MAX_BYTES + 1), resolved
        except HTTPError as exc:
            retry = exc.headers.get("Retry-After", "")
            if exc.code in (429, 503) or retry:
                try:
                    when = time.time() + max(1, int(retry))
                except ValueError:
                    try:
                        when = parsedate_to_datetime(retry).timestamp()
                    except (ValueError, TypeError, OverflowError):
                        when = time.time() + 60
                HOST_RETRY_AT[host] = max(time.time() + 1, when)
            raise


def validate_payload(data, kind):
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Empty or oversized source")
    if kind == "pdf":
        if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
            raise ValueError("Expected a complete PDF, not HTML or an error response")
    elif kind == "gutenberg-text":
        text = data.decode("utf-8-sig")
        if (not re.search(r"\*\*\* START OF (?:THE|THIS) PROJECT GUTENBERG", text)
                or not re.search(r"\*\*\* END OF (?:THE|THIS) PROJECT GUTENBERG", text)
                or "Project Gutenberg" not in text[-40000:]):
            raise ValueError("Expected UTF-8 Gutenberg text with retained end notices")
    elif kind == "python-html":
        lower = data.lower()
        if (b"<html" not in lower or b"</html>" not in lower
                or b"<title>" not in lower or b"python" not in lower
                or b"3.14." not in lower or b"python software foundation" not in lower):
            raise ValueError("Expected complete versioned Python documentation with notices")
    else:
        raise ValueError("Unsupported acquisition format")


def atomic_write(path, data):
    fd, temporary = tempfile.mkstemp(prefix=".intake-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def acquire(source, destination):
    result = dict(source)
    result.update(runtime_approved=False, training_approved=False)
    if not source["acquire"]:
        result["acquisition_status"] = "external-reference-only"
        return result
    try:
        if not re.fullmatch(r"[a-z0-9-]+", source["id"]):
            raise ValueError("Unsafe source id")
        suffix = ".pdf" if source["format"] == "pdf" else ".txt"
        target = destination / (source["id"] + suffix)
        metadata_path = destination / (source["id"] + ".json")
        if target.is_symlink() or metadata_path.is_symlink():
            raise ValueError("Source symlinks are not accepted")
        checked_url(source["url"])
        cached = None
        if target.exists() and metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if target.stat().st_size <= MAX_BYTES:
                candidate = target.read_bytes()
                if (metadata.get("url") == source["url"]
                        and hashlib.sha256(candidate).hexdigest() == metadata.get("sha256")):
                    validate_payload(candidate, source["format"])
                    cached = (candidate, metadata["resolved_url"], metadata["acquired_at"])
        if cached:
            data, resolved, acquired_at = cached
            if (source.get("expected_sha256")
                    and hashlib.sha256(data).hexdigest() != source["expected_sha256"]):
                raise ValueError("Cached source differs from the inspected edition; re-review required")
        else:
            data, resolved = download(source["url"])
            validate_payload(data, source["format"])
            if (source.get("expected_sha256")
                    and hashlib.sha256(data).hexdigest() != source["expected_sha256"]):
                raise ValueError("Source changed from the previously inspected edition; re-review required")
            acquired_at = datetime.now(timezone.utc).isoformat()
            atomic_write(target, data)
        result.update(acquisition_status="reused" if cached else "acquired",
                      local_file=target.name, bytes=len(data),
                      sha256=hashlib.sha256(data).hexdigest(),
                      resolved_url=resolved, acquired_at=acquired_at)
        atomic_write(metadata_path, (json.dumps(result, ensure_ascii=False, indent=2)
                                    + "\n").encode())
    except Exception as exc:
        result.update(acquisition_status="failed",
                      error=f"{type(exc).__name__}: {exc}")
    return result


def source_records(catalog):
    sources = list(catalog["sources"])
    collection = catalog.get("documentation_collection")
    if collection:
        parent = next(s for s in sources if s["id"] == collection["parent_id"])
        for page in collection["pages"]:
            sources.append(dict(
                parent, **page, acquire=True, format="python-html",
                use=collection["purpose"],
                restrictions="Unchanged archival HTML stored as .txt; scripts never executed, "
                "no images or linked assets downloaded. Retain the accompanying python-license "
                "snapshot and all applicable PSF/historical notices. Examples' additional "
                "0BSD terms do not relicense Bede originals. Not runtime or training approval."))
    return sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true",
                        help="Validate catalog only; never contact repositories")
    args = parser.parse_args()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    sources = source_records(catalog)
    ids = [s["id"] for s in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source ids")
    for source in sources:
        for field in ("id", "title", "creator", "url", "license",
                      "attribution", "use", "restrictions"):
            if not source.get(field):
                raise ValueError(f"Missing {field}")
        if source["acquire"]:
            checked_url(source["url"])
    if args.offline:
        print(f"PASS: {len(sources)} source records; "
              f"{sum(s['acquire'] for s in sources)} enabled review acquisitions")
        return 0
    if DEST.is_symlink():
        raise ValueError("Destination must not be a symlink")
    DEST.mkdir(parents=True, exist_ok=True)
    previous = DEST / "acquisition-report.json"
    cooldown_evidence = None
    if previous.exists():
        prior_report = json.loads(previous.read_text())
        cooldown_evidence = prior_report.get("cooldown_evidence")
        for host, retry_at in prior_report.get("host_retry_at", {}).items():
            if host in HOST_LOCKS and isinstance(retry_at, (int, float)):
                HOST_RETRY_AT[host] = retry_at
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda s: acquire(s, DEST), sources))
    report = dict(status="local-review-only", runtime_activation=False,
                  training=False, sources=results, host_retry_at=HOST_RETRY_AT)
    if cooldown_evidence:
        report["cooldown_evidence"] = cooldown_evidence
    atomic_write(DEST / "acquisition-report.json",
                 (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    for result in results:
        print(f"{result['id']}: {result['acquisition_status']}"
              + (f" ({result['error']})" if result.get("error") else ""))
    return int(any(r["acquisition_status"] == "failed" for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
