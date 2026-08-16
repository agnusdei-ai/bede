"""COPPA compliance guards — the written policies checked against the code.

`docs/RETENTION_POLICY.md` and `docs/INFORMATION_SECURITY_POLICY.md` exist to
satisfy the amended FTC COPPA Rule's requirement for a written retention policy
and a written security program. A compliance artifact is worth exactly as much
as its accuracy, and the failure mode is silent: nothing errors, nothing fails
to build, and the document simply describes a version of the system that has
moved on. This repo has hit that shape repeatedly (see CLAUDE.md's "Thirty
settings never reached the container"), so the policies ship with checks rather
than a promise to keep them current by hand.

**These tests found a real defect on the day they were written.**
`RETENTION_POLICY.md` claimed "exactly four demo-related tables" and omitted
`DemoCodeActivityLog`, the demo's work ledger, which had been collected since
it shipped. Nothing was hidden from visitors — the public Privacy Notice, the
consent screen, and `docs/DATA_RETENTION.md` all described it, and its
retention window was always the same 6 hours — but the one document required
to enumerate every category did not enumerate it. That is precisely the gap
this file exists to close.

What is enforced here is agreement between a policy and the code, never
whether a policy is *sufficient*. No test can rule on that; a lawyer can.
These tests know whether the document still describes this system.

Deliberately dependency-light — the checks read source text and ORM metadata
rather than standing up a database, so they run in the same pass as the rest of
the suite and cannot be skipped for want of a fixture.
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_API = _ROOT / "homeschool-api"

_RETENTION_POLICY = _ROOT / "docs" / "RETENTION_POLICY.md"
_INFOSEC_POLICY = _ROOT / "docs" / "INFORMATION_SECURITY_POLICY.md"
_DATA_RETENTION = _ROOT / "docs" / "DATA_RETENTION.md"
_PUBLIC_NOTICE = _ROOT / "demo" / "public" / "privacy.html"
_BUILD_SITE = _ROOT / "scripts" / "build_pages_site.sh"

_DATABASE_PY = _API / "core" / "database.py"
_DEMO_SESSION_PY = _API / "core" / "demo_code_session.py"
_SIGNALS_PY = _API / "services" / "interaction_signals.py"
_QUOTA_PY = _API / "core" / "diagnostic_preview_quota.py"
_DELETION_PY = _API / "services" / "student_deletion.py"
_FEEDBACK_ROUTER = _API / "routers" / "feedback.py"

_MODEL = re.compile(r"^class (\w+)\(Base\):(.*?)(?=^class |\Z)", re.M | re.S)
_TABLENAME = re.compile(r'__tablename__\s*=\s*"([^"]+)"')
_COLUMN = re.compile(r"^\s{4}(\w+):\s*Mapped\[", re.M)


def _models() -> dict[str, dict]:
    """Every ORM model in core/database.py, by class name.

    Read from source rather than imported: importing core.database pulls in
    pydantic settings and a live engine, and a compliance guard that only runs
    when the app's full environment is configured is a guard that stops running.

    `columns` is parsed from the `name: Mapped[...]` declarations specifically,
    never from the class body as a whole. These models carry long explanatory
    docstrings, and the first version of this file scanned the raw text — which
    read `DemoInteractionSignal` as student-scoped on the strength of a
    sentence explaining that it deliberately *cannot* be joined to a student
    name, and read `DemoCodeActivityLog` as holding a transcript on the
    strength of "never a transcript". A privacy guard that fires on a document
    saying the right thing is worse than no guard, because it trains everyone
    to route around it.
    """
    src = _DATABASE_PY.read_text()
    out = {}
    for m in _MODEL.finditer(src):
        name, body = m.group(1), m.group(2)
        tn = _TABLENAME.search(body)
        columns = set(_COLUMN.findall(body))
        out[name] = {
            "table": tn.group(1) if tn else None,
            "body": body,
            "columns": columns,
            "student_scoped": "student_name" in columns,
        }
    return out


# Demo tables that are deliberately NOT deleted when one demo code ends,
# each because it is not keyed by the code in the first place. Both carry
# their own retention window in RETENTION_POLICY.md instead, and neither can
# be joined back to a visitor:
#
#   DiagnosticPreviewUse   keyed by a hashed visitor IP. There is no code to
#                          delete it by, and deleting it on logout would make
#                          the rate limit trivially resettable.
#   DemoInteractionSignal  keyed by a keyed HMAC of the code, not the code, so
#                          it is unreversible by construction. It exists
#                          specifically to outlive one session so patterns can
#                          be aggregated across many, on its own 30-day purge.
_NOT_CODE_SCOPED = {"DiagnosticPreviewUse", "DemoInteractionSignal"}


def _demo_models() -> dict[str, dict]:
    """Models holding data collected from a public-demo visitor.

    Keyed off the `Demo` class-name prefix plus the one table that is
    demo-scoped without it, so a newly added demo table is picked up by
    existing here at all rather than by anyone remembering to list it.
    """
    models = _models()
    return {
        name: info
        for name, info in models.items()
        if name.startswith("Demo") or name == "DiagnosticPreviewUse"
    }


def test_the_model_scan_finds_something():
    """Canary. Every test below reads this scan, so a changed class shape
    would make the whole file pass while checking nothing."""
    models = _models()
    assert len(models) >= 20, (
        f"Only parsed {len(models)} ORM models from {_DATABASE_PY}. Either the "
        "file was restructured or the 'class X(Base):' shape changed, which "
        "would make every other test here silently vacuous."
    )
    assert "DemoCodeSession" in models
    assert len(_demo_models()) >= 4


# ── The written retention policy enumerates every category ──────────────


def test_every_demo_table_appears_in_the_written_retention_policy():
    """The COPPA Rule wants a policy stating, for each category of personal
    information collected, why it is collected and when it is deleted. A table
    that exists in the code and nowhere in the policy is a category being
    collected outside the document that is supposed to enumerate them.

    This is the check that caught `DemoCodeActivityLog`. Matching on the table
    name rather than prose because prose can describe a thing without ever
    naming the row it lives in, which is how the ledger stayed invisible here
    while being described in three other documents."""
    # Only the categories table counts, not the document as a whole. Naming a
    # table in a paragraph explaining that it was once *missing* from the table
    # is not enumerating it — and that exact case made an earlier version of
    # this test pass while the row was deleted. Verified by deleting it again.
    rows = "\n".join(
        line for line in _RETENTION_POLICY.read_text().splitlines()
        if line.lstrip().startswith("|")
    )
    missing = {
        name: info["table"]
        for name, info in _demo_models().items()
        if info["table"] and info["table"] not in rows and name not in rows
    }
    assert not missing, (
        f"Demo-visitor table(s) {missing} exist in core/database.py but are "
        f"named nowhere in {_RETENTION_POLICY.name}. Every category of data "
        "collected from a demo visitor needs a row in that policy's table "
        "stating its purpose and its deletion timeframe — that is the written "
        "policy the FTC COPPA Rule requires, and an omission there is a defect "
        "even when the practice itself is correct and disclosed elsewhere."
    )


def test_the_policys_own_table_count_matches_the_code():
    """The policy states a count of demo-related tables as a checkable claim
    for anyone reviewing it against the code. A count that drifts turns the
    one sentence inviting verification into the one sentence that fails it."""
    policy = _RETENTION_POLICY.read_text()
    stated = re.search(
        r"defines exactly (\w+)\s*\n?\s*demo-\s*\n?related tables", policy
    )
    assert stated, (
        "Could not find the 'defines exactly N demo-related tables' claim in "
        f"{_RETENTION_POLICY.name}. If that sentence was reworded, update this "
        "test rather than deleting it."
    )
    words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    claimed = words.get(stated.group(1).lower())
    assert claimed is not None, f"Unrecognized count word {stated.group(1)!r}."

    # The policy's own sentence excludes the rate-limit table ("plus the
    # rate-limit table above"), so DiagnosticPreviewUse is not in this count.
    actual = len([n for n in _demo_models() if n != "DiagnosticPreviewUse"])
    assert claimed == actual, (
        f"{_RETENTION_POLICY.name} claims exactly {claimed} demo-related "
        f"tables; core/database.py defines {actual}. The policy invites a "
        "reviewer to check this against the code, so it has to survive that "
        "check."
    )


@pytest.mark.parametrize(
    "constant_file, pattern, policy_phrase, what",
    [
        (_DEMO_SESSION_PY, r"_CODE_TTL_SECONDS = 6 \* 60 \* 60", "6 hours",
         "the demo session retention window"),
        (_SIGNALS_PY, r"_RETENTION_DAYS = 30", "30 days",
         "the interaction-signal retention window"),
        (_QUOTA_PY, r"_WINDOW_SECONDS = 30 \* 24 \* 60 \* 60", "30-day",
         "the diagnostic-preview rate-limit window"),
    ],
)
def test_stated_retention_windows_match_the_code(constant_file, pattern, policy_phrase, what):
    """A deletion timeframe is the operative promise in a retention policy.
    Both halves are checked, because either one drifting makes the policy
    wrong: the constant can change under a stale document, or the document can
    be edited to a window nothing implements."""
    src = constant_file.read_text()
    assert re.search(pattern, src), (
        f"Could not find {what} in {constant_file.name} (expected /{pattern}/). "
        f"If the constant moved or was renamed, {_RETENTION_POLICY.name} needs "
        "checking against its new value, not just this test updating."
    )
    assert policy_phrase in _RETENTION_POLICY.read_text(), (
        f"{_RETENTION_POLICY.name} no longer states {policy_phrase!r} for "
        f"{what}, but the code still implements it."
    )


def test_the_policy_names_a_responsible_individual_and_a_review_date():
    """Both are required elements of the written program, and both are the
    kind of thing that silently rots — a policy with no owner and no review
    date reads as maintained while being nobody's."""
    policy = _RETENTION_POLICY.read_text()
    assert "Responsible individual" in policy
    assert re.search(r"Last reviewed: \d{4}-\d{2}-\d{2}", policy), (
        f"{_RETENTION_POLICY.name} has no 'Last reviewed: YYYY-MM-DD' line."
    )
    infosec = _INFOSEC_POLICY.read_text()
    assert re.search(r"Last reviewed: \d{4}-\d{2}-\d{2}", infosec), (
        f"{_INFOSEC_POLICY.name} has no 'Last reviewed: YYYY-MM-DD' line."
    )


