"""Build a self-contained HTML page for reviewing drafts (opens in any browser, works offline).

Each draft shows the recipient, subject, body, fit explanation and evidence links,
plus buttons that open a pre-filled email in Gmail or in the default mail app.
Nothing is sent from this page: you review, attach your CV, and press Send yourself.
"""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path
from urllib.parse import quote

from . import models as m
from .textutil import clean, is_valid_url, split_multi

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2330;--muted:#5b6474;--line:#dde1e8;--accent:#2f5597;--warn:#9a5b00;--warnbg:#fff4e0;--ok:#1f7a3a;--okbg:#e7f4ec;--bad:#b42318;--badbg:#fdecea}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d2128;--ink:#e8ebf0;--muted:#a3abb8;--line:#333a45;--accent:#8fb0ee;--warn:#ffc46b;--warnbg:#3a2c12;--ok:#6fd38f;--okbg:#14301f;--bad:#ff8a80;--badbg:#3a1a19}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
header{padding:20px 16px;border-bottom:1px solid var(--line);background:var(--card)}h1{margin:0 0 4px;font-size:22px}
main{max-width:980px;margin:0 auto;padding:16px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:0 0 16px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;justify-content:space-between}.name{font-size:18px;font-weight:600}
.meta{color:var(--muted);font-size:13px}.badge{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:1px 10px;font-size:12px;margin-right:4px}
.score{font-weight:700;color:var(--accent)}pre{white-space:pre-wrap;word-wrap:break-word;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:12px;font:14px/1.5 Georgia,serif;color:var(--ink)}
.warn{background:var(--warnbg);color:var(--warn);border-radius:8px;padding:8px 12px;margin:8px 0;font-size:14px}
.btn{display:inline-block;padding:8px 14px;border-radius:8px;border:1px solid var(--accent);color:var(--accent);text-decoration:none;margin:4px 6px 0 0;font-size:14px;background:transparent;cursor:pointer}
.btn.primary{background:var(--accent);color:var(--card)}a{color:var(--accent)}ul{margin:6px 0 0 18px;padding:0}li{margin:2px 0}
details summary{cursor:pointer;color:var(--muted);font-size:13px}.checklist label{display:block;font-size:14px;margin:3px 0}
"""


CHECK_CSS = """
.checks{list-style:none;margin:8px 0;padding:0;display:grid;gap:4px}.checks>li{border-left:4px solid var(--line);padding:4px 10px;font-size:14px}
.checks>li.ck-ok{border-color:var(--ok)}.checks>li.ck-warn{border-color:var(--warn)}.checks>li.ck-bad{border-color:var(--bad)}.checks>li.ck-muted{border-color:var(--line)}
.checks .st{font-weight:700}
.checks .ck-ok .st{color:var(--ok)}.checks .ck-warn .st{color:var(--warn)}.checks .ck-bad .st{color:var(--bad)}.checks .ck-muted .st{color:var(--muted)}
.checks blockquote{margin:4px 0 4px 8px;padding:2px 8px;border-left:2px solid var(--line);color:var(--muted);font-size:13px}
.checks ul{margin:2px 0 2px 18px}
"""


def _check_class(name: str, status: str) -> str:
    from . import checks as ck

    if name == "funding":
        return "ck-" + {ck.FUNDING_CONFIRMED: "ok", ck.CONFIRMED: "ok", ck.FUNDING_POSSIBLE: "warn", ck.FUNDING_NOT_AVAILABLE: "bad"}.get(status, "muted")
    return "ck-" + {ck.PASSED: "ok", ck.CONFIRMED: "ok", ck.WARNING: "warn", ck.FAILED: "bad"}.get(status, "muted")


def _quote(text: str) -> str:
    return f"<blockquote>{html.escape(text)}</blockquote>" if clean(text) else ""


def checks_html(record: dict, confirm_form=None) -> str:
    """Every check with its result, official link and quoted evidence.
    confirm_form(name) may return extra HTML (the editor's "I checked this myself" form)."""
    from . import checks as ck

    checks = ck.load_checks(record)
    names = ck.CHECK_ORDER + (["edited_text"] if "edited_text" in checks else [])
    rows = []
    for name in names:
        entry = checks.get(name) or {}
        status = entry.get("status", ck.NOT_CHECKED)
        word = ck.FUNDING_WORDS.get(status, status) if name == "funding" else ck.STATUS_WORDS.get(status, status)
        parts = [f'<span class="st">{html.escape(word)}</span>']
        if entry.get("detail"):
            parts.append(html.escape(entry["detail"]))
        if entry.get("url") and is_valid_url(entry["url"]):
            parts.append(_link(entry["url"], "official source"))
        if entry.get("checked_on"):
            parts.append(f'<span class="meta">({html.escape(entry["checked_on"])})</span>')
        extra = []
        if name == "research":
            quotes = entry.get("quotes") or {}
            for phrase in entry.get("supported") or []:
                extra.append(f"<li>Found: \u201c{html.escape(phrase)}\u201d{_quote(quotes.get(phrase, ''))}</li>")
            for phrase in (entry.get("partly") or []) + (entry.get("unsupported") or []):
                extra.append(f"<li>Not found on the official page (left out of the email): \u201c{html.escape(phrase)}\u201d</li>")
            if entry.get("excerpt"):
                extra.append(f"<li>The official page says:{_quote(entry['excerpt'])}</li>")
        elif name == "publication":
            for item in entry.get("items") or []:
                link = _link(item["url"], "link") if is_valid_url(item.get("url", "")) else ""
                extra.append(f"<li>Paper {item.get('n')}: {html.escape(item.get('title', ''))} \u2014 {html.escape(item.get('detail', ''))} {link}</li>")
        elif name == "program":
            labels = {"degree": "Degree", "spring": "Spring entry", "fall": "Fall entry", "deadlines": "Deadlines", "ielts": "IELTS", "requirements": "Requirements"}
            for key, label in labels.items():
                item = (entry.get("items") or {}).get(key)
                if item:
                    word_i = ck.STATUS_WORDS.get(item.get("status"), item.get("status", ""))
                    extra.append(f'<li class="{_check_class(key, item.get("status", ""))}"><strong>{label}</strong> ({html.escape(word_i)}): '
                                 f"{html.escape(item.get('detail', ''))}{_quote(item.get('quote', ''))}</li>")
        elif name == "funding":
            from .page_facts import KIND_WORDS

            for ev in entry.get("evidence") or []:
                link = _link(ev["url"], "source") if is_valid_url(ev.get("url", "")) else ""
                extra.append(f"<li>{html.escape(KIND_WORDS.get(ev.get('kind'), ''))} {link}{_quote(ev.get('quote', ''))}</li>")
            earlier = clean(record.get("funding_or_assistantship_evidence"))
            if earlier:
                extra.append(f"<li>From earlier research (not checked on an official page): {html.escape(earlier[:400])}</li>")
        if entry.get("auto_result"):
            extra.append(f"<li>The latest automatic check said: {html.escape(entry['auto_result'])}</li>")
        detail_html = f"<details><summary>Evidence</summary><ul>{''.join(extra)}</ul></details>" if extra else ""
        form = confirm_form(name, status) if confirm_form else ""
        rows.append(f'<li class="{_check_class(name, status)}"><strong>{html.escape(ck.LABELS[name])}:</strong> {" ".join(parts)}{detail_html}{form}</li>')
    legacy = ""
    if not checks and clean(record.get("verification_status")) == m.VER_VERIFIED:
        legacy = '<li class="ck-warn"><span class="st">needs a look</span> Marked verified under the earlier, simpler rules (email only). Run verify again to check the research, papers, program and funding.</li>'
    return f'<ul class="checks">{legacy}{"".join(rows)}</ul>'


def gmail_compose_url(to: str, subject: str, body: str, account: str = "") -> str:
    base = "https://mail.google.com/mail/?view=cm&fs=1"
    auth = f"&authuser={quote(account)}" if account else ""
    return f"{base}{auth}&to={quote(to)}&su={quote(subject)}&body={quote(body)}"


def mailto_url(to: str, subject: str, body: str) -> str:
    return f"mailto:{quote(to, safe='@')}?subject={quote(subject)}&body={quote(body.replace(chr(10), chr(13) + chr(10)))}"


def _link(url: str, label: str | None = None) -> str:
    url = clean(url)
    if not is_valid_url(url):
        return html.escape(url)
    return f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">{html.escape(label or url)}</a>'


def render_review_page(
    records: list[dict],
    title: str,
    today: date,
    sender_account: str = "",
    warnings_by_id: dict[str, list[str]] | None = None,
    sendable_ids: set[str] | None = None,
    cv_report=None,
) -> str:
    """sendable_ids: records allowed to show send buttons (approved and passing every send check).
    None means a review-only page: no send buttons at all."""
    warnings_by_id = warnings_by_id or {}
    sendable_ids = sendable_ids or set()
    cards = []
    for r in records:
        rid = clean(r.get("record_id"))
        to = clean(r.get("institutional_email"))
        subject = clean(r.get("email_subject"))
        body = r.get("email_draft", "") or ""
        evidence = []
        for label, field in (
            ("Official profile", "faculty_profile_url"),
            ("Where the email was found", "email_source_url"),
            ("Lab", "lab_url"),
            ("Program", "program_url"),
        ):
            if clean(r.get(field)):
                evidence.append(f"<li>{label}: {_link(r.get(field))}</li>")
        for n in (1, 2):
            pub = clean(r.get(f"relevant_publication_{n}"))
            if pub:
                year = clean(r.get(f"publication_{n}_year"))
                url = clean(r.get(f"publication_{n}_url"))
                text = html.escape(pub + (f" ({year})" if year else ""))
                evidence.append(f"<li>Publication: {_link(url, pub + (f' ({year})' if year else '')) if url else text}</li>")
        for url in split_multi(r.get("source_urls", ""))[:6]:
            evidence.append(f"<li>Source: {_link(url)}</li>")
        warn_html = "".join(f'<div class="warn">{html.escape(w)}</div>' for w in warnings_by_id.get(rid, []))
        funding = clean(r.get("funding_or_assistantship_evidence")) or "Not verified"
        status = clean(r.get("workflow_status"))
        buttons = ""
        if status == m.DRAFT_READY:
            buttons = '<div class="warn">Not approved yet. Approve it first (5_approve_drafts.bat); the send buttons appear on the outbox page after approval.</div>'
        if to and subject and body and status == m.APPROVED and rid in sendable_ids:
            buttons = (
                f'<a class="btn primary" href="{html.escape(gmail_compose_url(to, subject, body, sender_account), quote=True)}" target="_blank" rel="noopener">Open in Gmail</a>'
                f'<a class="btn" href="{html.escape(mailto_url(to, subject, body), quote=True)}">Open in email app</a>'
                f'<button class="btn" onclick="copyText(\'body-{html.escape(rid)}\')">Copy email text</button>'
            )
        cards.append(
            f"""
<section class="card" id="{html.escape(rid)}">
  <div class="row"><div class="name">{html.escape(clean(r.get('professor_name')))}</div>
  <div><span class="score">Fit {html.escape(clean(r.get('fit_score')) or '?')}/10</span></div></div>
  <div class="meta">{html.escape(clean(r.get('title')))} &middot; {html.escape(clean(r.get('department_or_school')))} &middot; {html.escape(clean(r.get('university')))} {html.escape(clean(r.get('state')))}</div>
  <div class="meta"><span class="badge">{html.escape(rid)}</span><span class="badge">{html.escape(status)}</span><span class="badge">verification: {html.escape(clean(r.get('verification_status')))}</span></div>
  {warn_html}
  <p><strong>To:</strong> {html.escape(to)}<br><strong>Subject:</strong> {html.escape(subject)}</p>
  <pre id="body-{html.escape(rid)}">{html.escape(body)}</pre>
  {buttons}
  <details><summary>Why this professor? (fit explanation)</summary><p>{html.escape(clean(r.get('research_fit_explanation')))}</p><p class="meta">{html.escape(clean(r.get('fit_score_breakdown')))}</p></details>
  <h3 class="checks-title">Checks (what was verified, where)</h3>{checks_html(r)}
  <details><summary>Earlier research notes (from search results; not checked on official pages)</summary><p>Funding: {html.escape(funding)}<br>Spring 2027: {html.escape(clean(r.get('spring_2027_status')) or 'Not verified')}<br>Fall 2027: {html.escape(clean(r.get('fall_2027_status')) or 'Not verified')}<br>Eligibility: {html.escape(clean(r.get('eligibility_notes')) or 'Not verified')}</p></details>
  <details open><summary>Evidence links (check before sending)</summary><ul>{''.join(evidence) or '<li>No links recorded</li>'}</ul></details>
  <div class="checklist"><label><input type="checkbox"> Name, title and email match the official page</label>
  <label><input type="checkbox"> Their research topic in the email matches their official profile</label>
  <label><input type="checkbox"> I read the abstract of the cited paper (or removed the mention)</label>
  <label><input type="checkbox"> Program and intake are correct</label><label><input type="checkbox"> CV attached{(': ' + html.escape(cv_report.filename)) if cv_report is not None and cv_report.filename else ' (PDF)'}</label></div>
</section>"""
        )
    count = len(records)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}{CHECK_CSS}</style></head>
