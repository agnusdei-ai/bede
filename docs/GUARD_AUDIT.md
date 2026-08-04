# Guard audit: which controls can actually still fire

A guard that has never been observed failing is **unverified, not proven** —
and an unverified guard is worse than none, because it buys silence. This
document records what happened when each guard was deliberately broken.

The method is mutation, not review: neuter the guard in the source, run the
whole suite, record whether anything goes red, restore. It answers one
question precisely — *would we notice if this stopped working?*

Last run: 2026-08-04, four rounds, against 2181 backend tests.

## Why this exists

Two failures on the same day motivated it, and neither was a missing guard.

`.github/workflows/keep-demo-warm.yml` had been green for months while
delivering roughly a seventh of what it promised — the run history was never
checked, so it read as coverage. See `docs/DEMO_HOSTING.md`.

And in `tests/test_transcription_provider.py`, an assertion that `torch` stays
unimported would have passed for free in any environment where torch was not
installed. It only became evidence once a positive control proved the import
*does* happen on the other path.

Both are the same shape: a guard that cannot fail in the way that matters.

## Results

| Guard | Kind | Verdict |
|---|---|---|
| JWT IP + User-Agent fingerprint binding | security | CAUGHT |
| `credentials_version` (`cv` claim) | security | CAUGHT |
| Streaming-session ownership — chunk path | security | CAUGHT |
| Streaming-session ownership — SSE read path | security | **HUNG → CAUGHT** |
| Constitution SHA-256 digest at import | security | CAUGHT |
| `_sanitize_parent_field` — injection stripping | security | CAUGHT |
| `_sanitize_parent_field` — HTML stripping | security | CAUGHT |
| `_redact_credentials` | security | CAUGHT |
| `ExfiltrationGuard` — blocked endpoints | security | CAUGHT |
| `check_safeguarding` crisis patterns | safety | CAUGHT |
| `_MAX_TOOL_LOOP_ROUNDS` | safety | CAUGHT |
| `_MAX_TOOL_CALLS_PER_TURN` | safety | **UNCAUGHT → CAUGHT** |
| Account recovery `_REQUIRED_FACTORS = 2` | security | CAUGHT |
| Recovery refuses below the factor threshold | security | CAUGHT |
| `require_parent` authorization | security | CAUGHT |
| `require_real_user` rejects `demo_code` | security | CAUGHT |
| `LicenseGate` on an unlicensed deployment | security | CAUGHT |
| `ExfiltrationGuard` response-body key scan | security | CAUGHT |
| Parent lockout duration | security | CAUGHT |
| Per-IP rate limiting | security | CAUGHT |
| SecurityHeaders CSP content | security | **UNCAUGHT → CAUGHT** |

**Twenty-one guards probed. Nineteen already proven. Two were not, and one
failed illegibly.**

Both failures are the same species, and it is worth naming: a test that reads
like coverage while asserting something weaker than the property it names.
One asserted against the constant it was testing; the other asserted a header
was *present* rather than what it *said*.

### `_MAX_TOOL_CALLS_PER_TURN` was untested in the way that counts

Raising it from 6 to **10,000** left all 2179 tests green.

`tests/test_tool_call_audit.py` looked like thorough coverage of the cap, but
every assertion derived its expectation from the constant it was testing:

```python
cap = ai_service._MAX_TOOL_CALLS_PER_TURN
chunks = await _run_turn([_HINT] * (cap + over_by))
assert len(tool_chunks) == cap
```

With the cap at 10,000 the test built a turn of 10,003 calls and asserted
10,000 executed. They did. It passed. The test proves the code enforces
whatever number is in the constant — never that a bound exists.

This matters because CLAUDE.md documents this cap as the **Action Validator**
stage of the adversarial-resilience pipeline. Nothing would have caught it
being raised out of usefulness.

Fixed with two tests written against **literals, never the constant**: the cap
must sit within a sane band (`1..12`), and a turn asking for 40 tool calls must
receive far fewer. Both fail under the original mutation.

### The ownership check failed illegibly

Removing the owner check from `events()` did not fail the suite — it made it
**hang**, with no result in 900 seconds, which also killed the audit harness.

That still counts as caught, in that CI would never go green. But a timeout
carries no failing test name and reads as flaky infrastructure, so the natural
response is to retry the job rather than investigate. A foreign caller was
being handed a real session whose queue nothing would ever write to, and the
unbounded `async for` blocked forever.

`test_events_reports_unknown_for_a_different_owner` now drains under
`asyncio.wait_for(..., timeout=5)`. Same mutation now fails by name in about
nine seconds.

**A guard is only as good as the legibility of its failure.**

### The CSP was asserted by presence, not content

Changing `frame-ancestors 'none'` to `frame-ancestors *` — removing
clickjacking protection outright — left all 2181 tests green.

`test_security_headers_are_present` did this:

```python
assert "Content-Security-Policy" in resp.headers
```

which `default-src *` satisfies exactly as well as the real policy. A header
that exists and permits everything is indistinguishable from no header, except
that it reads as covered.

Not a total exposure — `X-Frame-Options: DENY` is asserted properly alongside
it and still denies framing in browsers that honour it. But `frame-ancestors`
is the modern control and `X-Frame-Options` is deprecated, so the CSP has to
hold on its own.

Now pinned by four content assertions: framing denied outright, the
directives that matter confined to `'self'`, no `unsafe-eval` anywhere and
`unsafe-inline` confined to `style-src` (Tailwind needs it), and no wildcard
source in any directive. Two of the four fail under the original mutation.

## Not yet probed

Stated rather than left to be assumed:

- Encryption at rest, container hardening (`read_only`, `cap_drop`, no shell),
  TLS configuration — deployment-level, not reachable from an in-process
  suite. These belong to `docs/environment-pentests/` and need a running
  instance rather than a test run.

One is **unprovable by test on principle**: `hmac.compare_digest` defends
against timing analysis, and swapping it for `==` passes every functional
assertion. It is justified by reasoning, not evidence, and should stay.

## The standing rule

1. Every guard must be **able to fail**, and someone must have **seen it
   fail**. Flip each new assertion against the broken code before shipping it.
2. A test must never derive its expected value from the thing under test.
   Assert against a literal, or against the property rather than the constant.
3. Prefer a guard that fails **loudly and by name** over one that hangs, times
   out, or degrades silently.
4. Re-run this audit when a guard is added or materially changed. The harness
   is a few dozen lines; the value is entirely in running it.