# ── Deletion actually reaches everything ────────────────────────────────


def test_logout_deletes_every_demo_table_for_that_code():
    """The policy promises deletion 'immediately on logout' for every demo
    category, not just the session row. A table added later without a matching
    delete in end_session() would leave a visitor's data alive for the rest of
    the 6-hour window after they explicitly ended the session."""
    src = _DEMO_SESSION_PY.read_text()
    end_session = re.search(
        r"async def end_session\(.*?(?=\nasync def |\ndef )", src, re.S
    )
    assert end_session, "Could not find end_session() in core/demo_code_session.py."

    # Look for the actual `delete(Model)` calls, not the model name anywhere in
    # the function. end_session()'s own docstring lists every table it clears,
    # so a name-anywhere check kept passing with the delete removed — the
    # docstring was doing the asserting. Verified by removing it again.
    deleted = set(re.findall(r"delete\((\w+)\)", end_session.group(0)))
    expected = _demo_models().keys() - _NOT_CODE_SCOPED
    missing = expected - deleted
    assert not missing, (
        f"end_session() does not delete {sorted(missing)}. "
        f"{_RETENTION_POLICY.name} promises every demo category is deleted "
        "immediately on logout, so a table reachable by demo code has to be "
        "deleted here too."
    )


def test_ttl_cleanup_reaches_every_code_scoped_demo_table():
    """The other half of the same promise: a visitor who closes the tab
    without logging out is covered by the 6-hour sweep instead. Both paths
    have to know about the same set of tables."""
    src = _DEMO_SESSION_PY.read_text()
    generate = re.search(
        r"async def generate_code\(.*?(?=\nasync def |\ndef )", src, re.S
    )
    assert generate, "Could not find generate_code() in core/demo_code_session.py."
    deleted = set(re.findall(r"delete\((\w+)\)", generate.group(0)))
    expected = _demo_models().keys() - _NOT_CODE_SCOPED
    missing = expected - deleted
    assert not missing, (
        f"The opportunistic TTL cleanup in generate_code() does not sweep "
        f"{sorted(missing)}. A visitor who never logs out would keep that data "
        "past the 6-hour window this policy commits to."
    )


