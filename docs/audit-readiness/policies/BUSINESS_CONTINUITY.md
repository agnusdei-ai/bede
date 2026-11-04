# Business Continuity and Disaster Recovery Policy

**DRAFT for owner approval. Not in effect.** Sections marked
**[OWNER DECISION]** must be decided before approval.

Owner: the designated individual in `docs/INFORMATION_SECURITY_POLICY.md` §2.

## 1. What must keep running, and how fast it must come back

| Service | Recovery time target | Data loss target |
|---|---|---|
| Public demo | **[OWNER DECISION]** | Demo data is kept for 6 hours at most, so a loss of the demo database loses no lasting data |
| Site (`agnusdei.ai`) | **[OWNER DECISION]** | None: the site is rebuilt from the repository |
| License server | **[OWNER DECISION]** | **[OWNER DECISION]** |
| Source repository and CI | **[OWNER DECISION]** | None if a current clone exists outside GitHub |

A family's self-hosted server keeps running if any of these fail, including
lessons, because it does not depend on them at runtime. Licence checks work
offline (`core/license_state.py`).

## 2. Backups

| Data | How it is backed up | Restore tested |
|---|---|---|
| Demo database | **[OWNER DECISION: Render backup setting]** | Not yet; schedule a restore test |
| License server D1 | **[OWNER DECISION: export schedule]** | Not yet |
| Licence signing key and installer signing identities | **[OWNER DECISION: offline storage]** | Check yearly that the stored copy is usable |
| Repository | A clone held outside GitHub **[OWNER DECISION: where]** | — |
| Self-hosted Postgres (families) | `make db-backup` / `make db-restore` | Every merge to `main`: `production-regression.yml` backs up, restores and checks the data survived |

## 3. Testing

- Restore the demo and license server backups at least
  **[OWNER DECISION: once a year]**, and record the date, the time taken, and
  any problem found.
- Run one incident tabletop exercise a year using `docs/INCIDENT_RESPONSE.md`
  and record it in `docs/incidents/`.

## 4. If the owner is unavailable

With one person holding production access, a long absence is itself a
continuity risk. Record who could act, and how they would get access, in
**[OWNER DECISION: a private location]**. Do not record credentials in this
repository.

## 5. Evidence an assessor will sample

- Backup settings for each service.
- Restore test records.
- Tabletop records.
- The CI restore results on `main`.
