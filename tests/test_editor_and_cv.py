"""The email editor (a real local server in a background thread), hand edits, and the CV checks."""

from __future__ import annotations

import http.client
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from src import checks as ck
from src import models as m
from src.cv_check import inspect_cv, set_cv
from src.drafting import apply_draft, build_draft, draft_hash
from src.editing import apply_edit
from src.evidence import save_snapshot
from src.review_server import EditorApp, editor_is_open, make_server
from src.storage import load_records, save_records
from src.tracker import read_log

from .conftest import make_pdf, make_record, write_profile


def drafted(profile, today, **overrides):
    rec = make_record(**overrides)
    apply_draft(rec, build_draft(rec, profile, today), today)
    return rec


@pytest.fixture
def editor(settings, profile, today):
    write_profile(settings, profile)
    save_records(settings.tracker_path, [drafted(profile, today)])
    server, app = make_server(settings, port=0, today_fn=lambda: today)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield app, base
    server.shutdown()
    server.server_close()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def post(base, path, fields):
    data = urllib.parse.urlencode(fields).encode()
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        return opener.open(urllib.request.Request(base + path, data=data, method="POST")).status
    except urllib.error.HTTPError as exc:
        return exc.code


def get(base, path):
    try:
        with urllib.request.urlopen(base + path) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), resp.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), exc.headers


def test_editor_needs_the_secret_link_and_a_local_address(editor):
    app, base = editor
    assert get(base, "/")[0] == 403
    assert get(base, "/?t=wrong")[0] == 403
    status, page, headers = get(base, f"/?t={app.token}")
    assert status == 200 and "Edit your emails" in page and "R0001" in page
    assert headers["Referrer-Policy"] == "no-referrer"  # the secret link never reaches university websites
    host, port = base.replace("http://", "").split(":")
    conn = http.client.HTTPConnection(host, int(port))
    conn.request("GET", f"/?t={app.token}", headers={"Host": "evil.example:80"})
    assert conn.getresponse().status == 403  # protects against other websites reaching the editor
    assert post(base, "/save", {"t": "wrong", "rid": "R0001"}) == 403


def test_edits_are_saved_logged_and_kept(editor, settings):
    app, base = editor
    rec = load_records(settings.tracker_path)[0]
    new_body = rec["email_draft"].replace("I am writing because", "I am writing to you because") + "\r\n"
    assert post(base, "/save", {"t": app.token, "rid": "R0001", "to": rec["institutional_email"], "email_source_url": rec["email_source_url"],
                                "subject": "My own subject line", "body": new_body}) == 303
    saved = load_records(settings.tracker_path)[0]
    assert saved["email_subject"] == "My own subject line"
    assert "I am writing to you because" in saved["email_draft"] and "\r" not in saved["email_draft"]
    assert saved["draft_edited_on"] and saved["workflow_status"] == m.DRAFT_READY
    assert any(r["action"] == "draft_edited" for r in read_log(settings))
    status, page, _ = get(base, f"/?t={app.token}")
    assert "My own subject line" in page and "Saved: subject, email text." in page  # still there when the page is reopened


def test_refused_save_keeps_what_you_typed(editor, settings):
    app, base = editor
    rec = load_records(settings.tracker_path)[0]
    before = rec["email_draft"]
    post(base, "/save", {"t": app.token, "rid": "R0001", "to": rec["institutional_email"], "email_source_url": "",
                         "subject": "Hello", "body": "Dear [Professor name], my carefully written text."})
    assert load_records(settings.tracker_path)[0]["email_draft"] == before  # nothing saved
    page = get(base, f"/?t={app.token}")[1]
    assert "my carefully written text" in page and "Replace the placeholder" in page


def test_changing_the_recipient_needs_the_official_page(settings, profile, today):
    rec = drafted(profile, today)
    result = apply_edit(rec, "new.address@testing.edu", rec["email_subject"], rec["email_draft"], today)
    assert not result.ok and "official university" in result.errors[0]
    result = apply_edit(rec, "new.address@testing.edu", rec["email_subject"], rec["email_draft"], today,
                        email_source_url="https://nutrition.testing.edu/people/jamie-testperson")
    assert result.ok and rec["institutional_email"] == "new.address@testing.edu"
    assert rec["email_verification"] == m.EMAIL_CONFIRMED_MANUALLY
    assert ck.status_of(ck.load_checks(rec), "email") == ck.CONFIRMED
    assert not apply_edit(rec, "nutrition@testing.edu", rec["email_subject"], rec["email_draft"], today, "https://testing.edu/x").ok
    assert not apply_edit(rec, "someone@gmail.com", rec["email_subject"], rec["email_draft"], today, "https://testing.edu/x").ok


def test_editing_an_approved_email_cancels_the_approval(profile, today):
    rec = drafted(profile, today)
    rec["workflow_status"] = m.APPROVED
    rec["approval_hash"] = draft_hash(rec)
    result = apply_edit(rec, rec["institutional_email"], rec["email_subject"] + " (revised)", rec["email_draft"], today)
    assert result.ok and result.approval_cancelled
    assert rec["workflow_status"] == m.DRAFT_READY and rec["approval_hash"] == ""
    sent = make_record(workflow_status=m.SENT, email_draft="x", email_subject="y")
    assert not apply_edit(sent, sent["institutional_email"], "z", "text", today).ok  # sent emails cannot be edited