def test_every_student_scoped_table_is_deleted_or_deliberately_exempt():
    """A parent's right to delete their child's data is the COPPA obligation
    with the most surface area, because it has to reach every table at once.
    services/student_deletion.py is the single place holding that list, and its
    own docstring records that the list had already drifted between call sites
    before it existed. This is that drift made loud."""
    # Read the ("label", Model) pairs the delete loop actually iterates, not
    # the file text. That module's docstring names several tables precisely to
    # explain why they are NOT deleted, so a name-anywhere check would count
    # an exclusion as an inclusion.
    deletion_src = _DELETION_PY.read_text()
    deleted = set(re.findall(r'\(\s*"[\w]+"\s*,\s*(\w+)\s*\)', deletion_src))
    assert len(deleted) >= 8, (
        "Parsed only "
        f"{sorted(deleted)} from delete_all_student_data()'s table list. If "
        "that loop was restructured this test needs updating, not deleting — "
        "as written it would now pass for almost any cascade."
    )
    models = _models()

    # Exemptions are named here rather than inferred, each with the reason
    # student_deletion.py's own docstring gives.
    exempt = {
        # Demo data: pseudonymous, self-chosen alias, its own 6-hour retention
        # story. Not a real family's record.
        "DemoCodeSession", "DemoCodeUnitNote", "DemoCodeFaithNote",
        "DemoCodeActivityLog", "DemoInteractionSignal",
        # Crypto-shredded via student_keys.destroy() in the same transaction
        # rather than row-deleted — checked separately below.
        "StudentKey",
    }

    student_tables = {
        name for name, info in models.items() if info["student_scoped"]
    }
    missing = student_tables - exempt - deleted
    assert not missing, (
        f"Table(s) {sorted(missing)} are scoped to a student but are not "
        "deleted by services/student_deletion.py. A parent deleting their "
        "child's data would leave these behind, silently. Either add them to "
        "delete_all_student_data() or add them to this test's exemption list "
        "with a stated reason."
    )

    stale = {name for name in exempt if name not in models}
    assert not stale, (
        f"Exemption(s) {sorted(stale)} no longer name a real model. An "
        "exemption that outlives the thing it excused hides the next one."
    )


