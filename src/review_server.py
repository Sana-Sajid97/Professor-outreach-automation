"""The draft editor: change each email's recipient, subject and text in your browser and save it to your tracker.

It runs only on your own computer (http://127.0.0.1, on a random port) and needs the secret link it opens,
so no other computer or website can use it. Nothing is ever sent from it: approval and sending stay in
5_approve_drafts.bat. Keep its window open while you edit, and close it when you are done.

What it shows for each email: every verification check with its official link and quoted evidence, the CV
that will be attached, and a form to edit the email. Checks you have done yourself on an official page can
be recorded with "I checked this myself".
"""

from __future__ import annotations

import hmac
import html
import json
import re
import secrets
import socket
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from . import checks as ck
from . import models as m
from .config import Settings
from .errors import UserFacingError
from .review import CHECK_CSS, CSS, checks_html
from .storage import file_stamp, load_records, save_records
from .textutil import clean

MAX_POST_BYTES = 512 * 1024
LOCK_NAME = "editor.lock"

EDITOR_CSS = """
.top{display:grid;gap:6px}.notice{border-radius:8px;padding:8px 12px;margin:8px 0;font-size:14px}
.notice.ok{background:var(--okbg);color:var(--ok)}.notice.warn{background:var(--warnbg);color:var(--warn)}.notice.bad{background:var(--badbg);color:var(--bad)}
form.edit{display:grid;gap:10px;margin-top:10px}form.edit label{display:grid;gap:4px;font-size:14px;font-weight:600}
input[type=text],input[type=email],input[type=url],textarea{font:inherit;font-weight:400;width:100%;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
textarea{font:15px/1.5 Georgia,serif;min-height:22em}.pill{display:inline-block;border-radius:999px;padding:1px 10px;font-size:12px;border:1px solid var(--line)}
.pill.approved{border-color:var(--ok);color:var(--ok)}details.confirm{margin:4px 0 2px}details.confirm form{display:grid;gap:6px;margin:6px 0}
h2{font-size:18px;margin:24px 0 8px}h3{font-size:15px;margin:12px 0 4px}button:focus-visible,input:focus-visible,textarea:focus-visible,a:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
"""


def _today() -> date:
    return date.today()


