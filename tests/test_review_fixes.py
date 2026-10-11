"""Regression tests for the issues found in the adversarial code review (one block per finding)."""

from __future__ import annotations

import importlib.util
import shutil
from datetime import date, timedelta

import pytest

from src import models as m
from src.dedupe import dedupe_records
from src.discovery import nih_reporter
from src.drafting import apply_draft, build_draft, build_follow_up, can_draft
from src.errors import UserFacingError
from src.http_client import PoliteClient
from src.review import render_review_page
from src.scoring import _intake_available
from src.sending import approve, mark_sent, reset_approval_for_import, send
from src.storage import load_records, read_csv_rows, save_records
from src.suppression import SuppressionList
from src.textutil import normalize_tracker_dates, parse_iso
from src.topics import match_topics
from src.tracker import already_sent, log_event, reconcile_with_log, set_status
from src.validate import validate_all
from src.verify import NO_MATCH, STRONG, SURNAME_ONLY, choose_email, email_matches_person

from .conftest import ROOT, FakeResponse, FakeSession, make_record, write_profile

QUIET = {"print_fn": lambda *a: None}


def answers(*values):
    it = iter(values)
    return lambda prompt="": next(it)


def drafted(profile, today, **overrides):
    rec = make_record(**overrides)
    apply_draft(rec, build_draft(rec, profile, today), today)
    return rec


def approved(settings, profile, today, **overrides):
    rec = drafted(profile, today, **overrides)
    assert approve([rec], settings, SuppressionList(), today, input_fn=answers("yes"), **QUIET) == 1
    return rec


# ------------------------------------------------------------------ 1. CSV quoting
def test_csv_reader_keeps_quotes_commas_newlines_and_detects_semicolons(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text(
        'record_id,professor_name,notes\nR1,"Smith, Jane","She said ""yes"", then\nleft"\nR2,Kim,plain\n', encoding="utf-8"
    )
    rows, _ = read_csv_rows(path)
    assert rows[0]["professor_name"] == "Smith, Jane"
    assert rows[0]["notes"] == 'She said "yes", then\nleft'
    assert rows[1]["notes"] == "plain"
    path.write_text("record_id;professor_name\nR1;Jane Smith\n", encoding="utf-8")
    rows, _ = read_csv_rows(path)
    assert rows[0]["professor_name"] == "Jane Smith"


# ------------------------------------------------------------------ 2. strict email matching
@pytest.mark.parametrize(
    "email,name,expected",
    [
        ("jane.smith@u.edu", "Jane Smith", STRONG),
        ("jsmith@u.edu", "Jane Smith", STRONG),
        ("smithj@u.edu", "Jane Smith", STRONG),
        ("john.smith@u.edu", "Jane Smith", NO_MATCH),  # same surname, different person
        ("jkim@u.edu", "Hyun Kim", NO_MATCH),  # initial contradicts the first name
        ("mgarcia@u.edu", "Lucia Garcia", NO_MATCH),
        ("smith@u.edu", "Jane Smith", SURNAME_ONLY),
        ("pchandlerlaney@u.edu", "Paula Chandler Laney", STRONG),
        ("perez-escamilla@u.edu", "Rafael Pérez-Escamilla", SURNAME_ONLY),
        ("nutrition@u.edu", "Jane Smith", NO_MATCH),
    ],
)
def test_email_matches_person(email, name, expected):
    assert email_matches_person(email, name) == expected


def test_choose_email_is_strict_on_shared_pages():
    emails = [("jane.smith@u.edu", "mailto"), ("john.smith@u.edu", "mailto")]
    assert choose_email(emails, "Jane Smith", "https://u.edu/people")[0] == "jane.smith@u.edu"
    only_surname = [("smith@u.edu", "mailto")]
    assert choose_email(only_surname, "Jane Smith", "https://u.edu/people/smith", own_profile=True)[0] == "smith@u.edu"
    assert choose_email(only_surname, "Jane Smith", "https://u.edu/people", own_profile=False)[0] == ""
    two = [("jsmith@u.edu", "mailto"), ("jane.smith@u.edu", "mailto")]
    assert choose_email(two, "Jane Smith", "https://u.edu/p")[0] == ""  # two candidates: a human decides


# ------------------------------------------------------------------ 6. dedupe never merges different people
def test_shared_roster_url_and_shared_email_do_not_merge_different_people():
    roster = "https://nutrition.testing.edu/faculty"
    a = make_record(record_id="R0001", professor_name="Jane Smith", institutional_email="jane.smith@testing.edu", faculty_profile_url=roster)
    b = make_record(record_id="R0002", professor_name="Omar Haddad", institutional_email="ohaddad@testing.edu", faculty_profile_url=roster)
    c = make_record(record_id="R0003", professor_name="Li Wei", institutional_email="nutrition@testing.edu", faculty_profile_url="https://x.edu/a")
    d = make_record(record_id="R0004", professor_name="Ana Ruiz", institutional_email="nutrition@testing.edu", faculty_profile_url="https://x.edu/b")
    result = dedupe_records([a, b, c, d])
    assert len(result.records) == 4
    assert result.shared  # reported for a human to fix


def test_same_person_with_hyphenated_surname_merges():
    a = make_record(record_id="R0001", professor_name="Ana Perez-Lopez", institutional_email="aperezlopez@testing.edu", faculty_profile_url="https://x.edu/a")
    b = make_record(record_id="R0002", professor_name="Ana Perez Lopez", institutional_email="aperezlopez@testing.edu", faculty_profile_url="https://x.edu/b")
    assert len(dedupe_records([a, b]).records) == 1


def test_validator_flags_one_email_on_two_active_records(today):
    a = make_record(record_id="R0001")
    b = make_record(record_id="R0002", professor_name="Someone Else")
    errors = [i for i in validate_all([a, b], today) if i.field == "institutional_email" and i.severity == "error"]
    assert {i.record_id for i in errors} == {"R0001", "R0002"}


# ------------------------------------------------------------------ 7. "Not verified" is not "No"
def test_seed_builder_treats_not_verified_contact_policy_as_unknown():
    spec = importlib.util.spec_from_file_location("build_seed", ROOT / "scripts" / "build_seed.py")
    build_seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_seed)
    unknown = build_seed.program_to_professor_fields({"advisor_contact_expected": "Not verified", "spring_2027_admission": "Not verified"})
    assert "notes" not in unknown and "spring_2027_status" not in unknown
    no = build_seed.program_to_professor_fields({"advisor_contact_expected": "No - do not contact faculty", "spring_2027_admission": "No"})
    assert "do not cold-email" in no["notes"] and no["spring_2027_status"].startswith("No spring")