def test_deletion_crypto_shreds_the_students_key():
    """Row deletion alone leaves decryptable copies in dead tuples, WAL, and
    every backup taken beforehand. Destroying the student's own key is what
    makes 'deleted' true beyond the live table, so it is part of the promise
    rather than an optimization."""
    src = _DELETION_PY.read_text()
    assert "student_keys.destroy" in src, (
        "delete_all_student_data() no longer crypto-shreds the student's key. "
        "Without it, a parent's deletion request leaves their child's data "
        "readable in backups under a DATA_KEY that never changes."
    )
    assert "await db.commit()" in src, (
        "The shred and the row deletes must commit together — a partial "
        "failure otherwise leaves either unreadable rows or an openable backup."
    )


# ── Things the policy says are never stored ─────────────────────────────


def test_feedback_is_never_persisted():
    """The policy states feedback exists only as one outbound email and that
    no row is ever created. 'Never stored' is a stronger commitment than a
    short window, so it is worth a check that nothing quietly starts storing."""
    src = _FEEDBACK_ROUTER.read_text()
    for forbidden in ("AsyncSessionLocal", "get_db", "db.add(", "db.commit("):
        assert forbidden not in src, (
            f"routers/feedback.py now references {forbidden!r}, which suggests "
            f"feedback is being persisted. {_RETENTION_POLICY.name} states it "
            "is never written to any database — change the policy in the same "
            "commit, or don't store it."
        )


