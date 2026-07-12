# Bede

A self-hosted, LAN-deployed Catholic Classical homeschool AI tutor. A parent
configures each student's daily plan; students connect from their own tablets.
Claude (the Bede persona) tutors via Socratic dialogue, agentic tools, and
subject-specific personas. All student data is AES-256-GCM encrypted at rest;
voice biometrics authenticate children at session start.

## Where to go next

| I want to... | Read |
|---|---|
| Set up Bede for my family to actually use | [docs/PARENT_SETUP.md](docs/PARENT_SETUP.md) — the full non-technical walkthrough, including the security model to understand before handing a tablet to your child |
| ...the technical/ops reference for that | [docs/PRODUCTION_SETUP.md](docs/PRODUCTION_SETUP.md) — `make setup`, day-to-day commands, database options |
| Show my child how to use it | [docs/CHILD_GUIDE.md](docs/CHILD_GUIDE.md) — written directly to the child |
| Set up Bede's spoken voice | [docs/VOICE_SETUP.md](docs/VOICE_SETUP.md) — OpenAI TTS (`gpt-4o-mini-tts`) |
| Host the public demo | [docs/DEMO_HOSTING.md](docs/DEMO_HOSTING.md) — a Render Blueprint is included |
| Work on the codebase itself | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — local dev for each app, project layout |
| Understand the architecture in depth | [CLAUDE.md](CLAUDE.md) — request flow, prompt structure, streaming state machine |
| See where Bede is headed vs. what's shipped | [docs/ROADMAP.md](docs/ROADMAP.md) — North Star orchestration flow, tracked against implemented/partial/not-started status |

Production (self-hosted, your family's real data) and the public demo
(stateless, cloud-hosted) are deliberately different setups with different
security models — don't mix the two up.

## License

Copyright (c) 2026 Agnus Dei Technologies, LLC. All rights reserved.

Bede is proprietary software, not open source. It's made available for
self-hosted use by your own household or homeschool community — see
[LICENSE](LICENSE) for the full terms. Resale, redistribution, and
commercial use are not permitted without written permission from Agnus
Dei Technologies, LLC.

Bede™ and the Bede name, logo, and persona are trademarks of Agnus Dei
Technologies, LLC.