def test_new_claims_in_an_edit_are_flagged(tmp_path, profile, today):
    rec = drafted(profile, today)
    save_snapshot(tmp_path, rec["faculty_profile_url"], "Research interests\nHousehold food insecurity\nMaternal diet quality during pregnancy", today)
    body = rec["email_draft"].replace("your research on", "your research on gut microbiome studies and", 1)
    result = apply_edit(rec, rec["institutional_email"], rec["email_subject"], body, today, evidence_dir=tmp_path)
    entry = ck.get_check(ck.load_checks(rec), "edited_text")
    assert result.ok and entry["status"] == ck.WARNING and "microbiome" in entry["detail"]
    assert any("microbiome" in w for w in result.warnings)


def test_confirming_a_check_in_the_editor(editor, settings):
    app, base = editor
    rec = load_records(settings.tracker_path)[0]
    assert post(base, "/confirm", {"t": app.token, "rid": "R0001", "check": "program", "source_url": rec["program_url"],
                                   "note": "Fall 2027 deadline Dec 15; IELTS 6.5"}) == 303
    entry = ck.get_check(ck.load_checks(load_records(settings.tracker_path)[0]), "program")
    assert entry["status"] == ck.CONFIRMED and "IELTS 6.5" in entry["detail"]
    post(base, "/confirm", {"t": app.token, "rid": "R0001", "check": "program", "source_url": "https://www.google.com/x"})
    assert "official (.edu) page" in get(base, f"/?t={app.token}")[1]  # a non-official page is refused, with the reason shown


def test_editor_never_overwrites_a_newer_tracker(settings, profile, today):
    write_profile(settings, profile)
    save_records(settings.tracker_path, [drafted(profile, today)])
    app = EditorApp(settings, lambda: today)
    records, stamp = app._load()
    other = load_records(settings.tracker_path)
    other[0]["notes"] = "changed in another window"
    save_records(settings.tracker_path, other)
    with pytest.raises(Exception, match="changed by another window"):
        app._save(records, stamp)


def test_cv_is_checked_and_served(editor, settings, profile, tmp_path):
    app, base = editor
    assert get(base, f"/cv?t={app.token}")[0] == 404
    assert "No CV is set up yet" in get(base, f"/?t={app.token}")[1]
    pdf = make_pdf(tmp_path / "incoming" / "Test_Applicant_CV.pdf", ["Test Applicant", "applicant@example.com"])
    dest = set_cv(settings, pdf)
    assert dest.parent == settings.private_dir / "cv" and "CV_ATTACHMENT" in (settings.root / ".env").read_text()
    report = inspect_cv(settings, profile)
    assert report.ok_to_attach and report.pages == 1 and report.name_found and report.email_found and not report.warnings
    status, body, headers = get(base, f"/cv?t={app.token}")
    assert status == 200 and headers["Content-Type"] == "application/pdf"
    assert report.fingerprint in get(base, f"/?t={app.token}")[1]


def test_cv_problems_are_explained(settings, profile, tmp_path):
    wrong = make_pdf(tmp_path / "Portfolio (1) (1).pdf", ["Someone Else", "other@example.com"], pages=6)
    set_cv(settings, wrong)
    report = inspect_cv(settings, profile)
    assert not report.ok_to_attach and "does not contain your name" in report.problems[0]
    assert any("6 pages" in w for w in report.warnings) and any("looks informal" in w for w in report.warnings)
    (settings.private_dir / "cv" / "notes.txt").write_text("not a pdf")
    with pytest.raises(Exception):
        set_cv(settings, settings.private_dir / "cv" / "notes.txt")


def test_editor_lock_is_cleaned_up_when_the_editor_is_gone(settings):
    settings.ensure_folders()
    (settings.workspace_dir / "editor.lock").write_text('{"port": 1, "token": "x"}')
    assert editor_is_open(settings) is False
    assert not (settings.workspace_dir / "editor.lock").exists()


def test_correcting_research_interests_is_checked_at_once(settings, profile, today):
    from src.verify import verify_record

    from .test_verification_checks import PROFILE, StubWeb

    write_profile(settings, profile)
    rec = make_record(research_interests="sports nutrition; exercise physiology", institutional_email="", email_source_url="",
                      email_verification="", verification_status="not_verified", workflow_status="needs_verification")
    verify_record(rec, StubWeb({rec["faculty_profile_url"]: PROFILE}), today, evidence_dir=settings.evidence_dir)
    assert rec["verification_status"] == m.VER_PARTIAL
    save_records(settings.tracker_path, [rec])
    app = EditorApp(settings, lambda: today)
    assert "Correct the research interests" in app.render()
    app.set_research({"rid": "R0001", "research_interests": "household food insecurity; maternal diet quality during pregnancy"})
    saved = load_records(settings.tracker_path)[0]
    assert ck.status_of(ck.load_checks(saved), "research") == ck.PASSED
    assert saved["verification_status"] == m.VER_VERIFIED and saved["workflow_status"] == m.VERIFIED
    assert "Run 4_run_pipeline.bat" in app.render()


def test_approving_waits_until_the_editor_is_closed(editor, settings, monkeypatch, capsys):
    import json

    from src import cli

    app, base = editor
    port = int(base.rsplit(":", 1)[1])
    (settings.workspace_dir / "editor.lock").write_text(json.dumps({"port": port, "token": app.token}))
    assert editor_is_open(settings)
    monkeypatch.setenv("OUTREACH_ROOT", str(settings.root))
    assert cli.main(["approve"]) == 1
    assert "editor is still open" in capsys.readouterr().err