# ------------------------------------------------------------------ 3. send buttons only for approved, sendable emails
def test_review_page_shows_send_buttons_only_for_sendable_approved_drafts(profile, today):
    ready = drafted(profile, today, record_id="R0001")
    ok = drafted(profile, today, record_id="R0002", institutional_email="other.person@testing.edu", professor_name="Other Person")
    ok["workflow_status"] = m.APPROVED
    page = render_review_page([ready, ok], "t", today)
    assert "mail.google.com" not in page  # review page: no buttons at all
    page = render_review_page([ready, ok], "t", today, sendable_ids={"R0002"})
    assert page.count("mail.google.com") == 1 and "Not approved yet" in page


def test_pipeline_review_page_never_has_send_buttons(settings, profile, today):
    from src.run_pipeline import run

    write_profile(settings, profile)
    run(settings, input_file=ROOT / "data" / "sample" / "sample_professors.csv", today=today, **QUIET)
    assert "mail.google.com" not in (settings.exports_dir / "review_latest.html").read_text(encoding="utf-8")


# ------------------------------------------------------------------ 4. follow-ups need approval; mark-sent needs approval
def test_follow_up_is_a_draft_that_must_be_approved(settings, profile, today):
    rec = approved(settings, profile, today)
    assert mark_sent([rec], ["R0001"], settings, today, input_fn=answers("yes"), **QUIET) == 1
    later = today + timedelta(days=settings.follow_up_days)
    from src.tracker import refresh_follow_ups

    refresh_follow_ups([rec], later, settings)
    assert rec["workflow_status"] == m.FOLLOW_UP_DUE
    assert mark_sent([rec], ["R0001"], settings, later, input_fn=answers("yes"), **QUIET) == 0  # not approved: refused
    draft = build_follow_up(rec, profile, later)
    rec["email_subject"], rec["email_draft"] = draft.subject, draft.body
    set_status(rec, m.DRAFT_READY, later, settings)
    assert approve([rec], settings, SuppressionList(), later, input_fn=answers("yes"), **QUIET) == 1
    assert mark_sent([rec], ["R0001"], settings, later, input_fn=answers("yes"), **QUIET) == 1
    assert rec["follow_up_count"] == "1" and rec["follow_up_date"] == ""
    from src.tracker import read_log

    assert [r["action"] for r in read_log(settings) if r["action"].endswith("sent")] == ["sent", "follow_up_sent"]


