# Wizard narration audio

Empty by default. Run `scripts/setup_wizard/generate_narration.py` once
(needs `OPENAI_API_KEY` and network access — a maintainer/build step, not
something end users run) to produce `welcome.wav` and `success.wav` here,
then commit them. The setup wizard plays them automatically if present and
silently skips narration if not — nothing else depends on this directory
being populated.