<body><header><h1>{html.escape(title)}</h1>
<div class="meta">{count} email(s) &middot; generated {today.isoformat()} &middot; Nothing is sent from this page.
{"Approved emails: open each in Gmail, attach your CV, press Send yourself, then record it with <code>outreach mark-sent --ids ...</code>." if sendable_ids else "Review each draft and check the evidence links. Research details came from search results of official pages, so confirm them on the profile. Then approve the ones you are happy with (5_approve_drafts.bat). Send buttons appear only on the outbox page, after approval."}</div></header>
<main>{_cv_block(cv_report)}{''.join(cards) or '<p>No drafts to review yet. Run the pipeline first.</p>'}</main>
<script>function copyText(id){{const t=document.getElementById(id).innerText;navigator.clipboard&&navigator.clipboard.writeText(t).then(()=>alert('Email text copied.'),()=>alert('Copy failed: select the text and press Ctrl+C.'));}}</script>
</body></html>"""


def _cv_block(cv_report) -> str:
    """The CV to attach (outbox): which file, its pages and size, a link to open it, and any problem."""
    if cv_report is None:
        return ""
    lines = [f"<strong>Attach this CV to every email:</strong> {html.escape(cv_report.summary())}"]
    if cv_report.path and cv_report.exists:
        lines.append(f'<a href="{html.escape(cv_report.path.resolve().as_uri(), quote=True)}" target="_blank" rel="noopener noreferrer">Open the CV to check it</a>'
                     f' <span class="meta">({html.escape(str(cv_report.path))})</span>')
    lines += [f"Problem: {html.escape(p)}" for p in cv_report.problems] + [f"Check: {html.escape(w)}" for w in cv_report.warnings]
    kind = "warn" if (cv_report.problems or cv_report.warnings) else "card"
    return f'<section class="{kind}" style="padding:12px">' + "<br>".join(lines) + "</section>"


def write_review_page(records: list[dict], path: Path, title: str, today: date, sender_account: str = "", warnings_by_id=None,
                      sendable_ids=None, cv_report=None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_review_page(records, title, today, sender_account, warnings_by_id, sendable_ids, cv_report), encoding="utf-8")
    return path
