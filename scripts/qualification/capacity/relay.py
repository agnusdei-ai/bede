#!/usr/bin/env python3
"""Give each sample device its own network address.

    python relay.py --spec 127.0.0.1:19000=127.0.0.11>127.0.0.1:18400 [--spec ...]

Each spec is LISTEN=SOURCE>UPSTREAM: accept on LISTEN, and open the matching
upstream connection FROM the address SOURCE. A browser cannot choose its own
source address; pointing browser i at relay i makes its traffic arrive from
address i, the way a household's tablets each arrive from their own LAN
address. Plain TCP, so TLS passes through untouched.

Why it exists: the per-IP rate limit (core/middleware.py) keys on the client
address. Ten browsers on one runner share one address, which no household
has, and would measure the rate limit of a single shared device instead of
the server. See docs/CAPACITY.md.
"""
from __future__ import annotations

import argparse
import asyncio
import signal


def parse(spec: str) -> tuple[tuple[str, int], str, tuple[str, int]]:
    listen, _, rest = spec.partition("=")
    source, _, upstream = rest.partition(">")
    if not (listen and source and upstream):
        raise ValueError(f"bad spec {spec!r}: want LISTEN=SOURCE>UPSTREAM")
    lh, _, lp = listen.rpartition(":")
    uh, _, up = upstream.rpartition(":")
    return (lh, int(lp)), source, (uh, int(up))


async def _pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
    try:
        while data := await r.read(65536):
            w.write(data)
            await w.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            w.close()
        except Exception:
            pass


async def serve(specs: list[str]) -> None:
    servers = []
    for spec in specs:
        listen, source, upstream = parse(spec)

        async def handle(cr, cw, source=source, upstream=upstream):
            try:
                ur, uw = await asyncio.open_connection(*upstream, local_addr=(source, 0))
            except OSError:
                cw.close()
                return
            await asyncio.gather(_pipe(cr, uw), _pipe(ur, cw))

        servers.append(await asyncio.start_server(handle, *listen, backlog=512))
    print("relay ready", len(servers), flush=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    for s in servers:
        s.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", action="append", required=True)
    asyncio.run(serve(ap.parse_args().spec))


if __name__ == "__main__":
    main()
