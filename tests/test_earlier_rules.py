"""Records marked verified under the earlier, email-only rules are checked again, and their emails follow the new checks."""

from __future__ import annotations

from src import checks as ck
from src import models as m
from src.drafting import apply_draft, build_draft, can_draft, draft_hash
from src.editing import apply_edit
from src.storage import load_records, save_records
from src.tracker import read_log
from src.verify import verify_record

from .conftest import make_record, write_profile
from .test_verification_checks import CROSSREF_OK, PROFILE, PROGRAM, StubWeb


def drafted(profile, today, **overrides):
    rec = make_record(**overrides)
    apply_draft(rec, build_draft(rec, profile, today), today)
    return rec


def web_for(rec):
    return StubWeb({rec["faculty_profile_url"]: PROFILE, rec["program_url"]: PROGRAM})


def test_verify_checks_earlier_records_first_and_sets_their_old_email_aside(settings, profile, today, monkeypatch, capsys):
    from src import cli, http_client

    write_profile(settings, profile)
    old = drafted(profile, today)  # verified by email only, with an email written before the checks existed
    assert ck.checked_under_earlier_rules(old)
    sample = make_record(record_id="R0002", record_source="sample", email_verification=m.EMAIL_SAMPLE)
    new = make_record(record_id="R0003", institutional_email="", email_source_url="", email_verification="",
                      verification_status="not_verified", workflow_status="needs_verification")
    save_records(settings.tracker_path, [new, sample, old])
    monkeypatch.setattr(http_client, "PoliteClient", lambda *a, **k: web_for(old))
    monkeypatch.setenv("OUTREACH_ROOT", str(settings.root))

    assert cli.main(["verify"]) == 0
    out = capsys.readouterr().out
    assert "1 record(s) were marked verified under the earlier, email-only rules" in out
    assert out.index("R0001") < out.index("R0003")  # the earlier records are checked first
    by_id = {r["record_id"]: r for r in load_records(settings.tracker_path)}
    rec, untouched, checked = by_id["R0001"], by_id["R0002"], by_id["R0003"]
    assert rec["workflow_status"] == m.VERIFIED and rec["verification_status"] == m.VER_VERIFIED
    assert rec["email_draft"] == "" and rec["email_subject"] == ""
    assert ck.status_of(ck.load_checks(rec), "research") == ck.PASSED
    [saved] = list(settings.old_drafts_dir.glob("R0001_*.txt"))
    assert old["email_draft"] in saved.read_text(encoding="utf-8")  # the old text is never lost
    assert any(r["action"] == "email_rechecked" and r["record_id"] == "R0001" for r in read_log(settings))
    assert "set aside" in out and "4_run_pipeline.bat writes it again" in out
    assert can_draft(rec, today, settings.min_fit_for_draft)[0]  # so the pipeline writes it again from the checked facts
    assert ck.load_checks(untouched) == {}  # sample records are never checked against real websites
    assert checked["verification_status"] == m.VER_VERIFIED


def test_an_approved_email_from_before_the_checks_is_approved_again(settings, profile, today):
    rec = drafted(profile, today)
    rec["workflow_status"], rec["approval_hash"], rec["approved_on"] = m.APPROVED, draft_hash(rec), "2026-10-10"
    outcome = verify_record(rec, web_for(rec), today, evidence_dir=settings.evidence_dir, old_drafts_dir=settings.old_drafts_dir)
    assert rec["workflow_status"] == m.VERIFIED and rec["approval_hash"] == "" and rec["approved_on"] == ""
    assert "set aside" in outcome.email_refresh
    [saved] = list(settings.old_drafts_dir.glob("R0001_*.txt"))
    assert "approved on 2026-10-10" in saved.read_text(encoding="utf-8")


def test_an_earlier_email_whose_research_is_not_on_the_page_waits_for_checks(settings, profile, today):
    rec = drafted(profile, today, research_interests="sports nutrition; exercise physiology")
    verify_record(rec, web_for(rec), today, evidence_dir=settings.evidence_dir, old_drafts_dir=settings.old_drafts_dir)
    assert rec["verification_status"] != m.VER_VERIFIED and rec["workflow_status"] == m.NEEDS_VERIFICATION
    assert rec["email_draft"] == ""


def test_an_edited_email_is_kept_and_a_new_problem_cancels_its_approval(settings, profile, today):
    rec = make_record(institutional_email="", email_source_url="", email_verification="", verification_status="not_verified",
                      workflow_status="needs_verification")
    spring_open = PROGRAM.replace("We do not admit new students in the spring semester.",
                                  "Applications for Spring 2027 entry are due November 15, 2026.")
    first = StubWeb({rec["faculty_profile_url"]: PROFILE, rec["program_url"]: spring_open},
                    {"https://api.crossref.org/works/": (200, CROSSREF_OK)})
    verify_record(rec, first, today, evidence_dir=settings.evidence_dir)
    assert rec["verification_status"] == m.VER_VERIFIED and not ck.problems(rec)
    apply_draft(rec, build_draft(rec, profile, today), today)
    body = rec["email_draft"].replace("I am writing because", "I am writing to you because")
    assert apply_edit(rec, rec["institutional_email"], rec["email_subject"], body, today, evidence_dir=settings.evidence_dir).ok
    rec["workflow_status"], rec["approval_hash"] = m.APPROVED, draft_hash(rec)
    # Checked again: the program page now shows a conflict (no Spring entry), so the approval no longer stands.
    outcome = verify_record(rec, web_for(rec), today, evidence_dir=settings.evidence_dir, old_drafts_dir=settings.old_drafts_dir)
    assert "approval was cancelled" in outcome.email_refresh
    assert rec["workflow_status"] == m.DRAFT_READY and rec["approval_hash"] == ""
    assert "I am writing to you because" in rec["email_draft"]  # your text is kept
    assert ck.problems(rec) and "edited_text" in ck.load_checks(rec)
    assert not settings.old_drafts_dir.exists() or not list(settings.old_drafts_dir.iterdir())


def test_without_a_folder_for_old_emails_nothing_is_discarded(profile, today):
    rec = drafted(profile, today)
    text = rec["email_draft"]
    verify_record(rec, web_for(rec), today)
    assert rec["email_draft"] == text and rec["workflow_status"] == m.DRAFT_READY
