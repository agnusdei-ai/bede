"""Input sanitization: injection phrasing, credentials, and markup.

Supports prompts/G08-untrusted-content-envelope.md.

WHERE TO APPLY THIS
-------------------
Not "on user input". The correct test is not provenance, it is REPLAY:

  * Operator- or admin-supplied config fields that sit in a cached prompt block
    for a whole session.                                      -> sanitize
  * Any text retrieved from outside the process (documents, tool results,
    scraped pages, uploads).                                   -> sanitize
  * Any text your own model wrote that summarizes a conversation the user
    steered, IF you persist it and replay it into a later prompt.
                                                               -> sanitize
  * Live per-turn chat text, when it is genuinely transient and there is no
    secret in context for a successful injection to extract.  -> usually not

That third case is the one that gets people. See G08.

Sanitize on BOTH the write path and the read path for persisted text. It is
deliberately redundant: rows written before you found the bug are still live,
and encrypted blobs typically have no migration path.

redact_credentials() has a wider scope than the others -- apply it anywhere free
text enters model context, an audit log, or persisted storage. A pasted API key
in a log is a live credential in a place nobody is watching.
"""

from __future__ import annotations

import re
from typing import Optional

HTML_TAG = re.compile(r"<[^>]{0,200}>")

# Prompt-injection phrasing.
#
# Two design notes worth keeping when you extend this:
#
# 1. The verb-to-target gap is `[^.!?\n]{0,60}?` -- non-greedy AND unable to
#    cross a sentence or line boundary. An earlier version required the target
#    immediately after the qualifier, so it caught "ignore previous
#    instructions" but sailed past "ignore ALL PREVIOUS instructions", the most
#    common phrasing of the attack. A bare `.*?` has the opposite problem: it
#    swallows unrelated prose between a stray verb and a distant noun.
#
# 2. The verb list is deliberately conservative -- ignore/disregard/override
#    only. "skip" and "bypass" were considered and rejected: "skip the
#    instructions on page 4" is something a real person writes, and a false
#    positive here silently mangles their text.
INJECTION_PATTERN = re.compile(
    r"((?:ignore|disregard|override)\b[^.!?\n]{0,60}?\binstructions?\b"
    r"|(?:reveal|show|print|repeat|output|display)\b[^.!?\n]{0,40}?\b(?:system\s+)?prompt\b"
    r"|\bsystem\s*:"
    r"|\[INST\]"
    r"|<<SYS>>"
    r"|<\|im_start\|>"
    r"|\bpretend\s+you\s+are\b"
    r"|\byour\s+(true\s+)?(name|identity|role)\s+is\b"
    r"|\bforget\s+(everything|your|all)\b"
    r"|\bnew\s+instructions?\b)",
    re.IGNORECASE | re.DOTALL,
)

# Credential shapes someone might paste into a text field: provider API keys,
# AWS/GitHub/Slack tokens, JWTs, Bearer headers, and user:pass@host connection
# strings.
CREDENTIAL_PATTERN = re.compile(
    r"(sk-(?:ant|proj|live|test)?-?[A-Za-z0-9_-]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|gh[pousr]_[A-Za-z0-9]{36,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"|[A-Za-z][A-Za-z0-9+.-]*://[^\s:/@]+:[^\s@/]+@[^\s]+"
    r"|(?i:bearer)\s+[A-Za-z0-9\-._~+/]{20,}=*)"
)

REDACTION_MARKER = "[redacted-credential]"
REMOVAL_MARKER = "[removed]"


def redact_credentials(value: Optional[str]) -> Optional[str]:
    """Replace credential-shaped substrings so a pasted secret never reaches
    model context, an audit log, or persisted storage."""
    if not value:
        return value
    return CREDENTIAL_PATTERN.sub(REDACTION_MARKER, value)


def strip_injection(value: Optional[str]) -> Optional[str]:
    """Replace prompt-injection phrasing with a visible marker.

    A marker rather than silent deletion: the remaining text should read as
    obviously modified, both to a human reviewing it and to the model, which
    should treat a field containing [removed] as suspect.
    """
    if not value:
        return value
    return INJECTION_PATTERN.sub(REMOVAL_MARKER, value)


def sanitize_field(value: Optional[str], max_len: int = 500) -> Optional[str]:
    """Full pass for a text field that will sit in prompt context.

    Returns None for a field that sanitizes down to nothing -- so the caller can
    treat it as absent rather than rendering an empty block. Callers should
    branch on None rather than emitting an empty section, since an empty
    labelled section reads to the model as "this exists and is blank".
    """
    if not value:
        return value
    cleaned = HTML_TAG.sub("", value)
    cleaned = strip_injection(cleaned) or ""
    cleaned = redact_credentials(cleaned) or ""
    cleaned = cleaned.strip()[:max_len]
    return cleaned or None
