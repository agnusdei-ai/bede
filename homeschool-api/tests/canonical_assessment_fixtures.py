"""Synthetic canonical-assessment fixtures, driven through the REAL app over HTTP.

Entirely fabricated: Synthetic Campus One / Two, Synthetic Teacher One /
Two, Synthetic Learner One / Two. The two learners deliberately share one
display name. Form ids, scores, cut points and dates are invented and
correspond to no real report. Never replace these with exported records.

``World`` seeds campuses/learners/grants through the real ``/pilot`` admin
routes with a minted verified-passkey administrator token; educator
accounts are provisioned through ``services.educator_access`` (identity
provisioning has no non-ceremony HTTP route), and every educator token is
minted with exactly the claims ``routers/educator_passkeys.login_verify``
issues and bound to the TestClient's fingerprint, so the real
``require_educator`` chain validates it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from core.middleware import compute_fingerprint
from core.security import create_access_token
from services.educator_access import provision_educator

SHARED_DISPLAY_NAME = "Synthetic Learner"
FIRST_DATA_DAY = date(2031, 8, 25)  # fabricated, far from any real school year
FORM = "SYN-FORM-1"
PM_FORM = "SYN-PM-FORM-1"

_FP = compute_fingerprint("testclient", "testclient")


def _mint(claims: dict) -> dict:
    token = create_access_token(claims, fingerprint=_FP, expires_delta=timedelta(minutes=30))
    return {"Authorization": f"Bearer {token}"}


ADMIN = _mint({"role": "parent", "auth_method": "webauthn_uv"})


@dataclass
class Teacher:
    id: str
    ev: int = 1

    @property
    def headers(self) -> dict:
        return _mint({"role": "educator", "sub": self.id, "ev": self.ev,
                      "auth_method": "webauthn_uv"})


@dataclass
class World:
    client: object
    campus_one: str = ""
    campus_two: str = ""
    learner_one: str = ""
    learner_two: str = ""
    teacher_one: Teacher | None = None
    teacher_two: Teacher | None = None
    _seq: int = field(default=0)

    # ── seeding ────────────────────────────────────────────────────────────
    def seed(self, *, calendar: bool = True, benchmark_auth: bool = True) -> "World":
        c = self.client
        factory = c.db_factory

        async def _teachers():
            async with factory() as s:
                a = await provision_educator(s, "synthetic.teacher.one", "synthetic-passphrase-one-x")
                b = await provision_educator(s, "synthetic.teacher.two", "synthetic-passphrase-two-x")
                return a["id"], b["id"]

        one, two = c.portal.call(_teachers)
        self.teacher_one, self.teacher_two = Teacher(one), Teacher(two)
        self.campus_one = self._ok(c.post("/pilot/campuses", json={"title": "Synthetic Campus One"},
                                          headers=ADMIN), 201)["campus_id"]
        self.campus_two = self._ok(c.post("/pilot/campuses", json={"title": "Synthetic Campus Two"},
                                          headers=ADMIN), 201)["campus_id"]
        for campus in (self.campus_one, self.campus_two):
            self.authorize_campus(campus)
        self.learner_one = self._ok(c.post(f"/pilot/campuses/{self.campus_one}/learners",
                                           json={"display_name": SHARED_DISPLAY_NAME},
                                           headers=ADMIN), 201)["learner_id"]
        self.learner_two = self._ok(c.post(f"/pilot/campuses/{self.campus_two}/learners",
                                           json={"display_name": SHARED_DISPLAY_NAME},
                                           headers=ADMIN), 201)["learner_id"]
        for campus, teacher, learner in ((self.campus_one, one, self.learner_one),
                                         (self.campus_two, two, self.learner_two)):
            self._ok(c.post(f"/pilot/campuses/{campus}/educators/{teacher}", headers=ADMIN), 204)
            self._ok(c.post(f"/pilot/campuses/{campus}/educators/{teacher}/learners/{learner}",
                            headers=ADMIN), 204)
            if calendar:
                self._ok(c.put(f"/pilot/campuses/{campus}/calendar",
                               json={"preset": "valor_default", "first_data_day": FIRST_DATA_DAY.isoformat()},
                               headers=ADMIN), 200)
            if benchmark_auth:
                self._ok(c.post(f"/pilot/campuses/{campus}/benchmark-authorizations", json={
                    "instrument": "dibels8",
                    "licensed_program_ref": "Synthetic licensed program reference",
                    "approved_forms": [FORM],
                    "local_policy_ref": "Synthetic local assessment policy reference",
                    "attestation": "licensed program, approved forms and local policy permit benchmark administration",
                }, headers=ADMIN), 201)
        return self

    def authorize_campus(self, campus: str) -> None:
        """Through the real endpoint with the real current notice hash."""
        shown = self._ok(self.client.get(f"/pilot/campuses/{campus}/data-authorization",
                                         headers=ADMIN), 200)
        self.client.post(
            f"/pilot/campuses/{campus}/data-authorization",
            json={"notice_hash": shown["notice_hash"], "authorizer_name": "Synthetic Administrator",
                  "authorizer_role": "administrator"}, headers=ADMIN,
        )
        assert self._ok(self.client.get(f"/pilot/campuses/{campus}/data-authorization",
                                        headers=ADMIN), 200)["authorized"]

    @staticmethod
    def _ok(resp, status):
        assert resp.status_code == status, (resp.status_code, resp.text)
        return resp.json() if resp.content else None

    # ── helpers ────────────────────────────────────────────────────────────
    def base(self, campus: str | None = None, learner: str | None = None) -> str:
        return f"/pilot/campuses/{campus or self.campus_one}/learners/{learner or self.learner_one}"

    def administer(self, *, purpose="benchmark", cycle="valor_q1", measure="multiple",
                   window="BOY", form=FORM, when: datetime | None = None,
                   teacher: Teacher | None = None, campus=None, learner=None,
                   vendor_next: str | None = None, guidance: dict | None = None,
                   expect=201) -> dict:
        self._seq += 1
        body = {
            "instrument": "dibels8", "edition": "8th", "measure": measure, "grade": "1",
            "form_id": form, "administration_purpose": purpose, "instructional_cycle": cycle,
            "administered_at": (when or datetime(2031, 8, 20, 9, self._seq % 60,
                                                 tzinfo=timezone.utc)).isoformat(),
            "report_source": "vendor_report" if purpose == "benchmark" else "teacher_administered",
            "official_benchmark_window": window,
            "vendor_next_assessment_date": vendor_next,
            "accommodations": [], "notes": None, "vendor_guidance": guidance,
        }
        r = self.client.post(f"{self.base(campus, learner)}/assessments", json=body,
                             headers=(teacher or self.teacher_one).headers)
        assert r.status_code == expect, r.text
        return r.json()

    def step(self, aid, action, expected, *, resolution=None, teacher=None,
             campus=None, learner=None, expect=200):
        r = self.client.post(f"{self.base(campus, learner)}/assessments/{aid}/transitions",
                             json={"action": action, "expected_state": expected,
                                   "resolution": resolution},
                             headers=(teacher or self.teacher_one).headers)
        assert r.status_code == expect, r.text
        return r.json()

    def scores(self, aid, scores, responses=(), *, expect=200, teacher=None,
               campus=None, learner=None):
        r = self.client.put(f"{self.base(campus, learner)}/assessments/{aid}/scores",
                            json={"scores": list(scores), "responses": list(responses)},
                            headers=(teacher or self.teacher_one).headers)
        assert r.status_code == expect, r.text
        return r.json()

    def finalize_with(self, aid, scores, responses=()):
        self.step(aid, "mark_ready", "DRAFT")
        self.step(aid, "start", "READY_FOR_ADMINISTRATION")
        self.scores(aid, scores, responses)
        self.step(aid, "submit", "IN_PROGRESS")
        return self.step(aid, "finalize", "COMPLETED_PENDING_REVIEW")

    def evidence(self, aid, summary="Synthetic evidence summary"):
        r = self.client.post(f"{self.base()}/assessments/{aid}/evidence",
                             json={"summary": summary}, headers=self.teacher_one.headers)
        assert r.status_code == 201, r.text
        return r.json()

    def proposal(self, aid):
        r = self.client.post(f"{self.base()}/assessments/{aid}/proposal",
                             headers=self.teacher_one.headers)
        assert r.status_code == 200, r.text
        return r.json()

    def decide(self, aid, pid, body, *, expect=200, teacher=None, campus=None, learner=None):
        r = self.client.post(f"{self.base(campus, learner)}/assessments/{aid}/proposals/{pid}/decision",
                             json=body, headers=(teacher or self.teacher_one).headers)
        assert r.status_code == expect, r.text
        return r.json()

    def packet(self, cycle, *, teacher=None, campus=None, learner=None, expect=200):
        r = self.client.get(f"{self.base(campus, learner)}/data-day", params={"cycle": cycle},
                            headers=(teacher or self.teacher_one).headers)
        assert r.status_code == expect, r.text
        return r.json()


# ── Score builders ──────────────────────────────────────────────────────────

def scored(measure, raw, unit="correct_per_minute", **labels):
    return {"measure": measure, "administration_status": "scored", "raw_score": raw,
            "score_unit": unit, **labels}


def skipped(measure, status="not_administered_by_rule",
            reason="Not administered at this grade and window per the report"):
    return {"measure": measure, "administration_status": status, "reason": reason}


def boy_vendor_report() -> list[dict]:
    """A BOY vendor-report SHAPE: two not-administered measures, printed cut points,
    and a composite printed with both label vocabularies. All values invented."""
    return [
        scored("LNF", 31, benchmark_label="At Benchmark", support_label="Goal",
               printed_cut_points=[{"label": "printed cut A", "value": 17},
                                   {"label": "printed cut B", "value": 29}]),
        scored("PSF", 12, benchmark_label="Below Benchmark", support_label="Some Support",
               printed_cut_points=[{"label": "printed cut A", "value": 9},
                                   {"label": "printed cut B", "value": 21}]),
        skipped("ORF_WC"),
        skipped("MAZE", status="not_administered_other",
                reason="Report prints this measure as not administered"),
        scored("COMPOSITE", 240, unit="points", benchmark_label="Below Benchmark",
               support_label="Some Support",
               printed_cut_points=[{"label": "printed composite cut", "value": 222}]),
    ]


def responses_with_errors() -> list[dict]:
    return [
        {"measure": "PSF", "item_index": 0, "mark": "segment", "correct": True},
        {"measure": "PSF", "item_index": 1, "mark": "segment", "correct": False,
         "error_type": "onset_rime_only"},
        {"measure": "PSF", "item_index": 2, "mark": "segment", "correct": False,
         "error_type": "onset_rime_only", "annotation": "Synthetic teacher annotation"},
    ]
