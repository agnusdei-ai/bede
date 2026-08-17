# Reference Implementation

Dependency-free Python (3.10+, standard library only) implementing the
enforcement layer. Copy the modules you want into your project; there is no
package to install and nothing to import from a registry.

| Module | Implements | Prompt |
|---|---|---|
| `constitution.py` | Digest + structure verification, immutable load, preamble rendering | [G01](../prompts/G01-constitution-preamble.md) |
| `sanitization.py` | Injection stripping, credential redaction, field sanitization | [G08](../prompts/G08-untrusted-content-envelope.md) |
| `adversarial_detection.py` | Tier-1 deterministic detection, signal assembly | [G05](../prompts/G05-safeguarding-escalation.md), [G12](../prompts/G12-moderation-classifier.md) |
| `policy_engine.py` | The pure decision function and its tiering | [G12](../prompts/G12-moderation-classifier.md) |
| `tool_registry.py` | Tool trust tiers, loop bounds, the structural external-tool bar | [G06](../prompts/G06-tool-use-discipline.md) |
| `external_content.py` | Sanitize → namespace → envelope pipeline | [G08](../prompts/G08-untrusted-content-envelope.md) |
| `pin_digest.py` | CLI to compute and verify a constitution digest | [G01](../prompts/G01-constitution-preamble.md) |

## Running the tests

```bash
cd governance-kit/reference
python -m pytest tests -q
```

The tests are worth reading before the modules. Several of them exist
specifically to demonstrate the **verify-by-breaking** discipline described in
[`../docs/PHILOSOPHY.md`](../docs/PHILOSOPHY.md): they construct the defect the
control exists to prevent and assert that the control catches it. A guard that
does not fail when the behavior regresses is decoration.

## What is deliberately not here

**No model client, no HTTP, no framework.** Every module is importable from
anywhere in your process, including code that runs before your framework is
initialized. That is the whole reason the constitution loader can verify at
import time.

**No handler bodies.** `tool_registry.py` declares what a tool *is*; your loop
keeps owning what it *does*. See that module's docstring for why hoisting
handlers into the registry is a worse design than it looks.

**No classifier call.** [G12](../prompts/G12-moderation-classifier.md) gives you
the prompt and the tiering table; the call itself is three lines against
whatever client you already have, and writing it yourself keeps this package
free of a vendor SDK.

## Adapting the modules

Three files have placeholders you must fill in before they do anything useful:

- `constitution.py`: `CONSTITUTION_PATH`, `PINNED_SHA256`, `EXPECTED_ID`,
  `REQUIRED_VALUE_NAMES`. **Delete the `try/except` at the bottom.** It exists
  so the kit imports standalone; in your deployment a failed verification must
  be fatal.
- `tool_registry.py`: replace `_SPECS` with your own tools, and tune the two
  caps.
- `adversarial_detection.py`: the patterns are a starting point. Extend them
  for your domain, and re-read the note about why social engineering has no
  Tier-1 pattern before adding one.
