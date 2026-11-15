"""Bede's pre-release repair loop: the deterministic half.

Nothing in this package calls a model, holds a secret, merges, or deploys.
The AI roles (triage, reproduce, repair, review) are Claude Code sessions
coordinated outside CI; this package decides what their results are worth.
See docs/release/REPAIR_LOOP.md.
"""
