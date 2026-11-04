# Bede iPhone/iPad RC1 — frozen-client signing

**Status: engineering candidate / release HOLD.** This is not the demo app, a macOS installer, or a certified working IPA. The signed candidate targets iPhone and iPad, bundle ID `ai.agnusdei.bede`, version `1.0.0`, build `1`, label **RC1**.

## Apple Account signing

An Apple Account added to Xcode can select a free **Personal Team** for local on-device development signing. In Xcode > Settings > Accounts, sign in on the owner's Mac and enable automatic signing for the App target. Never place credentials, device identifiers or certificates in the repository, in a public CI run, or in chat.

On a Mac with Xcode, Node 22+, and the approved clean checkout, set `BEDE_RC1_SOURCE_SHA` to the approved full commit hash; `BEDE_APPLE_TEAM_ID` and `BEDE_IOS_DEVICE_ID` come from Xcode. Run `bash scripts/ios/build-rc1-personal.sh`. The script builds and bundles the web client, synchronizes Capacitor, fails if a remote frontend URL appears, requests Xcode automatic development signing, verifies the signed app, and writes evidence in `~/Library/Developer/Bede/ios-rc1-*/`. Install through Xcode on a registered iPhone or iPad.

Apple's **free** provisioning profile expires after **7 days** and must be renewed/reinstalled. For Ad Hoc IPA distribution to registered devices or TestFlight distribution, paid Apple Developer Program membership is required. The no-update policy does not override profile expiration.

## Immutable RC1 policy

- Native assets (HTML, CSS, JavaScript and locales) are compiled into the signed app. `server.url` is forbidden; native service-worker registration is disabled. The web/PWA behavior is unchanged.
- The source SHA and lockfile are pinned at build; there is no over-the-air updater in this packaging route. Any change requires a new explicit candidate, not a silently updated RC1.
- This iPhone/iPad app is a client, **not** an on-device deployment of the Bede inference server or AI model.

## Important blocker — do not publish yet

The current application makes same-origin `/api` requests and uses HTTPS-origin WebAuthn. Bundled Capacitor code runs from `capacitor://localhost`. As written, that bundled client cannot simply talk to the existing Bede backend, and educator/parent passkey reliance on the HTTPS origin must not be assumed to work. Integrate and physically test a correctly scoped native HTTPS API and passkey path, without disabling CORS, TLS checks, MFA or authorization. Until that is proven, the signed app is **only an engineering candidate, not a functional RC1 release**.

## Physical acceptance gate

On the exact signed candidate, verify both iPhone and iPad: native install, portrait/landscape, SHA and icon; immutable native UI after restart; trusted HTTPS reachability; parent/educator/learner login and passkeys; role denial/cross-campus isolation and revocation; tutoring and voice streaming, transcription, handwriting and progress; English and Spanish locales; airplane mode, recovery and deletion. Record device/iOS/Xcode versions, artifact checksum, code-signing evidence and an explicit GO/HOLD decision. Do not claim physical results from an Xcode compile alone.