def test_mark_sent_refuses_unapproved_edited_or_suppressed(settings, profile, today):
    rec = drafted(profile, today)
    assert mark_sent([rec], ["R0001"], settings, today, input_fn=answers("yes"), **QUIET) == 0
    rec = approved(settings, profile, today)
    rec["email_draft"] += "\nP.S. edited after approval"
    assert mark_sent([rec], ["R0001"], settings, today, input_fn=answers("yes"), **QUIET) == 0
    rec = approved(settings, profile, today, record_id="R0002", institutional_email="b.person@testing.edu", professor_name="B Person")
    sup = SuppressionList()
    sup.add(rec, m.OPTED_OUT, today)
    assert mark_sent([rec], ["R0002"], settings, today, input_fn=answers("yes"), suppression=sup, **QUIET) == 0


def test_first_email_is_never_redrafted_for_someone_already_contacted(today):
    rec = make_record(workflow_status=m.DRAFT_READY, last_contact_date="2026-09-01")
    ok, reason = can_draft(rec, today, 4, force=True)
    assert not ok and "already contacted" in reason


def test_cli_followups_draft_goes_back_to_draft_ready(tmp_path, monkeypatch, profile):
    from src import cli
    from src.config import load_settings

    monkeypatch.setenv("OUTREACH_ROOT", str(tmp_path))
    settings = load_settings()
    settings.ensure_folders()
    write_profile(settings, profile)
    rec = make_record(workflow_status=m.FOLLOW_UP_DUE, last_contact_date="2026-09-20", follow_up_date="2026-09-30",
                      email_subject="Prospective PhD student", email_draft="Hello", approval_hash="abc")
    save_records(settings.tracker_path, [rec])
    assert cli.main(["followups", "--draft"]) == 0
    saved = load_records(settings.tracker_path)[0]
    assert saved["workflow_status"] == m.DRAFT_READY and saved["approval_hash"] == ""
    assert saved["email_subject"].startswith("Re: ")


# ------------------------------------------------------------------ 5. never send twice
def test_outreach_log_blocks_a_second_send_and_restores_status(settings, profile, today):
    settings.email_mode = "send_enabled"
    rec = approved(settings, profile, today)
    log_event(settings, rec, "sent", f"recorded by user; subject={rec['email_subject']}")
    assert already_sent(settings, rec["institutional_email"], rec["email_subject"])
    assert not already_sent(settings, rec["institutional_email"], rec["email_subject"] + " (2)")  # exact subject only
    report = send([rec], settings, SuppressionList(), today, method="gmail-api", gmail_service=object(), **QUIET)
    assert report.skipped and "already sent" in report.skipped[0][1]
    assert mark_sent([rec], ["R0001"], settings, today, input_fn=answers("yes"), **QUIET) == 0
    assert reconcile_with_log([rec], settings) == ["R0001"]
    assert rec["workflow_status"] == m.SENT


class _FakeGmail:
    def __init__(self):
        self.sent, self.drafts_made = [], []

    def users(self):
        return self

    def messages(self):
        return self

    def drafts(self):
        return self

    def send(self, userId, body):
        return _Run(lambda: (self.sent.append(body), {"id": f"m{len(self.sent)}"})[1])

    def create(self, userId, body):
        return _Run(lambda: (self.drafts_made.append(body), {"id": f"d{len(self.drafts_made)}"})[1])


class _Run:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


def test_save_failure_before_sending_sends_nothing(settings, profile, today):
    settings.email_mode = "send_enabled"
    rec = approved(settings, profile, today)
    gmail = _FakeGmail()

    def locked():
        raise UserFacingError("Close tracker.csv in Excel first.")

    with pytest.raises(UserFacingError):
        send([rec], settings, SuppressionList(), today, method="gmail-api", gmail_service=gmail, input_fn=answers("SEND 1"),
             save_fn=locked, sleep=lambda s: None, **QUIET)
    assert gmail.sent == [] and rec["workflow_status"] == m.APPROVED


