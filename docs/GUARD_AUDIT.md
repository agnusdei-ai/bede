# Guard audit: which controls can actually still fire

A guard that has never been observed failing is **unverified, not proven** —
and an unverified guard is worse than none, because it buys silence. This
document records what happened when each guard was deliberately broken.

The method is mutation, not review: neuter the guard in the source, run the
whole suite, record whether anything goes red, restore. It answers one
question precisely — *would we notice if this stopped working?*

Last run: 2026-08-04, against 2179 backend tests.

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

Eleven of twelve were already load-bearing and proven. Two needed work.

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

## Not yet probed

Stated rather than left to be assumed:

- Rate limiting, `LicenseGate`, `SecurityHeaders`
- `require_parent` / `require_real_user` role separation
- Parent lockout, and recovery's "at least 2 of 3 factors" rule
- `ExfiltrationGuard`'s response-body key-material scan (distinct from the
  endpoint blocklist above, which was probed)
- Encryption at rest, container hardening (`read_only`, `cap_drop`, no shell)
  — deployment-level, not reachable from an in-process suite; these belong to
  `docs/environment-pentests/`

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
