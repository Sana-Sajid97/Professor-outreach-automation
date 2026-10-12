"""The CV through approval and sending: the right file, approved, unchanged, and really attached."""

from __future__ import annotations

import pytest

from src import checks as ck
from src import models as m
from src.cv_check import inspect_cv, set_cv
from src.drafting import apply_draft, build_draft
from src.gmail_client import raw_attachments
from src.sending import approve, mark_sent, send
from src.suppression import SuppressionList
from src.tracker import read_log

from .conftest import make_pdf, make_record

QUIET = {"print_fn": lambda *a: None}


def answers(*values):
    it = iter(values)
    return lambda prompt="": next(it)


def drafted(profile, today, **overrides):
    rec = make_record(**overrides)
    apply_draft(rec, build_draft(rec, profile, today), today)
    return rec


@pytest.fixture
def cv(settings, tmp_path):
    return set_cv(settings, make_pdf(tmp_path / "src_cv" / "Test_Applicant_CV.pdf", ["Test Applicant", "applicant@example.com"]))


class _Run:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class Gmail:
    """Behaves like the Gmail API calls the tool uses (drafts.create / drafts.get / messages.send)."""

    def __init__(self, keep_attachment=True):
        self.drafts_made, self.sent, self.keep = [], [], keep_attachment

    def users(self):
        return self

    def messages(self):
        return self

    def drafts(self):
        return self

    def send(self, userId, body):
        return _Run(lambda: (self.sent.append(body["raw"]), {"id": f"m{len(self.sent)}"})[1])

    def create(self, userId, body):
        return _Run(lambda: (self.drafts_made.append(body["message"]["raw"]), {"id": f"d{len(self.drafts_made)}"})[1])

    def get(self, userId, id, format):
        raw = self.drafts_made[int(id[1:]) - 1]
        parts = [{"filename": name, "body": {"size": size}} for name, size, _ in raw_attachments(raw)] if self.keep else []
        return _Run(lambda: {"message": {"payload": {"parts": [{"filename": "", "body": {"size": 120}}] + parts}}})


def test_an_email_that_says_cv_attached_cannot_be_approved_without_a_cv(settings, profile, today):
    rec = drafted(profile, today)
    assert approve([rec], settings, SuppressionList(), today, input_fn=answers("yes"), profile=profile, **QUIET) == 0
    assert rec["workflow_status"] == m.DRAFT_READY


def test_approval_records_the_cv_and_a_changed_cv_stops_sending(settings, profile, today, cv, tmp_path):
    rec = drafted(profile, today)
    shown = []
    assert approve([rec], settings, SuppressionList(), today, input_fn=answers("yes"), profile=profile, print_fn=shown.append) == 1
    assert "ATTACHMENT: Test_Applicant_CV.pdf" in "\n".join(shown)
    assert rec["cv_fingerprint"] == inspect_cv(settings, profile).fingerprint
    assert any("cv=Test_Applicant_CV.pdf" in r["details"] for r in read_log(settings) if r["action"] == "approved")
    make_pdf(cv, ["Test Applicant", "applicant@example.com", "A newer line"])  # the CV file is replaced after approval
    report = send([rec], settings, SuppressionList(), today, method="manual", profile=profile, **QUIET)
    assert report.skipped and "CV file changed after you approved" in report.skipped[0][1]


def test_failed_checks_need_the_words_approve_anyway(settings, profile, today, cv):
    rec = drafted(profile, today)
    ck.set_check(rec, "program", ck.FAILED, today, detail="Official page: IELTS 7.0 minimum, but you have 6.5.")
    assert approve([rec], settings, SuppressionList(), today, input_fn=answers("yes"), profile=profile, **QUIET) == 0
    assert approve([rec], settings, SuppressionList(), today, input_fn=answers("approve anyway"), profile=profile, **QUIET) == 1
    assert any("approved anyway" in r["details"] for r in read_log(settings) if r["action"] == "approved")


def test_gmail_draft_is_read_back_to_confirm_the_cv(settings, profile, today, cv):
    rec = drafted(profile, today)
    approve([rec], settings, SuppressionList(), today, input_fn=answers("yes"), profile=profile, **QUIET)
    gmail = Gmail()
    report = send([rec], settings, SuppressionList(), today, method="gmail-drafts", gmail_service=gmail,
                  input_fn=answers("DRAFT 1"), profile=profile, **QUIET)
    assert report.drafted == ["R0001"] and "Gmail confirms" in report.attachment_notes[0][1]
    rec2 = drafted(profile, today, record_id="R0002", institutional_email="other.person@testing.edu", professor_name="Other Person")
    approve([rec2], settings, SuppressionList(), today, input_fn=answers("yes"), profile=profile, **QUIET)
    report = send([rec2], settings, SuppressionList(), today, method="gmail-drafts", gmail_service=Gmail(keep_attachment=False),
                  input_fn=answers("DRAFT 1"), profile=profile, **QUIET)
    assert report.attachment_notes[0][1].startswith("WARNING")


def test_sent_message_contains_exactly_the_approved_cv(settings, profile, today, cv):
    settings.email_mode = "send_enabled"
    rec = drafted(profile, today)
    approve([rec], settings, SuppressionList(), today, input_fn=answers("yes"), profile=profile, **QUIET)
    gmail = Gmail()
    report = send([rec], settings, SuppressionList(), today, method="gmail-api", gmail_service=gmail,
                  input_fn=answers("SEND 1"), profile=profile, sleep=lambda s: None, **QUIET)
    assert report.sent == ["R0001"]
    [(name, size, sha)] = raw_attachments(gmail.sent[0])
    assert name == "Test_Applicant_CV.pdf"
    assert sha == rec["cv_fingerprint"] == inspect_cv(settings, profile).fingerprint


def test_outbox_shows_the_cv_and_mark_sent_names_it(settings, profile, today, cv):
    rec = drafted(profile, today)
    approve([rec], settings, SuppressionList(), today, input_fn=answers("yes"), profile=profile, **QUIET)
    report = send([rec], settings, SuppressionList(), today, method="manual", profile=profile, **QUIET)
    page = report.outbox_path.read_text(encoding="utf-8")
    assert "Attach this CV to every email" in page and "Test_Applicant_CV.pdf" in page and "Open the CV to check it" in page
    prompts = []

    def remember(prompt=""):
        prompts.append(prompt)
        return "yes"

    assert mark_sent([rec], ["R0001"], settings, today, input_fn=remember, profile=profile, **QUIET) == 1
    assert "with your CV (Test_Applicant_CV.pdf) attached" in prompts[0]


def test_an_email_without_a_cv_mention_needs_no_cv(settings, profile, today):
    profile = dict(profile, email_preferences=dict(profile["email_preferences"], mention_cv_attached=False))
    rec = drafted(profile, today)
    assert "attached" not in rec["email_draft"].lower()
    assert approve([rec], settings, SuppressionList(), today, input_fn=answers("yes"), profile=profile, **QUIET) == 1
    assert rec["cv_fingerprint"] == ""