class EditorApp:
    """Everything the editor does, separated from the web server so it can be tested directly."""

    def __init__(self, settings: Settings, today_fn=_today):
        self.settings = settings
        self.token = secrets.token_urlsafe(24)
        self.today_fn = today_fn
        self.notices: dict[str, list[tuple[str, str]]] = {}
        self.pending: dict[str, dict] = {}  # what you typed when a save was refused, so nothing you wrote is lost

    # ------------------------------------------------------------------ data
    def _load(self) -> tuple[list[dict], str | None]:
        path = self.settings.tracker_path
        stamp = file_stamp(path)
        return load_records(path), stamp

    def _save(self, records: list[dict], stamp: str | None) -> None:
        if file_stamp(self.settings.tracker_path) != stamp:
            raise UserFacingError("The tracker was changed by another window a moment ago. Nothing was saved: reload this page and try again.")
        save_records(self.settings.tracker_path, records, self.settings.backup_dir)

    def _profile(self) -> dict:
        from .profile import load_profile

        try:
            return load_profile(self.settings.profile_path) if self.settings.profile_path.exists() else {}
        except UserFacingError:
            return {}

    def _note(self, rid: str, kind: str, text: str) -> None:
        if text:
            self.notices.setdefault(rid, []).append((kind, text))

    # ------------------------------------------------------------------ actions
    def save_edit(self, form: dict) -> str:
        from .editing import apply_edit
        from .tracker import find_record, log_event

        rid = form.get("rid", "")
        typed = {k: form.get(k, "") for k in ("to", "email_source_url", "subject", "body")}
        try:
            records, stamp = self._load()
            record = find_record(records, rid)
            if record is None:
                self._note(rid, "bad", f"No record {rid} in the tracker.")
                return rid
            result = apply_edit(record, typed["to"], typed["subject"], typed["body"], self.today_fn(),
                                email_source_url=typed["email_source_url"], evidence_dir=self.settings.evidence_dir)
            if result.errors:
                self.pending[rid] = typed
                for error in result.errors:
                    self._note(rid, "bad", error)
                self._note(rid, "bad", "Not saved. Your text is still in the form: fix the problem above and press Save again.")
                return rid
            if result.changed:
                self._save(records, stamp)
                log_event(self.settings, record, "draft_edited", "changed: " + ", ".join(result.changed))
                self._note(rid, "ok", "Saved: " + ", ".join(result.changed) + ".")
            for warning in result.warnings:
                self._note(rid, "warn" if warning != "Nothing changed." else "ok", warning)
            self.pending.pop(rid, None)
        except UserFacingError as exc:
            self.pending[rid] = typed
            self._note(rid, "bad", str(exc))
        return rid

    def confirm(self, form: dict) -> str:
        from .tracker import find_record, log_event
        from .verify import confirm_email_manually

        rid, name = form.get("rid", ""), form.get("check", "")
        source, note = clean(form.get("source_url")), clean(form.get("note"))
        try:
            records, stamp = self._load()
            record = find_record(records, rid)
            if record is None:
                self._note(rid, "bad", f"No record {rid} in the tracker.")
                return rid
            if name == "email":
                confirm_email_manually(record, form.get("email", ""), source, self.today_fn())
            else:
                ck.confirm_check(record, name, source, self.today_fn(), note)
            self._save(records, stamp)
            log_event(self.settings, record, "check_confirmed", f"{name}: {source}")
            self._note(rid, "ok", f"{ck.LABELS.get(name, name)} marked as checked by you.")
            if record.get("verification_status") == m.VER_VERIFIED and record.get("workflow_status") == m.VERIFIED:
                self._note(rid, "ok", "All required checks are done. Run the pipeline (4_run_pipeline.bat) to write this email.")
        except UserFacingError as exc:
            self._note(rid, "bad", str(exc))
        return rid

    def set_research(self, form: dict) -> str:
        """You corrected the research interests from the official page: save and re-check them at once."""
        from .tracker import find_record, log_event
        from .verify import recheck_research_offline

        rid = form.get("rid", "")
        text = re.sub(r"\s+", " ", form.get("research_interests", "")).strip()
        try:
            if not text:
                raise UserFacingError("The research interests are empty. Copy them from the official profile.")
            if len(text) > 800:
                raise UserFacingError("That is too long: keep the main research areas, separated by semicolons (;).")
            records, stamp = self._load()
            record = find_record(records, rid)
            if record is None:
                raise UserFacingError(f"No record {rid} in the tracker.")
            record["research_interests"] = text
            status = recheck_research_offline(record, self.today_fn(), self.settings.evidence_dir)
            self._save(records, stamp)
            log_event(self.settings, record, "research_interests_set", text[:200])
            entry = ck.get_check(ck.load_checks(record), "research")
            kind = "ok" if status in ck.OK_STATUSES else "warn"
            self._note(rid, kind, "Research interests saved. " + entry.get("detail", ""))
            if record.get("verification_status") == m.VER_VERIFIED:
                self._note(rid, "ok", "All required checks are done. Run 4_run_pipeline.bat to write this email.")
        except UserFacingError as exc:
            self._note(rid, "bad", str(exc))
        return rid

    def cv_file(self) -> Path | None:
        from .cv_check import cv_path

        path = cv_path(self.settings)
        return path if path and path.exists() else None

    # ------------------------------------------------------------------ page
    def _confirm_form(self, record: dict):
        rid = clean(record.get("record_id"))
        defaults = {
            "profile": clean(record.get("faculty_profile_url")),
            "research": clean(record.get("faculty_profile_url")) or clean(record.get("lab_url")),
            "publication": clean(record.get("publication_1_url")),
            "program": clean(record.get("program_url")),
            "funding": clean(record.get("program_url")) or clean(record.get("faculty_profile_url")),
            "email": clean(record.get("email_source_url")) or clean(record.get("faculty_profile_url")),
        }
        hints = {
            "profile": "Open the profile. Is it this person, at this university, still on the faculty?",
            "research": "Does the research described in the email match what the official page says?",
            "publication": "Does the link open this paper, with this professor as an author?",
            "program": "On the official program page: degree, Spring/Fall 2027 entry, deadline and IELTS minimum.",
            "funding": "Did an official page (or the professor) say an assistantship is available? Note what it said.",
            "email": "Is this exact address written on the official page?",
        }

        def form(name: str, status: str) -> str:
            ok = status in ck.OK_STATUSES or (name == "funding" and status == ck.FUNDING_CONFIRMED)
            if ok or name not in defaults:
                return ""
            email_field = ""
            if name == "email":
                email_field = (f'<label>Email address <input type="email" name="email" required value="{html.escape(clean(record.get("institutional_email")), quote=True)}"></label>')
            return (
                '<details class="confirm"><summary>I checked this myself</summary>'
                f'<form method="post" action="/confirm" accept-charset="utf-8">'
                f'<input type="hidden" name="t" value="{self.token}"><input type="hidden" name="rid" value="{html.escape(rid, quote=True)}">'
                f'<input type="hidden" name="check" value="{name}"><p class="meta">{html.escape(hints[name])}</p>{email_field}'
                f'<label>Official page where you checked it <input type="url" name="source_url" required value="{html.escape(defaults[name], quote=True)}"></label>'
                f'<label>What you saw (optional) <input type="text" name="note" maxlength="300"></label>'
                '<button class="btn" type="submit">Mark as checked by me</button></form></details>'
            )

        return form

    def _notices_html(self, rid: str) -> str:
        items = self.notices.pop(rid, [])
        return "".join(f'<div class="notice {kind}" role="status">{html.escape(text)}</div>' for kind, text in items)

    def _cv_html(self) -> str:
        from .cv_check import inspect_cv

        report = inspect_cv(self.settings, self._profile())
        link = f' <a href="/cv?t={self.token}" target="_blank" rel="noopener noreferrer">Open the CV</a>' if report.ok_to_attach else ""
        kind = "ok" if report.ok_to_attach and not report.warnings else ("warn" if report.ok_to_attach else "bad")
        lines = [report.summary()] + report.warnings + report.problems
        return f'<div class="notice {kind}">' + "<br>".join(html.escape(x) for x in lines if x) + f"{link}</div>"

    def _draft_card(self, record: dict) -> str:
        rid = clean(record.get("record_id"))
        typed = self.pending.get(rid, {})
        to = typed.get("to", clean(record.get("institutional_email")))
        source = typed.get("email_source_url", clean(record.get("email_source_url")))
        subject = typed.get("subject", clean(record.get("email_subject")))
        body = typed.get("body", record.get("email_draft", "") or "")
        status = clean(record.get("workflow_status"))
        pill = '<span class="pill approved">Approved</span>' if status == m.APPROVED else '<span class="pill">Draft, not approved</span>'
        edited = f' <span class="meta">edited by you on {html.escape(clean(record.get("draft_edited_on")))}</span>' if clean(record.get("draft_edited_on")) else ""
        return f"""
<section class="card" id="{html.escape(rid)}">
  <div class="row"><div class="name">{html.escape(clean(record.get('professor_name')))}</div>
  <div>{pill} <span class="score">Fit {html.escape(clean(record.get('fit_score')) or '?')}/10</span></div></div>
  <div class="meta">{html.escape(clean(record.get('title')))} &middot; {html.escape(clean(record.get('university')))} &middot; {html.escape(rid)}{edited}</div>
  {self._notices_html(rid)}
  <h3>Checks</h3>{checks_html(record, self._confirm_form(record))}
  <form method="post" action="/save" accept-charset="utf-8" class="edit" data-edit>
    <input type="hidden" name="t" value="{self.token}"><input type="hidden" name="rid" value="{html.escape(rid, quote=True)}">
    <label>To <input type="email" name="to" id="to-{html.escape(rid)}" required value="{html.escape(to, quote=True)}"></label>
    <label>Official page where this address is shown (needed only if you change the address)
      <input type="url" name="email_source_url" id="src-{html.escape(rid)}" value="{html.escape(source, quote=True)}"></label>
    <label>Subject <input type="text" name="subject" id="subject-{html.escape(rid)}" maxlength="150" required value="{html.escape(subject, quote=True)}"></label>
    <label>Email text <textarea name="body" id="body-{html.escape(rid)}" rows="20" required>{html.escape(body)}</textarea></label>
    <div class="row"><span class="meta" data-count>&nbsp;</span><button class="btn primary" type="submit">Save changes</button></div>
    <p class="meta">Saved changes go straight into your tracker and stay there. Saving an approved email cancels its approval. Nothing is sent from this page.</p>
  </form>
</section>"""

    def _waiting_card(self, record: dict) -> str:
        rid = clean(record.get("record_id"))
        missing = ck.missing_for_verified(ck.load_checks(record))
        research_form = ""
        if ck.status_of(ck.load_checks(record), "research") not in ck.OK_STATUSES:
            research_form = (
                '<details class="confirm" open><summary>Correct the research interests</summary>'
                '<form method="post" action="/set-research" accept-charset="utf-8">'
                f'<input type="hidden" name="t" value="{self.token}"><input type="hidden" name="rid" value="{html.escape(rid, quote=True)}">'
                '<p class="meta">Copy the research areas from the official profile (see "The official page says" above), separated by semicolons. '
                'They are checked against the saved official page as soon as you save.</p>'
                f'<label>Research interests <textarea name="research_interests" rows="3" style="min-height:4em">{html.escape(clean(record.get("research_interests")))}</textarea></label>'
                '<button class="btn" type="submit">Save and check</button></form></details>'
            )
        return f"""
<section class="card" id="{html.escape(rid)}">
  <div class="row"><div class="name">{html.escape(clean(record.get('professor_name')))}</div>
  <div><span class="pill">Waiting for checks</span> <span class="score">Fit {html.escape(clean(record.get('fit_score')) or '?')}/10</span></div></div>
  <div class="meta">{html.escape(clean(record.get('title')))} &middot; {html.escape(clean(record.get('university')))} &middot; {html.escape(rid)}</div>
  {self._notices_html(rid)}
  <p class="meta">Still needed before an email can be written: {html.escape('; '.join(missing) or 'nothing')}.</p>
  {checks_html(record, self._confirm_form(record))}
  {research_form}
</section>"""

    def render(self) -> str:
        try:
            records, _ = self._load()
        except UserFacingError as exc:
            records = []
            self._note("_page", "bad", str(exc))
        drafts = [r for r in records if r.get("workflow_status") in {m.DRAFT_READY, m.APPROVED} and clean(r.get("email_draft"))]
        drafts.sort(key=lambda r: (r.get("workflow_status") == m.APPROVED, -float(r.get("fit_score") or 0)))
        waiting = [r for r in records if r.get("workflow_status") == m.NEEDS_VERIFICATION and r.get("verification_status") == m.VER_PARTIAL]
        waiting.sort(key=lambda r: -float(r.get("fit_score") or 0))
        draft_html = "".join(self._draft_card(r) for r in drafts) or "<p>No emails to edit yet. Verify professors (3_verify_professors.bat), then run 4_run_pipeline.bat.</p>"
        waiting_html = "".join(self._waiting_card(r) for r in waiting[:60])
        # Messages for professors no longer shown here (e.g. just became verified) appear at the top, with their name.
        names = {clean(r.get("record_id")): clean(r.get("professor_name")) for r in records}
        page_notices = self._notices_html("_page")
        for rid in [k for k in list(self.notices) if k != "_page"]:
            for kind, text in self.notices.pop(rid):
                page_notices += f'<div class="notice {kind}" role="status">{html.escape(rid)} {html.escape(names.get(rid, ""))}: {html.escape(text)}</div>'
        waiting_section = (f"<h2>Waiting for checks ({len(waiting)})</h2><p class='meta'>These professors are partly verified. "
                           "If you check the missing items yourself on the official pages, record them here; the pipeline can then write their email.</p>"
                           + waiting_html) if waiting else ""
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Edit your emails</title>
<style>{CSS}{CHECK_CSS}{EDITOR_CSS}</style></head>
<body><header><div class="top"><h1>Edit your emails</h1>
<div class="meta">{len(drafts)} email(s) &middot; changes are saved to your tracker when you press Save &middot; nothing is sent from this page.
When you are happy with them, close this window and run <strong>5_approve_drafts.bat</strong> to approve each email.</div>
<div><strong>CV to attach:</strong> {self._cv_html()}</div></div></header>
<main>{page_notices}<h2>Emails ({len(drafts)})</h2>{draft_html}{waiting_section}</main>
<script>
(function () {{
  var dirty = false;
  function words(text) {{ var t = text.trim(); return t ? t.split(/\\s+/).length : 0; }}
  document.querySelectorAll("form[data-edit]").forEach(function (form) {{
    var area = form.querySelector("textarea"), counter = form.querySelector("[data-count]");
    function update() {{ counter.textContent = words(area.value) + " words (aim for under 220 in the body)"; }}
    area.addEventListener("input", function () {{ dirty = true; update(); }});
    form.querySelectorAll("input").forEach(function (i) {{ i.addEventListener("input", function () {{ dirty = true; }}); }});
    form.addEventListener("submit", function () {{ dirty = false; }});
    update();
  }});
  window.addEventListener("beforeunload", function (e) {{ if (dirty) {{ e.preventDefault(); e.returnValue = ""; }} }});
}})();
</script></body></html>"""


def make_handler(app: EditorApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OutreachEditor/1.0"

        def log_message(self, fmt, *args):  # keep the window quiet
            pass

        def _host_ok(self) -> bool:
            port = self.server.server_address[1]
            return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}"}

        def _send(self, code: int, body: str | bytes, ctype: str = "text/plain; charset=utf-8", extra: dict | None = None) -> None:
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")  # the secret link never leaks to university sites
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _token_ok(self, token: str) -> bool:
            return hmac.compare_digest((token or "").encode(), app.token.encode())

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, "Forbidden.")
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            if parts.path == "/favicon.ico":
                return self._send(204, b"")
            if not self._token_ok(query.get("t", [""])[0]):
                return self._send(403, "This editor link is out of date. Close this tab and start the editor again (edit_drafts.bat).")
            if parts.path == "/":
                return self._send(200, app.render(), "text/html; charset=utf-8")
            if parts.path == "/ping":
                return self._send(200, "ok")
            if parts.path == "/cv":
                path = app.cv_file()
                if not path:
                    return self._send(404, "No CV is set up yet. Run:  outreach cv --set \"C:\\path\\to\\Your_CV.pdf\"")
                return self._send(200, path.read_bytes(), "application/pdf",
                                  {"Content-Disposition": f"inline; filename*=UTF-8''{quote(path.name)}"})
            return self._send(404, "Not found.")

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, "Forbidden.")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_POST_BYTES:
                return self._send(413, "That form is too large or empty.")
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True).items()}
            if not self._token_ok(form.get("t", "")):
                return self._send(403, "This editor link is out of date. Close this tab and start the editor again (edit_drafts.bat).")
            path = urlsplit(self.path).path
            if path == "/save":
                rid = app.save_edit(form)
            elif path == "/confirm":
                rid = app.confirm(form)
            elif path == "/set-research":
                rid = app.set_research(form)
            else:
                return self._send(404, "Not found.")
            anchor = quote(rid, safe="")
            return self._send(303, "", extra={"Location": f"/?t={app.token}#{anchor}"})

    return Handler


def make_server(settings: Settings, port: int = 0, today_fn=_today) -> tuple[HTTPServer, EditorApp]:
    app = EditorApp(settings, today_fn)
    server = HTTPServer(("127.0.0.1", port), make_handler(app))
    return server, app


def _lock_path(settings: Settings) -> Path:
    return settings.workspace_dir / LOCK_NAME


def editor_is_open(settings: Settings) -> bool:
    """True when an editor started from this folder is still running (checked by asking it)."""
    import urllib.request

    path = _lock_path(settings)
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        url = f"http://127.0.0.1:{int(info['port'])}/ping?t={info['token']}"
        with urllib.request.urlopen(url, timeout=1) as resp:  # noqa: S310 - local address only
            return resp.status == 200
    except (OSError, ValueError, KeyError):
        try:
            path.unlink()  # left over from an editor window that was closed
        except OSError:
            pass
        return False


def serve(settings: Settings, open_browser: bool = True, port: int = 0, print_fn=print) -> int:
    if not settings.tracker_path.exists():
        raise UserFacingError("Your tracker is empty. Start it first (2_import_profile.bat or: python -m src.cli init).")
    server, app = make_server(settings, port)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/?t={app.token}"
    lock = _lock_path(settings)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"port": actual_port, "token": app.token, "started": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    print_fn("The email editor is open in your browser. If it did not open, copy this link into your browser:")
    print_fn(f"  {url}")
    print_fn("Keep this window open while you edit. Close it (or press Ctrl+C) when you are done.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        try:
            lock.unlink()
        except OSError:
            pass
    print_fn("Editor closed. Your saved changes are in the tracker.")
    return 0


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