def test_each_send_is_saved_at_once(settings, profile, today):
    settings.email_mode = "send_enabled"
    recs = [approved(settings, profile, today, record_id=f"R000{i}", institutional_email=f"p{i}.person@testing.edu",
                     professor_name=f"P{i} Person") for i in (1, 2)]
    saved_states = []
    send(recs, settings, SuppressionList(), today, method="gmail-api", gmail_service=_FakeGmail(), input_fn=answers("SEND 2"),
         save_fn=lambda: saved_states.append([r["workflow_status"] for r in recs]), sleep=lambda s: None, **QUIET)
    assert saved_states == [[m.APPROVED, m.APPROVED], [m.SENT, m.APPROVED], [m.SENT, m.SENT]]


def test_gmail_drafts_are_not_created_twice(settings, profile, today):
    rec = approved(settings, profile, today)
    gmail = _FakeGmail()
    send([rec], settings, SuppressionList(), today, method="gmail-drafts", gmail_service=gmail, input_fn=answers("DRAFT 1"), **QUIET)
    report = send([rec], settings, SuppressionList(), today, method="gmail-drafts", gmail_service=gmail, input_fn=answers("DRAFT 1"), **QUIET)
    assert len(gmail.drafts_made) == 1 and "already exists" in report.skipped[0][1]


def test_imported_rows_never_carry_approvals(tmp_path, monkeypatch, profile, today):
    rec = make_record(workflow_status=m.APPROVED, approval_hash="abc", approved_on="2026-10-01")
    reset_approval_for_import(rec)
    assert rec["workflow_status"] == m.DRAFT_READY and rec["approval_hash"] == "" and rec["approved_on"] == ""
    from src import cli
    from src.config import load_settings

    monkeypatch.setenv("OUTREACH_ROOT", str(tmp_path))
    settings = load_settings()
    settings.ensure_folders()
    write_profile(settings, profile)
    shutil.copytree(ROOT / "data" / "sample", tmp_path / "data" / "sample")
    assert cli.main(["init", "--sample"]) == 0
    incoming = tmp_path / "incoming.csv"
    save_records(incoming, [make_record(record_id="", professor_name="New Person", institutional_email="new.person@testing.edu",
                                        faculty_profile_url="https://x.edu/new", workflow_status=m.APPROVED, approval_hash="forged")])
    assert cli.main(["import", "--file", str(incoming)]) == 0
    new = [r for r in load_records(settings.tracker_path) if r["professor_name"] == "New Person"][0]
    assert new["workflow_status"] == m.DRAFT_READY and new["approval_hash"] == ""


# ------------------------------------------------------------------ 8. robots.txt errors and redirects
def _client(routes):
    return PoliteClient("TestAgent/1.0", delay_seconds=1, session=FakeSession(routes), sleep=lambda s: None)


def test_unreachable_robots_txt_means_disallow():
    client = _client({"https://a.edu/robots.txt": ConnectionError("down"), "https://a.edu/p": FakeResponse(200, "hello")})
    result = client.get("https://a.edu/p")
    assert not result.ok and result.blocked_by_robots


def test_redirects_are_checked_against_robots_on_every_hop():
    client = _client({
        "https://a.edu/robots.txt": FakeResponse(404, ""),
        "https://a.edu/p": FakeResponse(301, "", headers={"Location": "https://b.edu/private/p"}),
        "https://b.edu/robots.txt": FakeResponse(200, "User-agent: *\nDisallow: /private/"),
        "https://b.edu/private/p": FakeResponse(200, "secret"),
    })
    result = client.get("https://a.edu/p")
    assert not result.ok and result.blocked_by_robots
    assert "https://b.edu/private/p" not in client.session.calls  # never fetched


def test_allowed_redirect_is_followed_and_loops_stop():
    client = _client({
        "https://a.edu/robots.txt": FakeResponse(404, ""),
        "https://a.edu/old": FakeResponse(302, "", headers={"Location": "/new"}),
        "https://a.edu/new": FakeResponse(200, "<p>Jane Smith</p>"),
        "https://a.edu/loop": FakeResponse(302, "", headers={"Location": "/loop"}),
    })
    result = client.get("https://a.edu/old")
    assert result.ok and result.final_url == "https://a.edu/new"
    looped = client.get("https://a.edu/loop")
    assert not looped.ok and "redirect" in looped.error.lower()


