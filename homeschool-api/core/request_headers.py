"""
Extra HTTP headers for outbound AI-provider and MCP requests, from config.

Why this exists: providers and gateways keep inventing a header Bede has to
send before they will answer. On 2026-11-17 the demo's Claude backup was
refused because an organization-level Anthropic key needs
``anthropic-workspace-id``; OpenAI has ``OpenAI-Organization`` and
``OpenAI-Project``; a self-hosted gateway in front of a local model often
wants its own; and an MCP server that requires a key has nowhere to receive
one. A named setting per header would mean a code change for every new one,
so instead there is one shape, checked once, used everywhere:

- ``AI_PROVIDER_HEADERS`` (core/config.py): a JSON object keyed by adapter
  name, e.g. ``{"anthropic": {"anthropic-workspace-id": "wrkspc_..."}}``.
- ``MCP_EXTERNAL_SERVERS``: each server entry may carry a ``headers`` object.

The rules, and why each holds:

- Names must be plain HTTP tokens and values must carry no control
  characters, so a value can never end one header and start another (CR/LF
  injection). Checked when Bede starts, so a typo fails loudly at boot rather
  than as a refused lesson.
- A provider's credential stays in its own key setting. Provider headers may
  not set ``Authorization``, ``x-api-key`` or ``api-key``: two places holding
  a key is how the wrong one ends up sent, and how a key ends up somewhere it
  is not treated as a secret.
- MCP servers have no key setting of their own, so their headers MAY carry
  ``Authorization``; that is the only way to give such a server a key.
- Neither may set transport or protocol headers (``Host``, ``Content-Type``,
  ``Content-Length``, ``Cookie``, the MCP session/protocol headers, ...). Those
  belong to the client and overriding them breaks requests in ways that look
  like the provider being down.
- Values are never logged. ``redacted()`` gives the names only.
"""

from __future__ import annotations

import json
import re
from typing import Dict, Iterable, Mapping

#: Every provider adapter Bede has. The router reads its own list from here,
#: so a header map can only name a provider that exists.
PROVIDER_ADAPTERS = ("local", "openai", "mistral", "anthropic")

#: RFC 9110 token characters for a header name.
_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,64}$")
#: Printable ASCII plus space and tab; no CR, LF, NUL or other controls.
_VALUE = re.compile(r"^[\x20-\x7e\t]{0,4096}$")
MAX_HEADERS = 16

#: Owned by the HTTP client or the protocol; never set from config.
_TRANSPORT_HEADERS = frozenset({
    "host", "content-length", "content-type", "transfer-encoding", "connection",
    "keep-alive", "upgrade", "te", "trailer", "expect", "cookie", "set-cookie",
    "accept", "accept-encoding", "user-agent", "proxy-authorization",
    "mcp-session-id", "mcp-protocol-version",
})
#: Where a provider credential would go; providers keep theirs in a key field.
_CREDENTIAL_HEADERS = frozenset({"authorization", "x-api-key", "api-key"})


class HeaderConfigError(ValueError):
    """A configured header map is malformed or names a header it may not set."""


def check_headers(raw: object, *, where: str, allow_credentials: bool) -> Dict[str, str]:
    """Validate one ``{name: value}`` map. Values are not echoed in errors."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise HeaderConfigError(f"{where} must be a JSON object of header name to value.")
    if len(raw) > MAX_HEADERS:
        raise HeaderConfigError(f"{where} sets more than {MAX_HEADERS} headers.")
    out: Dict[str, str] = {}
    seen: set[str] = set()
    for name, value in raw.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise HeaderConfigError(f"{where}: {name!r} is not a valid header name.")
        lowered = name.lower()
        if lowered in seen:
            raise HeaderConfigError(f"{where}: header {name!r} is set twice.")
        seen.add(lowered)
        if lowered in _TRANSPORT_HEADERS:
            raise HeaderConfigError(
                f"{where}: {name!r} is set by Bede's HTTP client and cannot be configured."
            )
        if lowered in _CREDENTIAL_HEADERS and not allow_credentials:
            raise HeaderConfigError(
                f"{where}: {name!r} would carry the API key. Put the key in the "
                "provider's own key setting instead."
            )
        if not isinstance(value, str) or not _VALUE.fullmatch(value):
            raise HeaderConfigError(
                f"{where}: the value for {name!r} must be text with no line breaks "
                "or control characters."
            )
        out[name] = value.strip()
    return out


def parse_provider_headers(
    raw: str, known_adapters: Iterable[str] = PROVIDER_ADAPTERS,
) -> Dict[str, Dict[str, str]]:
    """Parse ``AI_PROVIDER_HEADERS`` into ``{adapter: {name: value}}``."""
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # Position only: the message from json can quote the text, which may
        # hold a value someone considers private.
        raise HeaderConfigError(
            f"AI_PROVIDER_HEADERS is not valid JSON (line {exc.lineno}, column {exc.colno})."
        ) from None
    if not isinstance(data, dict):
        raise HeaderConfigError(
            'AI_PROVIDER_HEADERS must be a JSON object keyed by provider, e.g. '
            '{"anthropic": {"anthropic-workspace-id": "..."}}.'
        )
    known = set(known_adapters)
    out: Dict[str, Dict[str, str]] = {}
    for adapter, headers in data.items():
        if adapter not in known:
            raise HeaderConfigError(
                f"AI_PROVIDER_HEADERS names {adapter!r}, which is not a provider. "
                f"Use one of: {', '.join(sorted(known))}."
            )
        checked = check_headers(
            headers, where=f"AI_PROVIDER_HEADERS[{adapter!r}]", allow_credentials=False,
        )
        if checked:
            out[adapter] = checked
    return out


def redacted(headers: Mapping[str, str]) -> str:
    """Header names only, for logs."""
    return ", ".join(sorted(headers)) or "(none)"