def test_no_table_holds_demo_conversation_text():
    """The policy's strongest claim: no table holds conversation transcript
    text or audio for any demo_code session. SessionTranscript exists and is a
    real family's, so this checks that the demo models have not grown a
    transcript-shaped column."""
    for name, info in _demo_models().items():
        # A count of messages is not a message. Counters and flags describe
        # the shape of a session without carrying any of its content, and
        # DemoCodeSession.message_count is what enforces the demo's own spend
        # cap — treating it as content would be the same docstring-scanning
        # bluntness this file's _models() comment warns about.
        # `_enc` columns stay in scope deliberately — an encrypted transcript
        # is still a transcript, and `transcript_enc` is exactly the shape this
        # check exists to catch.
        content_columns = {
            c for c in info["columns"]
            if not c.endswith(("_count", "_at")) and c not in {"redeemed", "email_sent"}
        }
        columns = " ".join(sorted(content_columns)).lower()
        for forbidden in ("transcript", "audio", "message", "conversation", "text"):
            assert forbidden not in columns, (
                f"{name} has a column matching {forbidden!r} ({sorted(content_columns)}). "
                f"{_RETENTION_POLICY.name} states plainly that no table holds "
                "conversation text or audio for a demo session, and the demo's "
                "own consent screen promises the same thing to the visitor."
            )


# ── The internal policies stay internal ─────────────────────────────────


def test_the_internal_policies_are_not_published():
    """Both policies open by stating they are internal and not part of the
    built site, resting that claim on build_pages_site.sh copying only site/
    and demo/dist/. If docs/ ever gets copied, two documents become publicly
    wrong about themselves in the same moment."""
    build = _BUILD_SITE.read_text()
    copies = [
        line.strip()
        for line in build.splitlines()
        if re.match(r"\s*(cp|rsync)\b", line) and not line.strip().startswith("#")
    ]
    assert copies, (
        f"Found no copy commands in {_BUILD_SITE.name}. If that script was "
        "restructured, this test needs updating rather than deleting."
    )
    leaking = [c for c in copies if re.search(r"\bdocs/", c)]
    assert not leaking, (
        f"{_BUILD_SITE.name} copies docs/ into the published site: {leaking}. "
        f"{_RETENTION_POLICY.name} and {_INFOSEC_POLICY.name} both open by "
        "stating they are internal and unpublished, resting on exactly this."
    )


# ── Disclosure stays consistent across the three places it lives ────────