# ------------------------------------------------------------------ 9. NIH matching
def _nih(first, last, org):
    return {"results": [{"appl_id": 1, "project_num": "R01X", "project_end_date": "2029-01-01",
                         "organization": {"org_name": org}, "principal_investigators": [{"first_name": first, "last_name": last}]}]}


@pytest.mark.parametrize(
    "first,last,org,name,university,expected",
    [
        ("JENNIFER", "SMITH", "UNIVERSITY OF WASHINGTON", "Jennifer Smith", "University of Washington", 1),
        ("JOHN", "SMITH", "UNIVERSITY OF WASHINGTON", "Jennifer Smith", "University of Washington", 0),  # same initial only
        ("CHRISTOPHER", "LEE", "PURDUE UNIVERSITY", "Chris Lee", "Purdue University", 1),
        ("JENNIFER", "SMITH", "UNIVERSITY OF WASHINGTON", "Jennifer Smith", "Washington State University", 0),
        ("JENNIFER", "SMITH", "UNIV OF MICHIGAN AT ANN ARBOR", "Jennifer Smith", "University of Michigan", 1),
        ("RAFAEL", "PEREZ-ESCAMILLA", "YALE UNIVERSITY", "Rafael Pérez-Escamilla", "Yale University", 1),
        ("", "SMITH", "UNIVERSITY OF WASHINGTON", "Jennifer Smith", "University of Washington", 0),
    ],
)
def test_nih_matching_is_strict(first, last, org, name, university, expected, today):
    assert len(nih_reporter.matching_projects(_nih(first, last, org), name, university, today)) == expected


# ------------------------------------------------------------------ 10. childhood-obesity evidence
def test_child_weight_words_are_weak_evidence_only():
    assert "childhood_obesity" not in match_topics("infant birth weight and maternal diet")
    weak = match_topics("obesity among preschool children in rural counties")["childhood_obesity"]
    assert not weak.is_strong and weak.weak
    assert "childhood_obesity" not in match_topics("adult obesity; children's literacy programs elsewhere in the county library system")
    assert match_topics("prevention of childhood obesity")["childhood_obesity"].is_strong


def test_subject_never_names_a_weakly_evidenced_topic(profile, today):
    rec = make_record(research_interests="obesity among preschool children; family meals",
                      relevant_publication_1="", publication_1_year="")
    draft = build_draft(rec, profile, today)
    assert "childhood obesity" not in draft.subject


# ------------------------------------------------------------------ 11. no invented research; papers must fit
def test_openalex_leads_have_no_invented_research_interests(today):
    from src.discovery import openalex

    people = {"A1": {"name": "Pat Senior", "author_id": "https://openalex.org/A1", "institutions": {"Test University": 1},
                     "works": [{"title": "Food insecurity in pregnancy", "doi": "", "year": 2025}], "topics": {"food_insecurity"}}}
    rec = openalex.to_records(people, today)[0]
    assert rec["research_interests"] == "" and "food insecurity" in rec["notes"]


def test_unrelated_paper_is_not_mentioned(profile, today):
    rec = make_record(relevant_publication_1="Soil microbiome of alpine meadows", publication_1_year="2025")
    draft = build_draft(rec, profile, today)
    assert "Soil microbiome" not in draft.body


# ------------------------------------------------------------------ 12. dates after an Excel re-save
@pytest.mark.parametrize(
    "value,day_first,expected",
    [
        ("2026-10-21", None, date(2026, 10, 21)),
        ("21/10/2026", None, date(2026, 10, 21)),
        ("10/21/2026", None, date(2026, 10, 21)),
        ("05/06/2026", None, None),  # ambiguous: never guessed
        ("05/06/2026", True, date(2026, 6, 5)),
        ("10/21/26", None, date(2026, 10, 21)),
        ("21-Oct-2026", None, date(2026, 10, 21)),
        ("2026-10-21 00:00:00", None, date(2026, 10, 21)),
    ],
)
def test_parse_iso_reads_excel_dates(value, day_first, expected):
    assert parse_iso(value, day_first) == expected


