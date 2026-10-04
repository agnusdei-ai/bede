# Selling Bede

**The operator's side of a sale.** `docs/PRODUCTION_SETUP.md#licensing` covers
what a *family* does with a license key. This covers what *you* do to produce
one, and it exists because that was the only undocumented step between a
hardened product and a sold one.

**You can sell Bede on Linux today, with no license server and no checkout
code.** Nothing here is a workaround.
[`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) §11 plans an automated
pipeline across four phases, and says in Phase 1 that "manual paste into
`/admin/license` still works exactly as today" and in Phase 4 that
hand-issued licenses get migrated into it. Hand issuance is the anticipated
starting state, not a thing to be apologised for.

---

## Why this is trustworthy today

`.github/workflows/production-regression.yml` rehearses this exact path on
every merge to `main`, and `main` is the release
([`RELEASE_QUALITY_GATES.md`](RELEASE_QUALITY_GATES.md)). In one job it:

1. mints a signed `LICENSE_KEY` with the same code you will use,
2. runs the real setup wizard and submits the real form,
3. verifies the generated `.env`,
4. boots the full stack exactly as the wizard configured it,
5. **asserts the license gate actually lifted** — a blocking step, because
   the two revisions before it left the job green while the gate went
   unverified, and an annotation is a message where only a non-zero exit is a
   gate,
6. confirms the no-CLI tablet-trust page works end to end,
7. confirms `make db-restore` recovers genuinely lost data, and that every
   table is still decryptable afterwards.

So the claim "a paid Linux install works" is not an argument from reading the
code. It is a green job, re-proved on every merge.

---

## One-time: the signing key

Licenses are Ed25519-signed and verified **offline**, against
`PUBLIC_KEY_PEM` embedded in `homeschool-api/core/licensing.py`. No install
ever phones home; a family's server needs no outbound network access to prove
it is licensed.

A public key is already embedded, so **the first question is whether you still
hold the private half that matches it.** Check before your first sale, not
during it:

```bash
cd homeschool-api
python scripts/issue_license.py --tier core --licensee "Key check" \
    --seats 6 --days 1 --private-key /path/to/your/private.pem
```

Then paste the printed key into a scratch `.env` and boot, or feed it to
`core.licensing.verify_license()` directly. If it verifies, you are ready. If
it does not, the embedded public key belongs to a keypair you no longer have,
and you need a new one:

```bash
python scripts/generate_license_keypair.py
```

That prints the pair once and stores neither. Put the **private** key somewhere
offline — a password manager or an encrypted drive — because anyone holding it
can mint any tier at any seat count for any name. Paste the **public** key into
`PUBLIC_KEY_PEM` and ship that change like any other.

Shipping a new public key invalidates every license signed by the old one. With
no customers yet that costs nothing; after your first sale it is a migration.
**Settle the key before you sell anything.**

---

## Fulfilling one order

### 1. Take the money, outside this repository

There is deliberately no payment code here, and for annual billing you do not
need any. A Stripe payment link, an invoice, or an ACH transfer all work, and
none of them touch Bede. Prices are
[decision register entry 10](DECISIONS.md); they are deliberately unpublished
([entry 9](DECISIONS.md)), so quote them yourself rather than putting them on a
page.

### 2. Mint the key

```bash
cd homeschool-api

# A Family Membership — up to 6 children, one year
python scripts/issue_license.py --tier core \
    --licensee "The Whitfield Family" --seats 6 --days 365 \
    --private-key ~/.bede-license-private.pem

# A Co-op Membership — ten-family minimum, so size seats to the co-op
python scripts/issue_license.py --tier coop \
    --licensee "St. Cecilia Homeschool Co-op" --seats 60 --days 365 \
    --private-key ~/.bede-license-private.pem
```

Two things about this command are load-bearing.

**`--seats` is the child cap, and it is enforced.** `routers/pod.py` compares
the pod's student count against the `seats` value signed into the license and
refuses to save beyond it. Entry 10 records that the Family Membership's
six-child cap "has no implementation" — that is true of the *tier name*, which
knows nothing about the current pricing model, and not of the *cap*, which
works today as long as you mint with `--seats 6`. A family that needs more
children needs a new key, which is also how an upsell is priced.

**The tier vocabulary does not match the price list, and that is recorded
rather than broken.** The signed tiers are `trial`, `core` and `coop`;
the commercial memberships are Family, Co-op and Network. Map `core` →
Family Membership and `coop` → Co-op or Network (sized by seats).
[Entry 28](DECISIONS.md) ruled that there is **no implicit mapping** between
the two vocabularies and that the signed license governs wherever they
disagree, so doing this by hand at mint time is the sanctioned behaviour, not
a shortcut around it. [Entry 7](DECISIONS.md) is the open entry that would
reconcile the names, and it is not in the way of selling.

`--tier trial` exists for your own evaluations and demos. It is **not** a
product: [entry 29](DECISIONS.md) rules out a commercial trial tier, and
[entry 28](DECISIONS.md) forbids reading a commercial meaning off a signed
one. A trial key must always carry `--days`, which the script enforces.

### 3. Deliver it

Send the `LICENSE_KEY=...` line and point the family at
[`PRODUCTION_SETUP.md`](PRODUCTION_SETUP.md). Nothing about it is secret in
transit the way a password is — it authorises one household's install and
carries their own name — so ordinary email is fine.

### 4. They install

Linux and macOS both run one script:

```bash
bash packaging/unix/install.sh
```

It detects the distro family and architecture (Debian/Ubuntu and Arch;
`x86_64` and `arm64`), offers to install Ollama and pull a
hardware-appropriate model for a family that wants Bede's AI entirely on their
own machine, and hands off to the same browser wizard as every other entry
point. The wizard asks for the license key at install time. See
[`UNIX_INSTALLER.md`](UNIX_INSTALLER.md).

One honest caveat to set expectations with: **no ARM build has ever been
booted on real hardware** ([entry 23](DECISIONS.md)).
`.github/workflows/arm64-build-check.yml` builds the image and imports the
risky dependencies under emulation, which is real evidence and is not a boot.
Until someone boots a Raspberry Pi, sell `x86_64` and treat ARM as
unverified — the installer accepting the architecture is not the same claim.

### 5. Confirm it took

Ask them to open Setup and look at the **License** card, which shows tier,
licensee, seats and expiry. If anything is wrong, a corrected key pastes
straight into that card — see renewals below.

---

## Renewals, upgrades and more children

Mint a new key and have the parent paste it into the License card
(`POST /admin/license`). `core/license_state.py` makes the database-applied
key win over the `.env` `LICENSE_KEY`, live, with **no restart and no file
edit** — the same precedence `parent_credential.py` and `provider_state.py`
use. This is the whole reason a renewal is not a support visit.

The endpoint is behind privileged elevation (`require_elevated_parent`), so
the parent re-proves their password, and `ElevationPrompt.tsx` handles that
prompt without the License card knowing elevation exists.

---

## Trials, and what makes one actually end

A trial is a signed license with an expiry and nothing else:

```bash
python scripts/issue_license.py --tier trial \
    --licensee "trial-a1b2c3" --seats 6 --days 30 \
    --private-key ~/.bede-license-private.pem
```

`--days` is **required** for `--tier trial` and the script enforces it, because
a trial that cannot expire is not a trial. [Entry 29](DECISIONS.md) sanctions
exactly this shape — *"a signed-license tier only, verified by
`core/licensing.py`, expiring, and carrying no commercial meaning"* — while
forbidding a fourth *commercial* tier. So a 30-day trial is in scope; a
"Trial Membership" alongside Family/Co-op/Network is not.

**What makes it end is `main.py`'s `_refresh_license_once`, and before that
existed nothing did.** `core/license_state.py`'s `current()` returns a cached
verdict, and `refresh()` ran only at startup and when a key was pasted.
`docker-compose.yml` runs the API under `restart: unless-stopped`, which
restarts on a crash or a host reboot and never on a schedule — so a family's
LAN server kept its boot-time verdict indefinitely, and on day 31 the gate
simply did not go up. **The trial became perpetual**, which is what
[entry 2](DECISIONS.md) rejected ("Pay-per-use, never zero"), arrived at by a
cached variable rather than by a decision. A daily re-evaluation closes it;
daily is the right cadence because `LicenseInfo.is_expired` is
`expires < date.today()`, so the verdict can only change at local midnight.

**What a family sees.** Inside the notice window the License card in Parent
Setup shows the remaining days, and in the last three it opens itself rather
than leaving a chip to be noticed. That window is proportional to the term —
10% of it, floored at a week and capped at a month — because a flat 30 days
is correct for an annual membership and is lit for the whole of a 30-day
trial, which tells a parent nothing. Past expiry the API answers
`license_required` on everything but login and license management, and the
parent pastes a key to continue.

**Self-service trials do not exist yet.** The key above is minted by hand with
your private key. A visitor requesting one and receiving it without you
touching anything is `LICENSE_SERVER_DESIGN.md` §11 **Phase 1** — "the
self-serve no-card trial flow and automated paid issuance + email" — which is
unbuilt. Hand-issued trials work today; self-service ones are Phase 1.

---

## Annual ships today. Monthly needs fulfilment, not enforcement.

This section said monthly needed §11 **Phase 2** (`install_id`,
`/v1/activate`, server-reported status overriding signed expiry). That was
wrong in an instructive way, and both halves of the correction matter.

**Enforcement is solved, by the commercial terms plus the daily refresh.** A
30-day cancellation notice with a prepaid final month means you are always
paid through at least the next 30 days. So a key dated *paid-through plus the
deposit month plus a few days' grace* expires exactly when your coverage
ends — and now actually takes effect, because the verdict is re-evaluated
daily rather than cached until a restart. Non-payment resolves itself. **No
revocation, no phone-home, no activation server.** The offline design was
never the obstacle; the cached verdict was.

**What monthly still needs is fulfilment.** Someone or something must mint a
fresh key each month and the parent must paste it. By hand that is one task
per customer per month and a paste a family should not have to remember — bad
at ten customers and unworkable at two hundred. That is §11 **Phase 1**
(automated issuance and delivery by email), a Cloudflare Worker, and a
considerably smaller build than Phase 2.

An interim that costs nothing: issue a key for the committed term (a year for
annual, a quarter for monthly) and let the deposit and the notice period carry
non-payment. You trade precision for zero friction, and the daily refresh
still makes the expiry real whenever it lands.

**[Entry 26](DECISIONS.md) remains open and this does not close it.** Its
question is the shared *contract vocabulary* — `BEDE_LOCUTO_ENTITLEMENT_CONTRACT.md`
describes only an annual prepaid term, and a checkout cannot mint an
entitlement in a shape the contract has no words for. That is a commercial
ruling, and a cross-repository one. Enforcement being solved is an input to
it, not an answer.

---

## What hand issuance does not give you

Each of these is a reason to build the license server eventually, and none is
a reason to delay a first sale.

| Not available | Consequence | Where it lands |
| --- | --- | --- |
| Revocation before expiry | A key verifies until its own expiry date, which is now genuinely enforced daily — but you cannot cut it short. Short-date the key instead, or handle it commercially. | §11 Phase 2 |
| Activation limits | Nothing stops one household's key being used on a second server. `core/licensing.py` says plainly that this is a trust-and-verify gate for honest self-hosters, not DRM — and every self-hoster has the source anyway. | §11 Phase 2 (`max_activations` = 2) |
| Automated issuance and delivery | You mint and send each key by hand. Fine at ten customers; not at two hundred. | §11 Phase 1 |
| A customer record | The only record a sale leaves is your own invoice. Keep a ledger from the first sale — customer, licensee string, tier, seats, issue date, expiry — because Phase 4 migrates existing licenses into the server's database and will need exactly that. | §11 Phase 4 |
| Monthly re-issue | Enforcement works (the daily refresh), but a fresh key each month is minted and pasted by hand. | §11 Phase 1 |

---

## Before the first sale, in order

1. **Confirm the private key matches the embedded public key.** Everything
   else is downstream of this, and it is the one step that gets more expensive
   the longer it waits.
2. **Decide annual or monthly.** Both are enforceable now; monthly additionally
   means minting and pasting a key each month until §11 Phase 1 automates it,
   and [entry 26](DECISIONS.md) still owes a ruling on the contract vocabulary.
3. **Start the ledger** in step 1's own spreadsheet, not later.
4. **Sell `x86_64`.** Treat ARM as unverified until a board boots
   ([entry 23](DECISIONS.md)).
5. **Mint `--seats 6`** for a Family Membership, so the published cap is the
   enforced one.

---

## Related

- [`PRODUCTION_SETUP.md`](PRODUCTION_SETUP.md) — the family's install and the
  License card
- [`UNIX_INSTALLER.md`](UNIX_INSTALLER.md) — the Linux and macOS installer
- [`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) — the automated
  pipeline this precedes
- [`DECISIONS.md`](DECISIONS.md) — entries 7, 9, 10, 23, 26, 28, 29
- `homeschool-api/core/licensing.py`, `core/license_state.py`,
  `scripts/issue_license.py`, `scripts/generate_license_keypair.py`
