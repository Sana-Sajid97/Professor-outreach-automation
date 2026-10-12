"""Per-check verification: profile, email, research, papers, program page and funding (offline, with sample pages)."""

from __future__ import annotations

import pytest

from src import checks as ck
from src import models as m
from src.drafting import build_draft, can_draft
from src.errors import UserFacingError
from src.evidence import load_snapshot
from src.http_client import FetchResult
from src.page_facts import funding_evidence, funding_level, page_blocks, program_facts
from src.publications import check_publication
from src.verify import verify_record

from .conftest import make_record

PROFILE = """<html><body><nav><a href="/funding">Funding</a></nav>
<h1>Jamie Testperson, PhD</h1><p>Associate Professor of Nutrition</p>
<h2>Research interests</h2><ul><li>Household food insecurity</li><li>Maternal diet quality during pregnancy</li></ul>
<p>I am recruiting one PhD student for Fall 2027 with a graduate research assistantship (stipend and tuition waiver).</p>
<p><a href="mailto:jamie.testperson@testing.edu">Email</a></p></body></html>"""
PROGRAM = """<h1>PhD in Nutrition</h1><p>Applications for Fall 2027 entry are due December 15, 2026.</p>
<p>We do not admit new students in the spring semester.</p><p>A minimum IELTS score of 6.5 overall is required.</p>
<p>All admitted PhD students receive an assistantship with a stipend and a tuition waiver.</p>"""
CROSSREF_OK = {"message": {"title": ["Food insecurity and diet quality in pregnancy"],
                           "author": [{"given": "Ana", "family": "Coauthor"}, {"given": "Jamie", "family": "Testperson"}],
                           "issued": {"date-parts": [[2025, 3]]}}}


class StubWeb:
    """Pages for client.get and official API answers for client.get_json (shaped like the documented responses)."""

    def __init__(self, pages: dict, apis: dict | None = None):
        self.pages, self.apis, self.api_calls = pages, apis or {}, []

    def get(self, url, use_cache=True):
        if url in self.pages:
            return FetchResult(url, True, 200, self.pages[url], final_url=url)
        return FetchResult(url, False, 404, error="Page not found (404).")

    def get_json(self, url, params=None, method="GET", json_body=None):
        self.api_calls.append((url, params))
        for prefix, (status, data) in self.apis.items():
            if url.startswith(prefix):
                return status, data, ""
        return 404, None, "not found"


def fresh(**overrides):
    base = dict(institutional_email="", email_source_url="", email_verification="", verification_status="not_verified",
                workflow_status="needs_verification")
    base.update(overrides)
    return make_record(**base)


def test_full_verification_records_every_check(tmp_path, profile, today):
    rec = fresh()
    web = StubWeb({rec["faculty_profile_url"]: PROFILE, rec["program_url"]: PROGRAM}, {"https://api.crossref.org/works/": (200, CROSSREF_OK)})
    outcome = verify_record(rec, web, today, evidence_dir=tmp_path, applicant_ielts=6.5)
    checks = ck.load_checks(rec)
    assert outcome.status == m.VER_VERIFIED and rec["workflow_status"] == m.VERIFIED
    assert {n: checks[n]["status"] for n in ck.CHECK_ORDER} == {
        "profile": "passed", "email": "passed", "research": "passed", "publication": "passed",
        "program": "failed",  # the record says Spring is open, but the official page says no spring entry
        "funding": "confirmed",
    }
    assert checks["research"]["unsupported"] == ["SNAP program evaluation"]
    assert checks["program"]["items"]["ielts"]["status"] == "passed"
    assert "December" in checks["program"]["items"]["deadlines"]["detail"] or "Dec" in checks["program"]["items"]["deadlines"]["detail"]
    assert {e["kind"] for e in checks["funding"]["evidence"]} >= {"open_position", "program_guarantee"}
    assert "Funding: confirmed on an official page" in rec["checks_summary"] and rec["funding_level"] == "confirmed"
    assert load_snapshot(tmp_path, rec["faculty_profile_url"])[0].startswith("Jamie Testperson")  # evidence kept
    body = build_draft(rec, profile, today).body
    assert "SNAP" not in body  # not on the official page, so never presented as their research
    assert "Food insecurity and diet quality in pregnancy" in body  # the checked paper may be mentioned
    assert ck.problems(rec) and "Program" in ck.problems(rec)[0]  # approval will need 'approve anyway'


def test_profile_alone_is_never_verified(profile, today):
    page = PROFILE.replace("Household food insecurity", "Sports nutrition").replace("Maternal diet quality during pregnancy", "Exercise physiology")
    rec = fresh()
    outcome = verify_record(rec, StubWeb({rec["faculty_profile_url"]: page}), today)
    assert outcome.status == m.VER_PARTIAL and rec["workflow_status"] == m.NEEDS_VERIFICATION
    assert ck.status_of(ck.load_checks(rec), "research") == ck.FAILED
    ok, reason = can_draft(rec, today, 0)
    assert not ok
    assert "--check research" in rec["next_action"]


def test_your_own_confirmation_counts_and_is_kept(profile, today):
    page = PROFILE.replace("Household food insecurity", "Sports nutrition").replace("Maternal diet quality during pregnancy", "Exercise physiology")
    rec = fresh()
    web = StubWeb({rec["faculty_profile_url"]: page})
    verify_record(rec, web, today)
    with pytest.raises(UserFacingError):
        ck.confirm_check(rec, "research", "https://www.linkedin.com/in/jt", today)  # must be the official page
    ck.confirm_check(rec, "research", rec["faculty_profile_url"], today, note="lab page lists food insecurity work")
    assert rec["verification_status"] == m.VER_VERIFIED and rec["workflow_status"] == m.VERIFIED
    assert "confirmed by you" in rec["checks_summary"]
    verify_record(rec, web, today)  # an automatic re-check never overwrites what you confirmed
    entry = ck.get_check(ck.load_checks(rec), "research")
    assert entry["status"] == ck.CONFIRMED and entry["auto_result"].startswith("failed")
    assert can_draft(rec, today, 0)[0]