def test_tracker_dates_are_repaired_on_load(tmp_path, settings, today):
    recs = [make_record(record_id="R0001", date_checked="21/10/2026", follow_up_date="05/11/2026"),
            make_record(record_id="R0002", date_checked="05/06/2026")]
    save_records(settings.tracker_path, recs)
    loaded = {r["record_id"]: r for r in load_records(settings.tracker_path)}
    assert loaded["R0001"]["date_checked"] == "2026-10-21"
    assert loaded["R0001"]["follow_up_date"] == "2026-11-05"  # day-first learned from 21/10/2026
    assert loaded["R0002"]["date_checked"] == "2026-06-05"
    alone = [make_record(date_checked="05/06/2026")]
    assert normalize_tracker_dates(alone) == [("R0001", "date_checked", "05/06/2026")]


def test_cli_set_and_note(tmp_path, monkeypatch, profile, capsys):
    from src import cli
    from src.config import load_settings

    monkeypatch.setenv("OUTREACH_ROOT", str(tmp_path))
    settings = load_settings()
    settings.ensure_folders()
    save_records(settings.tracker_path, [make_record(workflow_status=m.VERIFIED)])
    assert cli.main(["set", "--id", "R0001", "--field", "workflow_status", "--value", "sent"]) == 1
    assert cli.main(["set", "--id", "R0001", "--field", "faculty_profile_url", "--value", "not a url"]) == 1
    assert cli.main(["set", "--id", "R0001", "--field", "research_interests", "--value", "maternal nutrition"]) == 0
    assert cli.main(["set", "--id", "R0001", "--field", "faculty_profile_url", "--value", "https://x.edu/new"]) == 0
    assert cli.main(["note", "--id", "R0001", "--text", "Met at a webinar"]) == 0
    rec = load_records(settings.tracker_path)[0]
    assert rec["research_interests"] == "maternal nutrition"
    assert rec["workflow_status"] == m.NEEDS_VERIFICATION  # a new profile URL must be verified again
    assert "Met at a webinar" in rec["notes"]


# ------------------------------------------------------------------ 13. intake status text
@pytest.mark.parametrize(
    "text,intake,expected",
    [
        ("Spring deadline: Not verified - applications accepted year-round", "spring", None),
        ("Deadline (not yet posted)", "fall", None),
        ("No spring entry; apply by Dec 1 for Fall", "spring", False),
        ("not open for spring", "spring", False),
        ("reopened", "spring", None),  # whole words only
        ("Priority deadline passed; final deadline 2027-01-15", "spring", True),
        ("Spring deadline: October 1 standing deadline", "spring", False),  # 2026-10-01 has passed
        ("January 15 fall application deadline", "fall", True),  # 2027-01-15
        ("for Spring 2027 that was 2026-10-01 - PASSED as of 2026-10-11", "spring", False),  # research date ignored
        ("Likely closed for international applicants: international Oct 1 (department Nov 15)", "spring", False),
        ("Accepting - Spring 2027 final deadline 2026-11-15", "spring", True),
        ("deadline", "fall", None),
    ],
)
def test_intake_status_reading(text, intake, expected, today):
    assert _intake_available(text, today, intake) is expected


# ------------------------------------------------------------------ wording found on the real leads
def test_lab_names_and_job_titles_are_not_quoted_as_research(profile, today):
    rec = make_record(research_interests="Food Policy and Environmental Research Group (head); school meals for low-income children")
    body = build_draft(rec, profile, today).body
    assert "Research Group" not in body and "school meals for low-income children" in body
    rec = make_record(research_interests="Head Start obesity prevention")
    assert "Head Start obesity prevention" in build_draft(rec, profile, today).body  # a program, not a job title


def test_metabolic_label_follows_the_professors_own_words(profile, today):
    obesity = make_record(research_interests="maternal and child nutrition; obesity", relevant_publication_1="")
    draft = build_draft(obesity, profile, today)
    interest = draft.body.split("interest in ", 1)[1].split(".")[0] if "interest in " in draft.body else draft.body.split("particularly in ", 1)[1].split(".")[0]
    assert "diabetes" not in interest and "diabetes" not in draft.subject.lower()  # (her own CV line may still mention diabetes)
    assert "obesity" in interest
    diabetes = make_record(research_interests="type 2 diabetes prevention in rural adults", relevant_publication_1="")
    assert "diabetes prevention" in build_draft(diabetes, profile, today).subject


