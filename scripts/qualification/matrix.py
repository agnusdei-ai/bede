"""The qualification matrix: one declarative table, one runner.

``TABLE`` lists every protected record type and the routes that serve it.
The runner exercises each row against every rule that applies to it, over
real HTTP (and the real browser, and real SSE) against the running server.

Cell statuses — every one except PASS fails the run:

  PASS        the rule held, observed over the wire
  FAIL        the rule was violated, or the route misbehaved
  ABSENT      the route the rule needs is not in the candidate's route table
  BLOCKED     a precondition outside the rule failed (e.g. no teacher session
              could be obtained), so the rule could not be observed
  UNVERIFIED  the route exists but the rule cannot be observed over HTTP by
              this harness (stated reason); never silently passed

A missing route is never skipped. Other lanes are still building several of
these routes; until they land, those rows are ABSENT, which is the honest
state of the candidate.

Route templates are overridable without a code change:
QUAL_ROUTE_OVERRIDES='{"assessment.read": ["GET", "/pilot/me/learners/{learner_id}/x"]}'
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualconfig as cfg  # noqa: E402
from harness import Api, Driver, Stack, route_present  # noqa: E402
from seed import Fixture, Seeder  # noqa: E402

L = "/pilot/me/learners/{learner_id}"
# The canonical assessment routes (#607, routers/pilot_assessments.py) are
# campus-scoped. path() fills {campus_id} with the LEARNER's own campus, so a
# teacher copying another learner's id copies that learner's whole path.
C = "/pilot/campuses/{campus_id}/learners/{learner_id}"
SYNTH_PM_FORM = "SYN-PM-FORM-1"
SYNTH_FIRST_DATA_DAY = "2031-08-25"  # fabricated, far from any real school year


def canon_administration(measure: str = "PSF", purpose: str = "progress_monitoring",
                         window: str = "none", cycle: str = "valor_q1",
                         minute: int = 0) -> dict:
    """A synthetic canonical administration body (teacher-administered
    progress monitoring: needs no licensed-benchmark authorization). Every
    value is invented."""
    return {
        "instrument": "dibels8", "edition": "8th", "measure": measure, "grade": "1",
        "form_id": SYNTH_PM_FORM, "administration_purpose": purpose,
        "instructional_cycle": cycle,
        "administered_at": f"2031-09-02T09:{minute % 60:02d}:00+00:00",
        "report_source": "teacher_administered", "official_benchmark_window": window,
        "vendor_next_assessment_date": None, "accommodations": [], "notes": None,
        "vendor_guidance": None,
    }


def _scored(measure: str, raw: float) -> dict:
    return {"measure": measure, "administration_status": "scored", "raw_score": raw,
            "score_unit": "correct_per_minute"}


def _skipped(measure: str) -> dict:
    return {"measure": measure, "administration_status": "not_administered_by_rule",
            "reason": "Synthetic: not administered at this grade per the report"}

SYNTH_DIBELS = {
    "framework": "dibels8", "measure": "ORF_WC", "assessed_on": "2026-01-15",
    "source_name": "Synthetic qualification report", "score": 12,
    "score_unit": "correct_per_minute", "reported_band": "intensive_at_risk",
    "assessed_grade": "2", "assessment_window": "middle_of_year",
}

# ── THE TABLE ────────────────────────────────────────────────────────────────
# group: G1 (identity/isolation), DIBELS (canonical assessment + Data Day),
#        G2 (teacher decision workflow), DELETION (learner deletion lifecycle)
# read/write/list: (METHOD, template[, body]) — None means the brief asks
# nothing of that operation for this record type.
TABLE: list[dict] = [
    {"id": "learner_profile", "group": "G1", "read": ("GET", L)},
    {"id": "learner_list", "group": "G1", "list": ("GET", "/pilot/me/learners")},
    {"id": "learner_search", "group": "G1",
     "list": ("POST", "/pilot/me/learners/search", {"query": cfg.SHARED_LEARNER_DISPLAY_NAME})},
    {"id": "assessment", "group": "G1",
     "read": ("GET", C + "/assessments"),
     "write": ("POST", C + "/assessments", canon_administration(minute=1))},
    {"id": "tutoring_history", "group": "G1", "read": ("GET", L + "/tutoring/history")},
    {"id": "tutoring_turn", "group": "G1",
     "write": ("POST", L + "/tutoring/chat", {"child_message": "[START]"}), "sse": True},
    {"id": "cache_derived_summary", "group": "G1", "read": ("GET", L + "/diagnostic")},
    {"id": "voice_session", "group": "G1", "special": "voice"},
    {"id": "dibels_administration", "group": "DIBELS",
     "read": ("GET", C + "/assessments"),
     "write": ("POST", C + "/assessments", canon_administration(minute=2)),
     "semantics": ["progress_monitoring_not_benchmark", "skipped_measure_not_zero",
                   "interrupted_not_finalized", "interpretation_never_overwrites_score"]},
    {"id": "data_day_packet", "group": "DIBELS", "read": ("GET", C + "/data-day?cycle=valor_q1"),
     "semantics": ["packet_changes_no_official_score", "packet_starts_no_instruction",
                   "packet_shows_skipped_and_invalid_states"]},
    {"id": "evidence", "group": "G2",
     "read": ("GET", L + "/evidence"), "write": ("POST", L + "/evidence", SYNTH_DIBELS)},
    {"id": "recommendation", "group": "G2",
     "read": ("GET", L + "/recommendations"), "write": ("POST", L + "/recommendations", None)},
    {"id": "decision", "group": "G2", "read": ("GET", L + "/decisions"),
     "write": ("POST", L + "/recommendations/{recommendation_id}/decision", None),
     "special": "g2"},
    {"id": "authorized_instruction", "group": "G2", "read": ("GET", L + "/instruction")},
    {"id": "learner_deletion", "group": "DELETION",
     "delete": ("POST", "/pilot/owner/campuses/{campus_id}/learners/{learner_id}/delete"),
     "special": "deletion"},
]

UNIFORM_PROBES = {
    "random_uuid": lambda: str(uuid.uuid4()),
    "malformed_id": lambda: "not-a-uuid",
    "noncanonical_uuid": lambda: str(uuid.uuid4()).upper(),
    "nil_uuid": lambda: "00000000-0000-0000-0000-000000000000",
}
# The audit event the ADMIN REVOKE ACTION itself writes. Deliberately not a
# loose substring like "revoke": #606's authz.revoked_in_flight also contains
# it, and that event only appears when a stream happened to be open, so a
# loose marker would pass this cell for the wrong reason.
REVOCATION_AUDIT_MARKERS = [m.lower() for m in cfg._csv(
    "REVOCATION_AUDIT_MARKERS", "pilot.roster_grant_revoked")]
DELIVERY_WORDS = ("delivered", "sent to learner", "started lesson")


def _apply_overrides() -> None:
    raw = os.environ.get("QUAL_ROUTE_OVERRIDES", "").strip()
    if not raw:
        return
    for key, value in json.loads(raw).items():
        row_id, op = key.split(".", 1)
        for row in TABLE:
            if row["id"] == row_id:
                row[op] = tuple(value)


@dataclass
class Cell:
    row: str
    group: str
    cell: str
    status: str
    detail: str = ""
    evidence: dict = field(default_factory=dict)


class Matrix:
    def __init__(self, api: Api, driver: Driver, stack: Stack, seeder: Seeder,
                 routes: set) -> None:
        self.api, self.driver, self.stack, self.seeder = api, driver, stack, seeder
        self.fx: Fixture = seeder.fx
        self.routes = routes
        self.cells: list[Cell] = []
        self.recs: dict = {}

    # ── recording ────────────────────────────────────────────────────────────
    def put(self, row: dict | str, cell: str, outcome: str, detail: str = "", **ev) -> None:
        rid = row if isinstance(row, str) else row["id"]
        group = next((r["group"] for r in TABLE if r["id"] == rid), "G1") if isinstance(row, str) else row["group"]
        self.cells.append(Cell(rid, group, cell, outcome, detail[:400], ev))

    def present(self, spec) -> bool:
        # A query string is part of the call, never of the route template.
        return bool(spec) and route_present(self.routes, spec[0], spec[1].split("?", 1)[0])

    def path(self, template: str, **ids) -> str:
        """Fill a template. ``{campus_id}`` defaults to the campus of the
        learner being addressed (learner_two -> campus_two), so a teacher
        aiming at another campus's learner uses that learner's real path; an
        unknown id (a probe) keeps campus_one's path."""
        learner = ids.get("learner_id", self.fx.learner.get("learner_one", ""))
        own_campus = {self.fx.learner.get(k): self.fx.campus.get(k.replace("learner", "campus"))
                      for k in ("learner_one", "learner_two")}
        values = {"learner_id": learner,
                  "campus_id": own_campus.get(learner) or self.fx.campus.get("campus_one", ""),
                  **ids}
        return template.format(**values)

    def tok(self, teacher: str) -> str | None:
        return self.fx.teacher_token.get(teacher)

    def call(self, teacher: str | None, method: str, path: str, body=None) -> httpx.Response:
        token = self.tok(teacher) if teacher and teacher != "admin" else (
            self.fx.admin_token if teacher == "admin" else None)
        return self.api.call(method, path, token, body)

    def teachers_ready(self) -> bool:
        return all(self.tok(k) for k in cfg.TEACHER_USERNAMES)

    def blocked(self, row, cells: list[str]) -> None:
        for c in cells:
            self.put(row, c, "BLOCKED", self.fx.teacher_blocker or "no teacher session")

    # ── generic per-row rules ────────────────────────────────────────────────
    GENERIC = ["own_access", "cross_campus_read", "cross_campus_write", "random_uuid",
               "malformed_id", "noncanonical_uuid", "nil_uuid", "same_name_isolation"]

    def run_generic(self, row: dict, *, defer_own_write: bool = False) -> None:
        read, write, lst = row.get("read"), row.get("write"), row.get("list")
        specs = [s for s in (read, write, lst) if s]
        if not specs:
            return
        absent = [s for s in specs if not self.present(s)]
        if absent:
            for c in self.GENERIC:
                self.put(row, c, "ABSENT", "route not in candidate route table: "
                         + ", ".join(f"{s[0]} {s[1]}" for s in absent))
            for c in row.get("semantics", []):
                self.put(row, c, "ABSENT", "semantic check needs the route above")
            return
        if not self.teachers_ready():
            self.blocked(row, self.GENERIC + row.get("semantics", []))
            return
        l1, l2 = self.fx.learner["learner_one"], self.fx.learner["learner_two"]

        if lst:
            r1 = self.call("teacher_one", lst[0], lst[1], lst[2] if len(lst) > 2 else None)
            r2 = self.call("teacher_two", lst[0], lst[1], lst[2] if len(lst) > 2 else None)
            ok = r1.status_code == 200 and l1 in r1.text and l2 not in r1.text
            self.put(row, "own_access", "PASS" if ok else "FAIL",
                     f"teacher_one list -> {r1.status_code}", status=r1.status_code)
            iso = (r2.status_code == 200 and l2 in r2.text and l1 not in r2.text
                   and l2 not in r1.text)
            self.put(row, "same_name_isolation", "PASS" if iso else "FAIL",
                     "each teacher's list holds only their own same-named learner",
                     statuses=[r1.status_code, r2.status_code])
            for c in ("cross_campus_read", "cross_campus_write", "random_uuid", "malformed_id",
                      "noncanonical_uuid", "nil_uuid"):
                self.put(row, c, "PASS" if ok and iso else "FAIL",
                         "list route takes no learner id; covered by isolation of its result")
            return

        if write and not defer_own_write:
            body = write[2] if len(write) > 2 else None
            if "{recommendation_id}" not in write[1]:
                r = self.call("teacher_one", write[0], self.path(write[1], learner_id=l1), body)
                self.put(row, "own_write", "PASS" if r.status_code in (200, 201) else "FAIL",
                         f"teacher_one write own learner -> {r.status_code}", status=r.status_code)
        own = self.call("teacher_one", read[0], self.path(read[1], learner_id=l1)) if read else None
        if own is not None:
            self.put(row, "own_access", "PASS" if own.status_code == 200 else "FAIL",
                     f"teacher_one -> own learner {own.status_code}", status=own.status_code)
        target = read or write
        ref = self.call("teacher_two", target[0], self.path(target[1], learner_id=str(uuid.uuid4())),
                        target[2] if len(target) > 2 else None)
        cross = self.call("teacher_two", target[0], self.path(target[1], learner_id=l1),
                          target[2] if len(target) > 2 else None)
        same = (cross.status_code == ref.status_code == 404 and cross.text == ref.text)
        self.put(row, "cross_campus_read", "PASS" if same else "FAIL",
                 f"teacher_two -> learner_one {cross.status_code}; identical to absent-id response: "
                 f"{cross.text == ref.text}", statuses=[cross.status_code, ref.status_code])
        if write and "{recommendation_id}" not in write[1]:
            before = self.call("teacher_one", read[0], self.path(read[1], learner_id=l1)).text if read else ""
            w = self.call("teacher_two", write[0], self.path(write[1], learner_id=l1),
                          write[2] if len(write) > 2 else None)
            after = self.call("teacher_one", read[0], self.path(read[1], learner_id=l1)).text if read else ""
            okw = w.status_code == 404 and w.text == ref.text and before == after
            self.put(row, "cross_campus_write", "PASS" if okw else "FAIL",
                     f"teacher_two write learner_one -> {w.status_code}; learner_one unchanged: {before == after}",
                     status=w.status_code)
        else:
            self.put(row, "cross_campus_write", "PASS" if same else "FAIL",
                     "no learner-scoped write on this record type; read denial covers it")
        for name, make in UNIFORM_PROBES.items():
            r = self.call("teacher_two", target[0], self.path(target[1], learner_id=make()),
                          target[2] if len(target) > 2 else None)
            uni = r.status_code == ref.status_code and r.text == ref.text
            self.put(row, name, "PASS" if uni else "FAIL",
                     f"{r.status_code} identical-to-absent={r.text == ref.text}", status=r.status_code)
        if read:
            mine = self.call("teacher_two", read[0], self.path(read[1], learner_id=l2))
            iso = mine.status_code == 200 and l1 not in mine.text and (own is None or l2 not in own.text)
            self.put(row, "same_name_isolation", "PASS" if iso else "FAIL",
                     "same display name; neither teacher's response carries the other learner's id",
                     statuses=[own.status_code if own is not None else None, mine.status_code])
        for c in row.get("semantics", []):
            probe = getattr(self, f"_sem_{c}", None)
            if probe is None:
                self.put(row, c, "UNVERIFIED", "no semantic probe bound for this rule")
                continue
            try:
                ok, detail = probe()
            except Exception as exc:  # noqa: BLE001 - a probe crash is a FAIL, never a skip
                ok, detail = False, f"probe raised {type(exc).__name__}: {exc}"
            self.put(row, c, "PASS" if ok else "FAIL", detail)

    # ── DIBELS / Data Day semantic probes (canonical routes, #607) ──────────
    # Each probe is self-contained on teacher_one / learner_one / campus_one
    # and returns (held, detail). They exercise only teacher-recorded actions:
    # nothing here advances on a timer, schedules or delivers instruction.
    def _c(self, method: str, suffix: str, body=None, teacher: str = "teacher_one") -> httpx.Response:
        l1 = self.fx.learner["learner_one"]
        return self.call(teacher, method, self.path(C + suffix, learner_id=l1), body)

    def _administer(self, **kw) -> str:
        self._seq = getattr(self, "_seq", 10) + 1
        r = self._c("POST", "/assessments", canon_administration(minute=self._seq, **kw))
        if r.status_code != 201:
            raise RuntimeError(f"create administration -> {r.status_code} {r.text[:200]}")
        return r.json()["assessment_id"]

    def _step(self, aid: str, action: str, expected: str, resolution: str | None = None) -> int:
        return self._c("POST", f"/assessments/{aid}/transitions",
                       {"action": action, "expected_state": expected, "resolution": resolution}).status_code

    def _scores(self, aid: str, scores: list) -> int:
        return self._c("PUT", f"/assessments/{aid}/scores", {"scores": scores, "responses": []}).status_code

    def _finalize(self, aid: str, scores: list) -> list[int]:
        return [self._step(aid, "mark_ready", "DRAFT"),
                self._step(aid, "start", "READY_FOR_ADMINISTRATION"),
                self._scores(aid, scores),
                self._step(aid, "submit", "IN_PROGRESS"),
                self._step(aid, "finalize", "COMPLETED_PENDING_REVIEW")]

    def _detail(self, aid: str) -> dict:
        return self._c("GET", f"/assessments/{aid}").json()

    def _packet(self, cycle: str = "valor_q1") -> httpx.Response:
        return self._c("GET", f"/data-day?cycle={cycle}")

    def _sem_progress_monitoring_not_benchmark(self):
        bad = self._c("POST", "/assessments",
                      canon_administration(window="MOY", cycle="valor_q2", minute=50))
        aid = self._administer(cycle="valor_q2")
        steps = self._finalize(aid, [_scored("PSF", 20)])
        pk = self._packet("valor_q2").json()
        growth = pk.get("growth_by_measure", {})
        pm_ids = [p["assessment_id"] for p in growth.get("progress_monitoring", {}).get("PSF", {}).get("points", [])]
        bm_ids = [p["assessment_id"] for p in growth.get("benchmark", {}).get("PSF", {}).get("points", [])]
        shown = {a["assessment_id"]: a for a in pk.get("current_valid_results", [])}
        rec = shown.get(aid, {})
        ok = (bad.status_code == 422 and steps == [200] * 5 and aid in pm_ids and aid not in bm_ids
              and rec.get("administration_purpose") == "progress_monitoring"
              and rec.get("official_benchmark_window") == "none")
        return ok, (f"PM carrying an official window -> {bad.status_code}; finalized PM in "
                    f"progress_monitoring series: {aid in pm_ids}; in benchmark series: {aid in bm_ids}")

    def _sem_skipped_measure_not_zero(self):
        aid = self._administer(measure="multiple", cycle="valor_q3")
        pre = [self._step(aid, "mark_ready", "DRAFT"), self._step(aid, "start", "READY_FOR_ADMINISTRATION")]
        zero = self._scores(aid, [{**_skipped("ORF_WC"), "raw_score": 0, "score_unit": "correct_per_minute"}])
        good = self._scores(aid, [_scored("PSF", 10), _skipped("ORF_WC")])
        fin = [self._step(aid, "submit", "IN_PROGRESS"), self._step(aid, "finalize", "COMPLETED_PENDING_REVIEW")]
        by = {s["measure"]: s for s in self._detail(aid).get("scores", [])}
        orf = by.get("ORF_WC", {})
        pk = self._packet("valor_q3").json()
        skipped = {s["measure"] for s in pk.get("skipped_or_invalid_measures", [])}
        in_growth = any("ORF_WC" in series for series in pk.get("growth_by_measure", {}).values())
        ok = (pre == [200, 200] and zero == 422 and good == 200 and fin == [200, 200]
              and orf.get("raw_score") is None
              and orf.get("administration_status") == "not_administered_by_rule"
              and "ORF_WC" in skipped and not in_growth)
        return ok, (f"skipped measure with raw_score 0 -> {zero}; stored raw_score="
                    f"{orf.get('raw_score')!r}; listed as skipped: {'ORF_WC' in skipped}; in growth: {in_growth}")

    def _sem_interrupted_not_finalized(self):
        aid = self._administer(cycle="valor_q4")
        codes = [self._step(aid, "mark_ready", "DRAFT"),
                 self._step(aid, "start", "READY_FOR_ADMINISTRATION"),
                 self._scores(aid, [_scored("PSF", 10)]),
                 self._step(aid, "interrupt", "IN_PROGRESS")]
        fin = self._step(aid, "finalize", "INTERRUPTED")
        sub = self._step(aid, "submit", "INTERRUPTED")
        resume_no_reason = self._step(aid, "resume", "INTERRUPTED")
        state = self._detail(aid).get("state")
        ok = codes == [200] * 4 and fin == 409 and sub == 409 and resume_no_reason == 409 \
            and state == "INTERRUPTED"
        return ok, (f"finalize from INTERRUPTED -> {fin}; submit -> {sub}; resume without a written "
                    f"resolution -> {resume_no_reason}; state still {state}")

    def _sem_interpretation_never_overwrites_score(self):
        aid = self._administer(cycle="valor_q1")
        steps = self._finalize(aid, [_scored("PSF", 17)])
        before = self._detail(aid)
        ev = self._c("POST", f"/assessments/{aid}/evidence", {"summary": "Synthetic evidence summary"})
        pr = self._c("POST", f"/assessments/{aid}/proposal")
        dec = None
        if pr.status_code == 200:
            dec = self._c("POST", f"/assessments/{aid}/proposals/{pr.json()['proposal_id']}/decision",
                          {"action": "edit", "expected_version": 1, "edited_text": "Synthetic edited step",
                           "rationale": "Synthetic teacher reading"}).status_code
        rescore = self._scores(aid, [_scored("PSF", 99)])
        after = self._detail(aid)
        ok = (steps == [200] * 5 and ev.status_code == 201 and pr.status_code == 200 and dec == 200
              and rescore == 409 and after.get("scores") == before.get("scores")
              and after.get("snapshot_sha256") == before.get("snapshot_sha256")
              and after.get("snapshot_verified") is True)
        return ok, (f"evidence {ev.status_code}, proposal {pr.status_code}, teacher edit {dec}; "
                    f"re-score after finalization -> {rescore}; scores unchanged: "
                    f"{after.get('scores') == before.get('scores')}")

    def _sem_packet_changes_no_official_score(self):
        aid = self._administer(cycle="valor_q1")
        self._finalize(aid, [_scored("PSF", 21)])
        before = self._detail(aid)
        pk = self._packet("valor_q1")
        after = self._detail(aid)
        boundaries = pk.json().get("boundaries", {}) if pk.status_code == 200 else {}
        ok = (pk.status_code == 200 and after.get("scores") == before.get("scores")
              and after.get("snapshot_sha256") == before.get("snapshot_sha256")
              and boundaries.get("changes_official_scores") is False
              and boundaries.get("alters_placement") is False)
        return ok, f"packet {pk.status_code}; scores unchanged by reading it; boundaries={boundaries}"

    def _sem_packet_starts_no_instruction(self):
        pk = self._packet("valor_q1")
        data = pk.json() if pk.status_code == 200 else {}
        b = data.get("boundaries", {})
        outcomes = [d.get("outcome", {}) for d in data.get("prior_teacher_decisions", [])]
        low = pk.text.lower()
        ok = (pk.status_code == 200 and b.get("starts_instruction") is False
              and b.get("delivers_instruction") is False
              and all(o.get("delivery_state") == "NOT_REQUESTED" for o in outcomes)
              and not any(w in low for w in DELIVERY_WORDS))
        return ok, (f"packet {pk.status_code}; starts_instruction={b.get('starts_instruction')} "
                    f"delivers_instruction={b.get('delivers_instruction')}; "
                    f"{len(outcomes)} prior decision(s), all NOT_REQUESTED")

    def _sem_packet_shows_skipped_and_invalid_states(self):
        valid_skip = self._administer(measure="multiple", cycle="valor_q2")
        vcodes = self._finalize(valid_skip, [_scored("PSF", 12), _skipped("MAZE")])
        aid = self._administer(measure="multiple", cycle="valor_q2")
        codes = vcodes + [self._step(aid, "mark_ready", "DRAFT"),
                 self._step(aid, "start", "READY_FOR_ADMINISTRATION"),
                 self._scores(aid, [_scored("PSF", 10), _skipped("MAZE")]),
                 self._step(aid, "invalidate", "IN_PROGRESS", resolution="Synthetic: wrong form used"),
                 self._step(aid, "resolve_invalid", "INVALID_ADMINISTRATION",
                            resolution="Synthetic: recorded for the file only"),
                 self._step(aid, "finalize", "COMPLETED_PENDING_REVIEW")]
        pk = self._packet("valor_q2").json()
        not_valid = {a["assessment_id"] for a in pk.get("not_valid_administrations", [])}
        valid = {a["assessment_id"] for a in pk.get("current_valid_results", [])}
        skipped = {s["measure"] for s in pk.get("skipped_or_invalid_measures", [])}
        ok = codes == [200] * 11 and aid in not_valid and aid not in valid and "MAZE" in skipped
        return ok, (f"lifecycle codes {codes}; invalid administration listed as not valid: "
                    f"{aid in not_valid}; excluded from valid results: {aid not in valid}; "
                    f"skipped measures shown: {sorted(skipped)}")

    # ── browser vs API ───────────────────────────────────────────────────────
    def browser_agreement(self) -> None:
        row = "learner_profile"
        if not self.teachers_ready():
            self.blocked(row, ["browser_api_agree"])
            return
        path = self.path(L)
        r = self.call("teacher_one", "GET", path)
        b_status, b_text = self.driver.fetch("teacher_one", "GET", path, self.tok("teacher_one"))
        r2 = self.call("teacher_two", "GET", path)
        b2_status, b2_text = self.driver.fetch("teacher_two", "GET", path, self.tok("teacher_two"))
        ok = (r.status_code == b_status and json.loads(r.text) == json.loads(b_text)
              and r2.status_code == b2_status and r2.text == b2_text)
        self.put(row, "browser_api_agree", "PASS" if ok else "FAIL",
                 f"api {r.status_code}/{r2.status_code} browser {b_status}/{b2_status}")

    # ── voice ────────────────────────────────────────────────────────────────
    def voice_owner_binding(self) -> None:
        row = "voice_session"
        cells = ["own_voice_start", "cross_teacher_voice_subscribe", "cross_teacher_voice_write",
                 "cross_campus_voice_start_denied"]
        if not self.present(("POST", "/voice/stream/start")):
            for c in cells:
                self.put(row, c, "ABSENT", "/voice/stream/start not mounted")
            return
        if not self.teachers_ready():
            self.blocked(row, cells)
            return
        sid_sub, sid_write = self._voice_start("teacher_one"), self._voice_start("teacher_one")
        if not (sid_sub and sid_write):
            self.put(row, "own_voice_start", "FAIL", "teacher_one could not start a voice session")
            for c in cells[1:]:
                self.put(row, c, "BLOCKED", "no voice session to attack")
            return
        self.put(row, "own_voice_start", "PASS", "teacher_one started voice sessions for learner_one")
        # Teacher Two attaches FIRST (no reader yet), so an accepted attach stays open.
        sub = self._sse_open("teacher_two", f"/voice/stream/{sid_sub}/events", seconds=4.0)
        self.put(row, "cross_teacher_voice_subscribe", "PASS" if _sse_denied(sub) else "FAIL",
                 f"teacher_two -> teacher_one's voice events: {_sse_desc(sub)}")
        fin = self.call("teacher_two", "POST", f"/voice/stream/{sid_write}/finish")
        self.put(row, "cross_teacher_voice_write", "PASS" if fin.status_code == 404 else "FAIL",
                 f"teacher_two finished teacher_one's voice session -> {fin.status_code} "
                 "(must be the same 404 as an unknown session)", status=fin.status_code)
        x = self.call("teacher_two", "POST", "/voice/stream/start",
                      {"language": "en", "learner_id": self.fx.learner["learner_one"]})
        self.put(row, "cross_campus_voice_start_denied", "PASS" if x.status_code in (403, 404) else "FAIL",
                 f"teacher_two started a voice session naming learner_one -> {x.status_code}")

    def _voice_start(self, teacher: str, learner: str = "learner_one") -> str | None:
        r = self.call(teacher, "POST", "/voice/stream/start",
                      {"language": "en", "learner_id": self.fx.learner[learner]})
        return r.json().get("session_id") if r.status_code == 200 else None

    def _sse_open(self, teacher: str, path: str, seconds: float,
                  until: threading.Event | None = None, token: str | None = None) -> dict:
        """Read an SSE stream in a background thread for up to ``seconds``
        (or until ``until`` is set, plus SSE_IDLE_WAIT_S). Records data
        events with timestamps, keep-alive pings, whether the SERVER ended
        the stream, and any transport error — kept distinct, because a
        client-side error must never read as the server closing the stream."""
        out = {"status": None, "data_events": 0, "pings": 0, "ended": False, "error": None,
               "text": "", "event_times": [], "end_time": None}
        headers = {"Authorization": f"Bearer {token or self.tok(teacher)}", "User-Agent": self.api.ua}
        client = httpx.Client(base_url=self.api.base, timeout=httpx.Timeout(10, read=120), verify=self.api.verify)
        closing = threading.Event()

        def reader() -> None:
            try:
                with client.stream("GET", path, headers=headers) as r:
                    out["status"] = r.status_code
                    if r.status_code != 200:
                        out["text"] = r.read().decode(errors="replace")[:300]
                        out["ended"], out["end_time"] = True, time.time()
                        return
                    for line in r.iter_lines():
                        if line.startswith("data:"):
                            out["data_events"] += 1
                            out["event_times"].append(time.time())
                            out.setdefault("event_payloads", []).append(line[5:].strip()[:200])
                            out["text"] += line[5:].strip()[:200] + " "
                        elif line.startswith(":"):
                            out["pings"] += 1
                    out["ended"], out["end_time"] = True, time.time()
            except Exception as exc:  # noqa: BLE001
                if not closing.is_set():
                    out["error"] = type(exc).__name__

        th = threading.Thread(target=reader, daemon=True)
        th.start()
        deadline = time.time() + seconds
        while time.time() < deadline and th.is_alive():
            if until is not None and until.is_set():
                deadline = min(deadline, until.revoked_at + cfg.SSE_IDLE_WAIT_S)  # type: ignore[attr-defined]
            time.sleep(0.1)
        closing.set()
        client.close()
        th.join(timeout=5)
        return out

    # ── G2 ───────────────────────────────────────────────────────────────────
    G2_CELLS = ["evidence_linked_to_recommendation", "recommendation_is_not_approval",
                "approve_recorded", "edit_recorded", "reject_recorded", "replay_rejected",
                "true_concurrency_one_winner", "cross_campus_decision_denied",
                "substituted_recommendation_id_denied", "ledger_chain_valid",
                "instruction_recorded_not_delivered", "failed_audit_write_atomic"]

    def g2(self) -> None:
        row = "decision"
        needed = [("POST", L + "/evidence"), ("POST", L + "/recommendations"),
                  ("POST", L + "/recommendations/{recommendation_id}/decision"),
                  ("GET", L + "/decisions"), ("GET", L + "/instruction")]
        missing = [s for s in needed if not self.present(s)]
        if missing:
            for c in self.G2_CELLS + ["restart_preserves_decision_and_chain",
                                      "revocation_before_decision_denied"]:
                self.put(row, c, "ABSENT", "missing: " + ", ".join(f"{m} {p}" for m, p in missing))
            return
        if not self.teachers_ready():
            self.blocked(row, self.G2_CELLS)
            return
        l1, l2 = self.fx.learner["learner_one"], self.fx.learner["learner_two"]
        p = lambda t, **k: self.path(t, learner_id=l1, **k)  # noqa: E731
        ev = self.call("teacher_one", "POST", p(L + "/evidence"), SYNTH_DIBELS)
        rec = self.call("teacher_one", "POST", p(L + "/recommendations"))
        data = rec.json() if rec.status_code == 200 else {}
        # The generic recommendation row verifies *read* and negative write
        # isolation without issuing an extra authorized write. This sole G2
        # creation is the real positive write, so no pending recommendation
        # is left behind to prevent teacher review or tutoring.
        self.put("recommendation", "own_write",
                 "PASS" if rec.status_code == 200 and not data.get("abstained", True) else "FAIL",
                 f"teacher_one authorized recommendation -> {rec.status_code}",
                 status=rec.status_code)
        linked = (ev.status_code == 201 and not data.get("abstained", True)
                  and ev.json().get("evidence_id") in data.get("source_evidence_ids", []))
        self.put(row, "evidence_linked_to_recommendation", "PASS" if linked else "FAIL",
                 f"evidence {ev.status_code}, recommendation {rec.status_code}")
        not_approval = data.get("status") == "pending" and data.get("authorized_instruction") is None
        self.put(row, "recommendation_is_not_approval", "PASS" if not_approval else "FAIL",
                 f"status={data.get('status')}")
        if not data.get("recommendation_id"):
            for c in self.G2_CELLS[2:]:
                self.put(row, c, "BLOCKED", "no recommendation to decide")
            return
        rid, ver = data["recommendation_id"], data["version"]
        dpath = p(L + "/recommendations/{recommendation_id}/decision", recommendation_id=rid)
        # cross-campus and substituted-id attempts BEFORE the real decision
        x = self.call("teacher_two", "POST", dpath, {"action": "approve", "expected_version": ver})
        self.put(row, "cross_campus_decision_denied", "PASS" if x.status_code == 404 else "FAIL",
                 f"teacher_two decided learner_one's recommendation -> {x.status_code}")
        sub = self.call("teacher_two", "POST",
                        self.path(L + "/recommendations/{recommendation_id}/decision",
                                  learner_id=l2, recommendation_id=rid),
                        {"action": "approve", "expected_version": ver})
        self.put(row, "substituted_recommendation_id_denied", "PASS" if sub.status_code == 404 else "FAIL",
                 f"teacher_two used learner_one's recommendation id on own learner -> {sub.status_code}")
        a = self.call("teacher_one", "POST", dpath, {"action": "approve", "expected_version": ver})
        self.put(row, "approve_recorded", "PASS" if a.status_code == 200 else "FAIL", f"-> {a.status_code}")
        again = self.call("teacher_one", "POST", dpath, {"action": "approve", "expected_version": ver})
        self.put(row, "replay_rejected", "PASS" if again.status_code == 409 else "FAIL",
                 f"replay -> {again.status_code}")
        self.recs["approved"] = rid
        # edit and reject on fresh recommendations
        for action, cell in (("edit", "edit_recorded"), ("reject", "reject_recorded")):
            nr = self.call("teacher_one", "POST", p(L + "/recommendations"))
            if nr.status_code != 200 or nr.json().get("abstained"):
                self.put(row, cell, "FAIL", f"could not obtain a recommendation ({nr.status_code})")
                continue
            body = {"action": action, "expected_version": nr.json()["version"]}
            if action == "edit":
                body["edited_text"] = "Synthetic edited instruction."
            d = self.call("teacher_one", "POST",
                          p(L + "/recommendations/{recommendation_id}/decision",
                            recommendation_id=nr.json()["recommendation_id"]), body)
            self.put(row, cell, "PASS" if d.status_code == 200 else "FAIL", f"-> {d.status_code}")
        # true concurrency: two clients, two pool connections, one recommendation
        nr = self.call("teacher_one", "POST", p(L + "/recommendations"))
        if nr.status_code == 200 and not nr.json().get("abstained"):
            cpath = p(L + "/recommendations/{recommendation_id}/decision",
                      recommendation_id=nr.json()["recommendation_id"])
            body = {"action": "approve", "expected_version": nr.json()["version"]}
            results: list[int] = []
            barrier = threading.Barrier(2)

            def fire():
                with httpx.Client(base_url=self.api.base, timeout=cfg.REQUEST_TIMEOUT_S, verify=self.api.verify,
                                  headers={"User-Agent": self.api.ua}) as c:
                    barrier.wait()
                    results.append(c.post(cpath, json=body, headers={
                        "Authorization": f"Bearer {self.tok('teacher_one')}"}).status_code)
            threads = [threading.Thread(target=fire) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            ok = sorted(results) == [200, 409]
            self.put(row, "true_concurrency_one_winner", "PASS" if ok else "FAIL", f"statuses={sorted(results)}")
        else:
            self.put(row, "true_concurrency_one_winner", "FAIL", f"no recommendation ({nr.status_code})")
        led = self.call("teacher_one", "GET", p(L + "/decisions"))
        self.put(row, "ledger_chain_valid", "PASS" if led.status_code == 200 and led.json().get("chain_valid") else "FAIL",
                 f"-> {led.status_code} chain_valid={led.json().get('chain_valid') if led.status_code == 200 else None}")
        ins = self.call("teacher_one", "GET", p(L + "/instruction"))
        low = ins.text.lower()
        rec_ok = ins.status_code == 200 and not any(w in low for w in DELIVERY_WORDS)
        self.put(row, "instruction_recorded_not_delivered", "PASS" if rec_ok else "FAIL",
                 f"-> {ins.status_code}; no delivery claim in payload: {rec_ok}")
        self.put(row, "failed_audit_write_atomic", "UNVERIFIED",
                 "a failed audit write cannot be induced over HTTP without fault injection into the "
                 "server; the in-process atomicity test lives with #604")

    def g2_after_restart(self) -> None:
        row = "decision"
        if not self.recs.get("approved"):
            self.put(row, "restart_preserves_decision_and_chain",
                     "ABSENT" if not self.present(("GET", L + "/decisions")) else "BLOCKED",
                     "no decision recorded before restart")
            return
        l1 = self.fx.learner["learner_one"]
        led = self.call("teacher_one", "GET", self.path(L + "/decisions", learner_id=l1))
        ins = self.call("teacher_one", "GET", self.path(L + "/instruction", learner_id=l1))
        ok = led.status_code == 200 and led.json().get("chain_valid") and len(led.json().get("entries", [])) >= 1 \
            and ins.status_code == 200
        self.put(row, "restart_preserves_decision_and_chain", "PASS" if ok else "FAIL",
                 f"after SIGTERM+relaunch: ledger {led.status_code}, instruction {ins.status_code}")

    # ── revocation ───────────────────────────────────────────────────────────
    REV_CELLS = ["revocation_denies_old_session", "revocation_denies_new_session",
                 "revocation_removes_from_list", "revocation_closes_active_voice_stream",
                 "revocation_closes_active_tutoring_stream", "reconnect_after_revocation_denied",
                 "no_post_revocation_write", "revocation_before_decision_denied",
                 "no_post_revocation_voice_start", "revocation_is_audited", "other_teacher_unaffected"]

    def revocation(self) -> None:
        row = "learner_profile"
        if not self.teachers_ready():
            self.blocked(row, self.REV_CELLS)
            return
        c1, t1 = self.fx.campus["campus_one"], self.fx.teacher_id["teacher_one"]
        l1 = self.fx.learner["learner_one"]
        old_token = self.tok("teacher_one")
        pending = None
        if self.present(("POST", L + "/recommendations")):
            nr = self.call("teacher_one", "POST", self.path(L + "/recommendations", learner_id=l1))
            if nr.status_code == 200 and not nr.json().get("abstained"):
                pending = nr.json()
        # Three voice sessions opened BEFORE revocation, each for one probe:
        # one actively streamed, one only reconnected to afterwards, one only
        # written to afterwards — so no probe's outcome is an artifact of
        # another probe having already ended the session.
        s_active, s_reconnect, s_write = (self._voice_start("teacher_one") for _ in range(3))
        revoked = threading.Event()
        stream_result: dict = {}
        th = None
        if s_active:
            th = threading.Thread(target=lambda: stream_result.update(self._sse_open(
                "teacher_one", f"/voice/stream/{s_active}/events", seconds=40, until=revoked)))
            th.start()
            time.sleep(1.5)
        # Complete human-owned elevated WebAuthn ceremony BEFORE starting
        # the short local tutor stream. Otherwise the model stub could
        # finish normally while the passkey prompt is still completing,
        # falsely passing or failing a revocation race.
        self.seeder.elevate()
        tutor_spec = ("POST", L + "/tutoring/chat")
        tutor_result: dict = {"events": [], "finished": False}
        tutor_thread = None
        if self.present(tutor_spec):
            tutor_path = self.path(tutor_spec[1], learner_id=l1)

            def read_active_tutor():
                try:
                    with httpx.Client(base_url=self.api.base,
                                      timeout=cfg.REQUEST_TIMEOUT_S,
                                      verify=self.api.verify,
                                      headers={"User-Agent": self.api.ua}) as client:
                        with client.stream(
                            "POST", tutor_path,
                            json={"child_message": "[START]"},
                            headers={"Authorization": f"Bearer {old_token}"},
                        ) as response:
                            tutor_result["status"] = response.status_code
                            for line in response.iter_lines():
                                if line.startswith("data:"):
                                    value = line[5:].strip()
                                    try:
                                        item = json.loads(value)
                                    except ValueError:
                                        item = {"type": "invalid"}
                                    tutor_result["events"].append((time.time(), item))
                    tutor_result["finished"] = True
                    tutor_result["ended_at"] = time.time()
                except Exception as exc:
                    tutor_result["error"] = f"{type(exc).__name__}: {exc}"

            tutor_thread = threading.Thread(target=read_active_tutor, daemon=True)
            tutor_thread.start()
            # Synchronize against an *observed* first text chunk rather than
            # guessing a fixed delay across slow CI workers. Never assume
            # a response exists: the below assertion still FAILS if no
            # protected data preceded revocation.
            deadline = time.monotonic() + min(cfg.REQUEST_TIMEOUT_S, 10.0)
            while time.monotonic() < deadline:
                if any(event.get("type") == "text" for _, event in tutor_result["events"]):
                    break
                if tutor_result.get("finished") or tutor_result.get("error"):
                    break
                time.sleep(0.05)
        rv = self.api.call("DELETE", f"/pilot/campuses/{c1}/educators/{t1}/learners/{l1}", self.fx.admin_token)
        revoked.revoked_at = time.time()  # type: ignore[attr-defined]
        revoked.set()
        if rv.status_code != 204:
            for c in self.REV_CELLS:
                self.put(row, c, "FAIL", f"revoke route -> {rv.status_code}")
            return
        r_old = self.api.call("GET", self.path(L, learner_id=l1), old_token)
        self.put(row, "revocation_denies_old_session", "PASS" if r_old.status_code in (401, 404) else "FAIL",
                 f"pre-revocation token -> {r_old.status_code}")
        new_token = self.seeder.relogin_teacher("teacher_one")
        if not new_token:
            for c in ("revocation_denies_new_session", "revocation_removes_from_list",
                      "reconnect_after_revocation_denied", "no_post_revocation_write",
                      "no_post_revocation_voice_start"):
                self.put(row, c, "BLOCKED", "no fresh teacher session obtainable")
            self.put("decision", "revocation_before_decision_denied", "BLOCKED", "no fresh session")
        else:
            r_new = self.call("teacher_one", "GET", self.path(L, learner_id=l1))
            self.put(row, "revocation_denies_new_session", "PASS" if r_new.status_code == 404 else "FAIL",
                     f"fresh session -> {r_new.status_code}")
            lst = self.call("teacher_one", "GET", "/pilot/me/learners")
            self.put(row, "revocation_removes_from_list",
                     "PASS" if lst.status_code == 200 and l1 not in lst.text else "FAIL",
                     f"-> {lst.status_code}")
            if s_reconnect:
                rc = self._sse_open("teacher_one", f"/voice/stream/{s_reconnect}/events", seconds=4)
                self.put(row, "reconnect_after_revocation_denied", "PASS" if _sse_denied(rc) else "FAIL",
                         f"fresh session reattached to a pre-revocation voice stream: {_sse_desc(rc)}")
            else:
                self.put(row, "reconnect_after_revocation_denied", "BLOCKED", "no voice session")
            if s_write:
                fin = self.call("teacher_one", "POST", f"/voice/stream/{s_write}/finish")
                self.put(row, "no_post_revocation_write", "PASS" if fin.status_code in (401, 403, 404) else "FAIL",
                         f"finish on a pre-revocation voice session -> {fin.status_code}")
            else:
                self.put(row, "no_post_revocation_write", "BLOCKED", "no voice session")
            vs = self.call("teacher_one", "POST", "/voice/stream/start", {"language": "en", "learner_id": l1})
            self.put(row, "no_post_revocation_voice_start", "PASS" if vs.status_code in (401, 403, 404) else "FAIL",
                     f"new voice session naming the revoked learner -> {vs.status_code}")
            if pending:
                d = self.call("teacher_one", "POST", self.path(
                    L + "/recommendations/{recommendation_id}/decision", learner_id=l1,
                    recommendation_id=pending["recommendation_id"]),
                    {"action": "approve", "expected_version": pending["version"]})
                self.put("decision", "revocation_before_decision_denied",
                         "PASS" if d.status_code == 404 else "FAIL", f"-> {d.status_code}")
            else:
                self.put("decision", "revocation_before_decision_denied",
                         "ABSENT" if not self.present(("POST", L + "/recommendations")) else "BLOCKED",
                         "no pending recommendation")
        if th is not None:
            th.join(timeout=cfg.SSE_IDLE_WAIT_S + 45)
            r_at = revoked.revoked_at  # type: ignore[attr-defined]
            closed = (stream_result.get("ended") and not stream_result.get("error")
                      and (stream_result.get("end_time") or 1e18) <= r_at + cfg.SSE_IDLE_WAIT_S)
            # Protected output after revocation = any data event after it EXCEPT
            # the server's own terminal "unknown or expired session" notice,
            # which carries no learner data and is how the server tells the
            # client the stream is over. Anything else after r_at fails.
            after = [p for t, p in zip(stream_result.get("event_times", []),
                                       stream_result.get("event_payloads", []))
                     if t > r_at and not _is_session_ended_notice(p)]
            self.put(row, "revocation_closes_active_voice_stream", "PASS" if closed and not after else "FAIL",
                     f"server ended the stream within {cfg.SSE_IDLE_WAIT_S}s of revocation: {bool(closed)}; "
                     f"protected data events after revocation: {len(after)}; {_sse_desc(stream_result)}")
        else:
            self.put(row, "revocation_closes_active_voice_stream", "BLOCKED",
                     "teacher_one could not start a voice session")
        if tutor_thread is None:
            self.put(row, "revocation_closes_active_tutoring_stream", "ABSENT",
                     "UUID-keyed tutoring stream route not mounted")
        else:
            tutor_thread.join(timeout=cfg.SSE_IDLE_WAIT_S + 20)
            r_at = revoked.revoked_at  # type: ignore[attr-defined]
            records = tutor_result.get("events", [])
            before = [e for t, e in records if t <= r_at and e.get("type") == "text"]
            after = [e for t, e in records if t > r_at and e.get("type") == "text"]
            stopped = any(t >= r_at and e.get("type") == "error"
                          and e.get("message") == "Learner access ended"
                          for t, e in records)
            finished_on_time = (tutor_result.get("finished") and not tutor_result.get("error")
                                and tutor_result.get("ended_at", 1e18) <= r_at + cfg.SSE_IDLE_WAIT_S)
            ok = (tutor_result.get("status") == 200 and bool(before)
                  and not after and stopped and finished_on_time)
            self.put(row, "revocation_closes_active_tutoring_stream",
                     "PASS" if ok else "FAIL",
                     f"real local-model SSE status={tutor_result.get('status')}; "
                     f"text before revoke={len(before)}; protected text after={len(after)}; "
                     f"terminal revocation={stopped}; timely end={bool(finished_on_time)}; "
                     f"client error={tutor_result.get('error')}")
        audited = False
        aud = self.api.call("GET", "/admin/audit?limit=200", self.fx.admin_token)
        if aud.status_code == 200:
            # An entry whose EVENT is the revoke action and whose detail names
            # the revoked learner's UUID; not any string anywhere in the log.
            audited = any(str(e.get("event", "")).lower() in REVOCATION_AUDIT_MARKERS
                          and l1 in str(e.get("detail", ""))
                          for e in aud.json().get("entries", []))
        self.put(row, "revocation_is_audited", "PASS" if audited else "FAIL",
                 f"/admin/audit -> {aud.status_code}; revoke-action event naming the learner: {audited}")
        t2 = self.call("teacher_two", "GET", self.path(L, learner_id=self.fx.learner["learner_two"]))
        self.put(row, "other_teacher_unaffected", "PASS" if t2.status_code == 200 else "FAIL",
                 f"teacher_two own learner -> {t2.status_code}")

    def persistence_after_restart(self, phase: str) -> None:
        row = "learner_profile"
        if not self.teachers_ready():
            self.blocked(row, [f"restart_{phase}"])
            return
        l1, l2 = self.fx.learner["learner_one"], self.fx.learner["learner_two"]
        if phase == "before_revocation":
            r = self.call("teacher_one", "GET", self.path(L, learner_id=l1))
            self.put(row, "restart_preserves_access", "PASS" if r.status_code == 200 else "FAIL",
                     f"teacher_one own learner after relaunch -> {r.status_code}")
        else:
            token = self.seeder.relogin_teacher("teacher_one")
            r = self.call("teacher_one", "GET", self.path(L, learner_id=l1)) if token else None
            r2 = self.call("teacher_two", "GET", self.path(L, learner_id=l2))
            ok = r is not None and r.status_code == 404 and r2.status_code == 200
            self.put(row, "restart_preserves_revocation", "PASS" if ok else ("BLOCKED" if r is None else "FAIL"),
                     f"revoked teacher after relaunch -> {r.status_code if r else None}; "
                     f"other teacher -> {r2.status_code}")

    # ── deletion ─────────────────────────────────────────────────────────────
    DEL_CELLS = ["delete_succeeds_with_plain_confirmation", "post_delete_read_denied",
                 "post_delete_list_excludes", "post_delete_write_denied",
                 "post_delete_voice_denied", "post_delete_cache_evicted"]

    def deletion(self) -> None:
        row = next(r for r in TABLE if r["id"] == "learner_deletion")
        spec = row["delete"]
        if not self.present(spec):
            for c in self.DEL_CELLS:
                self.put(row, c, "ABSENT", f"{spec[0]} {spec[1]} not mounted")
            return
        if not self.teachers_ready():
            self.blocked(row, self.DEL_CELLS)
            return
        c2, l2 = self.fx.campus["campus_two"], self.fx.learner["learner_two"]
        self.seeder.elevate()
        target = spec[1].format(campus_id=c2, learner_id=l2)
        confirm = {"confirm_learner_id": l2,
                   "confirm_display_name": cfg.SHARED_LEARNER_DISPLAY_NAME}
        # Wrong-name confirmation must be rejected without deleting the
        # learner. A plain DELETE without a human confirmation is forbidden.
        denied = self.api.call(spec[0], target, self.fx.admin_token,
                               {**confirm, "confirm_display_name": "Wrong synthetic name"})
        prior = self.call("teacher_two", "GET", self.path(L, learner_id=l2))
        d = self.api.call(spec[0], target, self.fx.admin_token, confirm)
        body = d.json() if d.status_code == 200 else {}
        plain = (d.status_code == 200 and isinstance(body, dict)
                 and body.get("learner_id") == l2
                 and len(body.get("receipt_sha256", "")) == 64
                 and all(v == 0 for v in body.get("remaining_counts", {}).values())
                 and cfg.SHARED_LEARNER_DISPLAY_NAME not in d.text)
        safe = denied.status_code == 422 and prior.status_code == 200
        self.put(row, "delete_succeeds_with_plain_confirmation",
                 "PASS" if safe and plain else "FAIL",
                 f"wrong typed confirmation -> {denied.status_code}; learner still readable: "
                 f"{prior.status_code}; verified confirmed deletion -> {d.status_code}; "
                 f"content-free receipt: {bool(plain)}")
        r = self.call("teacher_two", "GET", self.path(L, learner_id=l2))
        self.put(row, "post_delete_read_denied", "PASS" if r.status_code in (401, 404) else "FAIL", f"-> {r.status_code}")
        lst = self.call("teacher_two", "GET", "/pilot/me/learners")
        self.put(row, "post_delete_list_excludes", "PASS" if l2 not in lst.text else "FAIL", f"-> {lst.status_code}")
        ev = ("POST", L + "/evidence")
        if self.present(ev):
            w = self.call("teacher_two", "POST", self.path(ev[1], learner_id=l2), SYNTH_DIBELS)
            self.put(row, "post_delete_write_denied", "PASS" if w.status_code in (401, 404) else "FAIL", f"-> {w.status_code}")
        else:
            self.put(row, "post_delete_write_denied", "ABSENT", "no learner-scoped write route mounted")
        v = self.call("teacher_two", "POST", "/voice/stream/start", {"language": "en", "learner_id": l2})
        self.put(row, "post_delete_voice_denied", "PASS" if v.status_code in (401, 403, 404) else "FAIL",
                 f"voice start for deleted learner -> {v.status_code}")
        self.put(row, "post_delete_cache_evicted", "UNVERIFIED",
                 "cache eviction is not observable over HTTP beyond the read denial above")

    # ── drive ────────────────────────────────────────────────────────────────
    def canonical_setup(self) -> None:
        """Each campus's Data Day calendar, through the real elevated admin
        route, before any canonical administration is recorded. The Valor
        default preset; the first Data Day is a fabricated date."""
        spec = ("PUT", "/pilot/campuses/{campus_id}/calendar")
        if not self.present(spec):
            self.put("data_day_packet", "campus_calendar_configured", "ABSENT",
                     f"{spec[0]} {spec[1]} not mounted")
            return
        self.seeder.elevate()
        codes = [self.api.call("PUT", spec[1].format(campus_id=self.fx.campus[k]), self.fx.admin_token,
                               {"preset": "valor_default", "first_data_day": SYNTH_FIRST_DATA_DAY}).status_code
                 for k in ("campus_one", "campus_two")]
        self.put("data_day_packet", "campus_calendar_configured",
                 "PASS" if codes == [200, 200] else "FAIL", f"calendar PUT per campus -> {codes}")

    def run(self) -> list[Cell]:
        _apply_overrides()
        if self.fx.campus:
            self.canonical_setup()
        for row in TABLE:
            if row.get("special") in ("voice", "g2", "deletion") or row["id"] == "tutoring_turn":
                continue
            # Recommendation creation is a stateful teacher approval prelude.
            # Exercise negative writes here, but create its single positive
            # proposal inside g2() so the candidate 409 pending-proposal
            # guard remains mandatory and is not bypassed.
            self.run_generic(row, defer_own_write=row["id"] == "recommendation")
        self.browser_agreement()
        self.voice_owner_binding()
        self.g2()
        # This write legitimately REQUIRES a teacher-approved G2 instruction.
        # Run it after the real evidence→recommendation→human decision journey,
        # not before approval and not by bypassing the approval guard.
        self.run_generic(next(row for row in TABLE if row["id"] == "tutoring_turn"))
        self.stack.restart_server()
        self.put("learner_profile", "restart_sigterm_relaunch", "PASS",
                 "server stopped by SIGTERM and relaunched", **self.stack.events[-1])
        self.persistence_after_restart("before_revocation")
        self.g2_after_restart()
        self.revocation()
        self.stack.restart_server()
        self.persistence_after_restart("after_revocation")
        self.deletion()
        return self.cells


def _is_session_ended_notice(payload: str) -> bool:
    """Exactly the server's terminal error event for an unknown/ended voice
    session, {"type": "error", "message": "unknown or expired session"}."""
    try:
        item = json.loads(payload)
    except (TypeError, ValueError):
        return False
    return item == {"type": "error", "message": "unknown or expired session"}


def _sse_denied(r: dict) -> bool:
    """An SSE attach was refused: a 4xx, or the server's own 'unknown or
    expired session' error event followed by the server ending the stream.
    An attach that stays open (pings only) or a client-side error is NOT a
    denial."""
    if r.get("status") in (401, 403, 404):
        return True
    return bool(r.get("status") == 200 and r.get("ended") and not r.get("error")
                and r.get("data_events") == 1 and "unknown or expired" in r.get("text", "").lower())


def _sse_desc(r: dict) -> str:
    return (f"status={r.get('status')} server_ended={r.get('ended')} error={r.get('error')} "
            f"data_events={r.get('data_events')} pings={r.get('pings')}")


def summarize(cells: list[Cell]) -> dict:
    counts: dict = {}
    for c in cells:
        counts.setdefault(c.group, {}).setdefault(c.status, 0)
        counts[c.group][c.status] += 1
    total = {s: sum(1 for c in cells if c.status == s) for s in
             ("PASS", "FAIL", "ABSENT", "BLOCKED", "UNVERIFIED")}
    return {"by_group": counts, "total": total, "cells": len(cells),
            "qualified": total["PASS"] == len(cells) and len(cells) > 0}


def write_reports(cells: list[Cell], out: Path) -> dict:
    summary = summarize(cells)
    (out / "matrix.json").write_text(json.dumps(
        {"summary": summary, "cells": [c.__dict__ for c in cells]}, indent=2) + "\n")
    lines = ["| Group | Record type | Cell | Status | Detail |", "|---|---|---|---|---|"]
    for c in cells:
        lines.append(f"| {c.group} | {c.row} | {c.cell} | {c.status} | {c.detail.replace('|', '/')} |")
    (out / "matrix.md").write_text("\n".join(lines) + "\n")
    _junit(cells, out / "junit-matrix.xml")
    return summary


def _junit(cells: list[Cell], path: Path) -> None:
    from xml.sax.saxutils import escape, quoteattr
    fails = sum(1 for c in cells if c.status != "PASS")
    parts = [f'<testsuite name="synthetic-qualification-matrix" tests="{len(cells)}" failures="{fails}">']
    for c in cells:
        parts.append(f"<testcase classname={quoteattr(c.group + '.' + c.row)} name={quoteattr(c.cell)}>")
        if c.status != "PASS":
            parts.append(f"<failure message={quoteattr(c.status)}>{escape(c.detail)}</failure>")
        parts.append("</testcase>")
    parts.append("</testsuite>")
    path.write_text("\n".join(parts) + "\n")
