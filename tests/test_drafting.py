"""Email drafts: gating, honesty and quality checks."""

from __future__ import annotations

import re

from src import models as m
from src.drafting import build_draft, build_follow_up, can_draft, draft_hash
from src.validate import PLACEHOLDER_RE

from .conftest import make_record


def body_words(draft):
    parts = draft.body.split("\n\n")
    return sum(len(p.split()) for p in parts[1:-1])


def test_draft_uses_verified_facts_and_cv_sentences(record, profile, today):
    draft = build_draft(record, profile, today)
    assert draft.body.startswith("Dear Professor Testperson,")
    assert "household food insecurity" in draft.body
    assert "Food insecurity and diet quality in pregnancy" in draft.body
    assert "I provided nutrition counseling for underserved patients." in draft.body
    assert "CGPA of 3.80/4.00" in draft.body
    assert "Spring 2027 or Fall 2027" in draft.body
    assert "assistantship" in draft.body
    assert not PLACEHOLDER_RE.search(draft.body)
    assert body_words(draft) <= 220


def test_draft_never_claims_to_have_read_the_paper(record, profile, today):
    for rid in ("R0001", "R0002", "R0003", "R0004"):
        draft = build_draft(dict(record, record_id=rid), profile, today)
        assert not re.search(r"\bI (have )?read\b", draft.body)


def test_draft_mentions_only_recorded_facts(profile, today):
    rec = make_record(relevant_publication_1="", publication_1_year="", research_interests="school meal policy")
    draft = build_draft(rec, profile, today)
    assert "paper" not in draft.body
    assert any("No recent publication" in w for w in draft.warnings)


def test_ai_professor_gets_ml_evidence_first(profile, today):
    rec = make_record(research_interests="machine learning for diabetes risk prediction; precision nutrition")
    draft = build_draft(rec, profile, today)
    background = draft.body.split("\n\n")[2]
    assert background.index("ML model") < background.index("dietary interventions")


def test_fall_only_program_asks_about_fall(profile, today):
    rec = make_record(spring_2027_status="No spring admission (fall only)")
    draft = build_draft(rec, profile, today)
    assert "Fall 2027" in draft.subject and "Spring" not in draft.subject


def test_personal_note_is_inserted(record, profile, today):
    rec = dict(record, personal_note="I was struck by your use of SNAP participation data")
    assert "I was struck by your use of SNAP participation data." in build_draft(rec, profile, today).body


def test_drafts_vary_between_professors(profile, today):
    a = build_draft(make_record(record_id="R0001"), profile, today).body
    b = build_draft(make_record(record_id="R0002"), profile, today).body
    c = build_draft(make_record(record_id="R0003"), profile, today).body
    assert len({a.split("\n\n")[1][:30], b.split("\n\n")[1][:30], c.split("\n\n")[1][:30]}) >= 2


def test_can_draft_gates(record, today):
    assert can_draft(record, today, 4)[0]
    assert not can_draft(dict(record, workflow_status=m.NEEDS_VERIFICATION), today, 4)[0]
    assert not can_draft(dict(record, verification_status=m.VER_PARTIAL), today, 4)[0]
    assert not can_draft(dict(record, email_verification=m.EMAIL_SEEN_IN_SEARCH), today, 4)[0]
    assert not can_draft(dict(record, fit_score="2"), today, 4)[0]
    assert not can_draft(record, today, 4, suppressed=True)[0]
    assert not can_draft(dict(record, workflow_status=m.SENT), today, 4)[0]
    assert not can_draft(dict(record, eligibility_notes="discourages contacting advisors"), today, 4)[0]
    assert not can_draft(dict(record, workflow_status=m.DRAFT_READY), today, 4)[0]
    assert can_draft(dict(record, workflow_status=m.DRAFT_READY), today, 4, force=True)[0]


def test_follow_up_is_short_and_polite(record, profile, today):
    rec = dict(record, email_subject="Prospective PhD student", last_contact_date="2026-10-01")
    draft = build_follow_up(rec, profile, today)
    assert draft.subject == "Re: Prospective PhD student"
    assert "2026-10-01" in draft.body
    assert "will not follow up again" in draft.body
    assert len(draft.body.split()) < 150


def test_draft_hash_changes_with_text(record):
    rec = dict(record, email_subject="A", email_draft="B")
    h = draft_hash(rec)
    assert h == draft_hash(dict(rec))
    assert h != draft_hash(dict(rec, email_draft="B changed"))
    assert h != draft_hash(dict(rec, institutional_email="other@testing.edu"))