def test_paper_is_only_mentioned_when_its_check_passed(profile, today):
    wrong = {"message": {"title": ["Soil carbon in alpine meadows"], "author": [{"family": "Testperson"}]}}
    rec = fresh()
    web = StubWeb({rec["faculty_profile_url"]: PROFILE}, {"https://api.crossref.org/works/": (200, wrong)})
    verify_record(rec, web, today)
    pub = ck.get_check(ck.load_checks(rec), "publication")
    assert pub["status"] == ck.FAILED and "different paper" in pub["detail"]
    assert "Food insecurity and diet quality in pregnancy" not in build_draft(rec, profile, today).body


@pytest.mark.parametrize(
    "answer,expected",
    [
        ({"message": {"title": ["Food insecurity and diet quality in pregnancy"], "author": [{"family": "Someone"}]}}, "failed"),
        ({"message": {"title": ["Food insecurity and diet quality in pregnancy"], "author": [{"family": "Testperson"}]}}, "passed"),
    ],
)
def test_crossref_author_check(answer, expected):
    result = check_publication(StubWeb({}, {"https://api.crossref.org/works/": (200, answer)}),
                               "Food insecurity and diet quality in pregnancy", "https://doi.org/10.1234/abc", "Jamie Testperson")
    assert result["status"] == expected


def test_pubmed_and_unlinked_papers():
    pubmed = {"result": {"12345678": {"title": "Food insecurity and diet quality in pregnancy.", "authors": [{"name": "Testperson J"}], "pubdate": "2024 Jan"}}}
    web = StubWeb({}, {"https://eutils.ncbi.nlm.nih.gov/": (200, pubmed)})
    result = check_publication(web, "Food insecurity and diet quality in pregnancy", "https://pubmed.ncbi.nlm.nih.gov/12345678/", "Jamie Testperson")
    assert result["status"] == "passed" and result["year"] == "2024"
    assert web.api_calls[0][1]["id"] == "12345678"
    assert check_publication(web, "A paper", "https://journal.example/article/1", "Jamie Testperson")["status"] == "not_checked"
    assert check_publication(StubWeb({}, {"https://api.crossref.org/works/": (404, None)}), "A paper", "https://doi.org/10.1234/x", "J T")["status"] == "failed"


@pytest.mark.parametrize(
    "sentence,kind",
    [
        ("All admitted PhD students receive a graduate assistantship that includes a stipend and tuition waiver.", "program_guarantee"),
        ("I am recruiting a PhD student for Fall 2027; the position is funded by a research assistantship.", "open_position"),
        ("Graduate assistantships may be available on a competitive basis.", "general"),
        ("Funding is not guaranteed.", "general"),
        ("MS students are self-funded.", "no_funding"),
        ("The department does not offer assistantships to MS students.", "no_funding"),
    ],
)
def test_funding_sentences_are_graded(sentence, kind):
    evidence = funding_evidence([sentence], "https://u.edu/p")
    assert evidence and evidence[0]["kind"] == kind
    assert evidence[0]["quote"].startswith(sentence[:20])


def test_funding_levels():
    assert funding_level([{"kind": "general"}, {"kind": "no_funding"}]) == "possible"
    assert funding_level([{"kind": "no_funding"}]) == "not_available"
    assert funding_level([]) == "not_verified"
    assert funding_level([{"kind": "active_grant"}]) == "possible"


def test_program_facts_flag_what_cannot_be_confirmed():
    facts = program_facts(page_blocks("<p>PhD in Nutrition. International applicants need IELTS 7.0 overall.</p>"), 6.5, "PhD in Nutrition")
    assert facts["status"] == "failed" and "7.0" in facts["items"]["ielts"]["detail"]
    facts = program_facts(page_blocks("<p>PhD in Nutrition. Applications for Fall 2027 are due January 15.</p>"), 6.5, "PhD in Nutrition")
    assert facts["items"]["ielts"]["status"] == "warning"  # not stated on the page: flagged, not assumed
    assert facts["items"]["spring"]["status"] == "warning"  # not mentioned
    assert facts["items"]["fall"]["status"] == "passed"
    assert facts["status"] == "passed"


def test_hand_edited_drafts_are_never_overwritten(today):
    rec = make_record(workflow_status=m.DRAFT_READY, email_draft="My own words", draft_edited_on="2026-10-12")
    ok, reason = can_draft(rec, today, 0, force=True)
    assert not ok and "edited this email by hand" in reason
    assert can_draft(rec, today, 0, force=True, discard_edits=True)[0]


def test_nih_grant_is_possible_funding_not_a_position(today):
    from src.cli import _add_grant_evidence

    rec = make_record()
    _add_grant_evidence(rec, "NIH RePORTER: Active NIH project R01DK1 \"Food insecurity\" - https://reporter.nih.gov/project-details/111", today)
    entry = ck.get_check(ck.load_checks(rec), "funding")
    assert entry["status"] == ck.FUNDING_POSSIBLE and entry["evidence"][0]["kind"] == "active_grant"


def test_old_verified_records_are_flagged_for_a_recheck():
    rec = make_record()  # verified under the earlier rules, no checks recorded
    assert any("earlier, simpler rules" in a for a in ck.attention(rec))
    assert ck.summary_text({}).startswith("Profile: not checked yet")
