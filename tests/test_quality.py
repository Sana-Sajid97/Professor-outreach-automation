"""Validation, deduplication and fit scoring."""

from __future__ import annotations

from src import models as m
from src.dedupe import dedupe_records
from src.scoring import score_record
from src.validate import ielts_minimum, validate_record

from .conftest import make_record


def _fields(issues, severity=None):
    return {(i.field, i.severity) for i in issues if severity is None or i.severity == severity}


def test_valid_record_has_no_errors(record, today):
    issues = validate_record(record, today, applicant_ielts=6.5)
    assert not [i for i in issues if i.severity == "error"], issues


def test_validation_catches_problems(today):
    bad = make_record(
        professor_name="",
        institutional_email="not-an-email",
        faculty_profile_url="ftp://nope",
        workflow_status="draft_ready",
        email_draft="Dear [Professor name], {{x}}",
        email_subject="Hi",
        eligibility_notes="IELTS 7.0 required",
    )
    issues = validate_record(bad, today, applicant_ielts=6.5)
    errors = _fields(issues, "error")
    assert ("professor_name", "error") in errors
    assert ("institutional_email", "error") in errors
    assert ("faculty_profile_url", "error") in errors
    assert ("email_draft", "error") in errors  # placeholder left in draft
    assert any("IELTS 7" in i.message for i in issues)


def test_validation_flags_domain_mismatch_and_generic_and_stale(today):
    rec = make_record(institutional_email="info@other.edu", date_checked="2025-01-01")
    issues = validate_record(rec, today)
    messages = " ".join(i.message for i in issues)
    assert "does not match" in messages
    assert "general office address" in messages
    assert "Re-verify" in messages


def test_unverified_advanced_record_is_an_error(today):
    rec = make_record(verification_status="not_verified", workflow_status="verified")
    assert ("verification_status", "error") in _fields(validate_record(rec, today))


def test_suppressed_email_still_active_is_error(record, today):
    issues = validate_record(record, today, suppressed_emails={"jamie.testperson@testing.edu"})
    assert ("workflow_status", "error") in _fields(issues)


def test_contact_discouraged_warning(today):
    rec = make_record(eligibility_notes="The department discourages contacting faculty before the second round.")
    assert any("Do not cold-email" in i.message for i in validate_record(rec, today))


def test_ielts_parser():
    assert ielts_minimum("Minimum IELTS 6.5 overall") == 6.5
    assert ielts_minimum("IELTS: 7") == 7.0
    assert ielts_minimum("TOEFL 80") is None


def test_dedupe_by_email_url_and_name():
    a = make_record(record_id="R0001", workflow_status="sent", notes="first")
    b = make_record(record_id="R0002", faculty_profile_url="https://other.testing.edu/x", lab_url="https://lab.testing.edu", notes="second")
    c = make_record(record_id="R0003", institutional_email="", faculty_profile_url="https://www.nutrition.testing.edu/people/jamie-testperson/")
    d = make_record(record_id="R0004", institutional_email="", faculty_profile_url="", professor_name="Jamie Q. Testperson, PhD")
    e = make_record(record_id="R0005", professor_name="Someone Else", institutional_email="se@testing.edu", faculty_profile_url="https://nutrition.testing.edu/se")
    result = dedupe_records([a, b, c, d, e])
    assert len(result.records) == 2
    kept = [r for r in result.records if r["professor_name"].startswith("Jamie")][0]
    assert kept["record_id"] == "R0001"  # the record furthest along (sent) is kept
    assert kept["workflow_status"] == m.SENT
    assert kept["lab_url"] == "https://lab.testing.edu"  # blanks filled from duplicates
    assert "Merged duplicate" in kept["notes"]


def test_dedupe_flags_conflicting_emails():
    a = make_record(record_id="R0001")
    b = make_record(record_id="R0002", institutional_email="jtestperson@testing.edu")  # same URL, different email
    result = dedupe_records([a, b])
    assert len(result.records) == 1
    assert result.merges[0].conflicts


def test_possible_duplicates_are_not_merged():
    a = make_record(record_id="R0001", professor_name="Katherine Smith", institutional_email="ks@testing.edu", faculty_profile_url="https://testing.edu/ks")
    b = make_record(record_id="R0002", professor_name="Kathrine Smith", institutional_email="ksmith@testing.edu", faculty_profile_url="https://testing.edu/ksmith")
    result = dedupe_records([a, b])
    assert len(result.records) == 2
    assert result.possible
    assert "possible duplicate" in result.records[1]["duplicate_of"]


def test_score_full_marks(record, profile, today):
    result = score_record(record, profile, today)
    assert result.topic == 3
    assert result.background == 2
    assert result.program == 2
    assert result.funding == 2
    assert result.publication == 1
    assert result.total == 10
    assert "not an admission probability" in result.explanation


def test_score_missing_evidence_gives_no_points(profile, today):
    rec = make_record(
        research_interests="plant breeding and soil science",
        relevant_publication_1="",
        publication_1_year="",
        recruiting_evidence="Not verified",
        funding_or_assistantship_evidence="",
        spring_2027_status="Not verified",
        fall_2027_status="",
        eligibility_notes="",
        verification_status="not_verified",
    )
    result = score_record(rec, profile, today)
    assert result.total == 0
    assert result.confidence == "low"


def test_score_ielts_above_applicant_gets_no_eligibility_point(record, profile, today):
    rec = dict(record, eligibility_notes="Minimum IELTS 7.0 overall")
    result = score_record(rec, profile, today)
    assert result.program == 1
    assert "ABOVE" in result.explanation


def test_score_passed_deadlines(record, profile, today):
    rec = dict(record, spring_2027_status="Deadline was 2026-09-01", fall_2027_status="No 2027 intake (closed)")
    assert score_record(rec, profile, today).program == 1  # only the IELTS point remains