def test_the_ai_vendor_is_named_consistently_in_all_three_disclosures():
    """`RETENTION_POLICY.md` records, as its own commitment, that changing
    which AI vendor is primary or secondary must update this policy, the
    security policy's vendor table, and the public Privacy Notice in the same
    change. That commitment exists because it was already broken once — the
    notice named Anthropic while the demo ran on OpenAI. This is that
    commitment made mechanical rather than remembered."""
    notice = _PUBLIC_NOTICE.read_text()
    infosec = _INFOSEC_POLICY.read_text()
    policy = _RETENTION_POLICY.read_text()

    render = (_ROOT / "render.yaml").read_text()
    order = re.search(r"BEDE_ADAPTER_ORDER\s*\n?\s*value:\s*([\w,]+)", render)
    if order is None:
        order = re.search(r'BEDE_ADAPTER_ORDER["\s:=]+([\w,]+)', render)
    assert order, (
        "Could not read BEDE_ADAPTER_ORDER out of render.yaml. If the demo's "
        "provider order moved, the three disclosure documents need checking "
        "against wherever it now lives."
    )

    vendors = {
        "openai": "OpenAI",
        "mistral": "Mistral",
        "anthropic": ("Anthropic", "Claude"),
    }
    for adapter in order.group(1).split(","):
        adapter = adapter.strip()
        names = vendors.get(adapter)
        if names is None:
            pytest.fail(
                f"render.yaml's BEDE_ADAPTER_ORDER names adapter {adapter!r}, "
                "which this test has no vendor name for. A new AI vendor has "
                "to be added to all three disclosure documents and to this map."
            )
        names = (names,) if isinstance(names, str) else names
        for doc, path in (
            (notice, _PUBLIC_NOTICE), (infosec, _INFOSEC_POLICY), (policy, _RETENTION_POLICY)
        ):
            assert any(n in doc for n in names), (
                f"The demo is configured to send conversations to {names[0]} "
                f"(BEDE_ADAPTER_ORDER includes {adapter!r}), but {path.name} "
                "never names it. A visitor's conversation reaching an undisclosed "
                "vendor is the exact failure the 2026-08-03 correction recorded "
                "in RETENTION_POLICY.md was about."
            )


@pytest.mark.parametrize(
    "path",
    [
        "docs/RETENTION_POLICY.md",
        "docs/INFORMATION_SECURITY_POLICY.md",
        "docs/DATA_RETENTION.md",
        "demo/public/privacy.html",
        "scripts/build_pages_site.sh",
        "render.yaml",
    ],
)
def test_every_file_this_guard_reads_is_in_the_ci_change_filter(path):
    """Every file above lives outside homeschool-api/, and this suite is the
    only thing checking it. .github/workflows/test.yml computes relevant=false
    for a change that touches nothing it names, skipping api-tests entirely —
    so a policy-only edit, or a render.yaml provider switch, would sail past
    the guard written for exactly that change. Same reasoning, and the same
    grep-the-pattern-line technique, as test_decision_register.py's own
    version: an earlier form of that test matched the explanatory comment
    beside the filter and would have kept passing with the pattern deleted."""
    workflow = (_ROOT / ".github" / "workflows" / "test.yml").read_text()
    filter_lines = [
        line for line in workflow.splitlines() if "grep -qE" in line and "^(" in line
    ]
    assert filter_lines, (
        "Could not find the change-filter `grep -qE` line in "
        ".github/workflows/test.yml. If that job was restructured, this test "
        "needs updating rather than deleting."
    )
    # The filter escapes dots for grep; compare on that form, not the raw path.
    escaped = path.replace(".", r"\.")
    assert any(escaped in line for line in filter_lines), (
        f"{path} is not in .github/workflows/test.yml's change-filter pattern, "
        "so a change touching only it computes relevant=false, skips api-tests, "
        "and never runs this suite. A comment mentioning the file does not count."
    )


def test_the_two_retention_documents_agree_on_which_is_which():
    """RETENTION_POLICY.md is the commitment; DATA_RETENTION.md is the
    technical description. Each says so and points at the other. If either
    stops pointing, a reader lands in one and cannot tell it is half the
    story."""
    assert "DATA_RETENTION.md" in _RETENTION_POLICY.read_text(), (
        "RETENTION_POLICY.md no longer points at DATA_RETENTION.md, the "
        "technical description a reviewer verifies it against."
    )
    assert "RETENTION_POLICY.md" in _DATA_RETENTION.read_text(), (
        "DATA_RETENTION.md no longer points back at RETENTION_POLICY.md, the "
        "compliance artifact it is the evidence for."
    )
