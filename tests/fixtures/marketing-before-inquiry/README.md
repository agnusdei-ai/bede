# Retired marketing forms and membership chooser

These are frozen copies of the marketing pages before the owner approved an
email-inquiry-only offer. They are test fixtures, not public routes or build
inputs. The old form and chooser scripts remain covered against these fixtures;
the active website must not depend on them.

Current production-page behavior, including both inquiry inboxes, absence of
checkout and forms, complete assets, and progressive motion, is checked by
`scripts/bede-production.test.mjs` as part of the demo test command.

When introducing payment or form features again, explicitly approve that product
change and test the new live markup rather than treating these fixtures as the
current offer.
