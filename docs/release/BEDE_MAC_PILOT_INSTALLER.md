# Bede Mac pilot installation

## One entry point

The Bede Installer.app packaged inside Bede Pilot Mac arm64.dmg is the only Mac pilot installation entry point. The browser setup page is part of the same installation journey and uses the same Bede portrait, colors and language.

Older scripts such as setup-gui.command, Install-Bede.command and source checkout instructions remain internal development compatibility tools. They are not supported Mac pilot distribution methods and must not be delivered as alternatives to the native application.

The app copies sealed runtime files into the current user's Application Support/Bede Pilot directory so the signed application is not used for mutable configuration. It starts the operator runtime, opens the local browser setup when the approved license is entered, and only reports completion after the HTTPS health probe succeeds.

## Experience

The application shows these verified stages: Checking this Mac, Preparing Bede, Completing setup, Starting Bede, Confirming secure access. The active stage shows a spinner and completed stages show a check. The output of the runtime stages is the authoritative source for progress; there is no time based simulated percentage.

The browser wizard uses the same Bede image and neutral language. Cancel means setup is not complete. A completed form means only that the settings were saved, not that the API has started. Final completion is based on the verified local HTTPS health check.

## Pilot prerequisites

The synthetic pilot requires a manually authorized compatible license, a supported working container engine and architecture, approved model access, and a trusted local or private network HTTPS origin. The current embedded signing public key still requires a matching private issuing key for the license. This PR does not generate or replace it.

## Release gate

This PR is not evidence of a signed or notarized Mac release. The GitHub job creates an ad hoc signed ARM64 test DMG for physical qualification only. Developer ID signing, notarization, hardware testing, installer cancel safety, passkey checks and G1/G2/G3 evidence must pass before declaring the pilot ready. No real learners before separate owner Pilot GO.

## Deferred

No Stripe, billing, production signing key custody, Cloudflare license Worker, entitlement automation, or student data is introduced here. Commercial licensing is a separate sprint.