@pytest.mark.parametrize(
    "program,university,expected",
    [
        ("PhD in Nutritional Sciences (Graduate Program in Nutritional Sciences); the MS is self-funded, so the PhD is the assistantship route",
         "The Pennsylvania State University (University Park)", "PhD in Nutritional Sciences"),
        ("Probably Health Promotion Sciences MS/PhD (UConn) - not verified that she advises there", "University of Connecticut", ""),
        ("Not verified (adjunct in Psychology)", "X University", ""),
        ("Food Science, M.S. and Ph.D. (a listed specialization area)", "Clemson University", "M.S. and Ph.D. in Food Science"),
        ("PhD in Nutrition, UMass Amherst", "University of Massachusetts Amherst", "PhD in Nutrition"),
        ("PhD in Public Health (Social and Behavioral Sciences), Yale GSAS / Yale School of Public Health", "Yale University", "PhD in Public Health"),
        ("Graduate study in Nutrition, URI Department of Nutrition (program names not verified)", "University of Rhode Island", ""),
    ],
)
def test_program_names_in_emails_never_carry_research_notes(program, university, expected):
    from src.drafting import clean_program_name

    assert clean_program_name(program, university) == expected


@pytest.mark.parametrize(
    "program,expected",
    [
        ("PhD in Nutritional Sciences (MS is self-funded)", "PhD"),  # she needs funding: the PhD is the route
        ("Nutritional Sciences M.S. (Community track); Ph.D. requires a master's", "MS"),  # BS holders start with the MS
        ("Nutrition MS (or Nutrition Science PhD after an MS)", "MS"),
        ("MS / PhD in Nutrition", "MS or PhD"),
    ],
)
def test_degree_label_reads_funding_and_entry_notes(program, expected):
    from src.drafting import degree_label

    assert degree_label({"graduate_program": program}, {}) == expected


def test_email_names_a_clean_program(profile, today):
    rec = make_record(graduate_program="PhD in Nutritional Sciences (Graduate Program); the MS is self-funded, so the PhD is the route",
                      university="The Pennsylvania State University (University Park)")
    body = build_draft(rec, profile, today).body
    assert "apply to the PhD in Nutritional Sciences at The Pennsylvania State University for" in body
    assert "self-funded" not in body and "University Park" not in body


def test_placeholder_research_text_is_treated_as_missing(profile, today):
    rec = make_record(research_interests="Not captured in search results")
    ok, reason = can_draft(rec, today, 0)
    assert not ok and "no research interests" in reason
    errors = [i for i in validate_all([make_record(research_interests="Not verified (advisor on a thesis)", workflow_status=m.VERIFIED)], today)
              if i.field == "research_interests"]
    assert errors
    from src.scoring import score_record

    placeholder = score_record(make_record(research_interests="Not verified (obesity during pregnancy)", relevant_publication_1=""), profile, today)
    assert placeholder.topic == 0  # words inside a research note earn no topic points


def test_surname_only_email_needs_the_real_profile_page_not_a_redirect(today):
    from src.verify import verify_record

    page = '<html><body><h1>Jane Smith</h1><a href="mailto:smith@u.edu">Email</a></body></html>'
    direct = _client({"https://u.edu/robots.txt": FakeResponse(404, ""), "https://u.edu/people/jane-smith": FakeResponse(200, page)})
    rec = make_record(professor_name="Jane Smith", institutional_email="", email_source_url="", email_verification="",
                      faculty_profile_url="https://u.edu/people/jane-smith", verification_status=m.VER_NOT, workflow_status=m.NEEDS_VERIFICATION)
    verify_record(rec, direct, today)
    assert rec["institutional_email"] == "smith@u.edu"  # her own page: accepted (and flagged to double-check)
    moved = _client({
        "https://u.edu/robots.txt": FakeResponse(404, ""),
        "https://u.edu/people/jane-smith": FakeResponse(301, "", headers={"Location": "https://u.edu/directory"}),
        "https://u.edu/directory": FakeResponse(200, page),
    })
    rec = make_record(professor_name="Jane Smith", institutional_email="", email_source_url="", email_verification="",
                      faculty_profile_url="https://u.edu/people/jane-smith", verification_status=m.VER_NOT, workflow_status=m.NEEDS_VERIFICATION)
    verify_record(rec, moved, today)
    assert rec["institutional_email"] == ""  # the profile now redirects to a directory: surname-only is not enough
