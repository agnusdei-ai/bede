"""
Bede Diagnostic Engine — pure-Python CDM/IRT/KST core.

See docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md for the full design and
docs/diagnostic/DIAGNOSTIC_LOOP.md for the runtime S1-S9 loop this package
implements piece by piece, per docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md.

The public façade (process_evidence, get_next_probe_hint) lands in unit
1.8, once the modules it composes (qmatrix, irt, cdm, kst, cat, mastery)
exist. This file is intentionally minimal until then — no premature import
surface for modules that don't exist yet.
"""
