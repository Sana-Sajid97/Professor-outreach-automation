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
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2330;--muted:#5b6474;--line:#dde1e8;--accent:#2f5597;--warn:#9a5b00;--warnbg:#fff4e0;--ok:#1f7a3a}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d2128;--ink:#e8ebf0;--muted:#a3abb8;--line:#333a45;--accent:#8fb0ee;--warn:#ffc46b;--warnbg:#3a2c12;--ok:#6fd38f}}
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
  <details><summary>Funding and intake evidence</summary><p>Funding: {html.escape(funding)}<br>Spring 2027: {html.escape(clean(r.get('spring_2027_status')) or 'Not verified')}<br>Fall 2027: {html.escape(clean(r.get('fall_2027_status')) or 'Not verified')}<br>Eligibility: {html.escape(clean(r.get('eligibility_notes')) or 'Not verified')}</p></details>
  <details open><summary>Evidence links (check before sending)</summary><ul>{''.join(evidence) or '<li>No links recorded</li>'}</ul></details>
  <div class="checklist"><label><input type="checkbox"> Name, title and email match the official page</label>
  <label><input type="checkbox"> Their research topic in the email matches their official profile</label>
  <label><input type="checkbox"> I read the abstract of the cited paper (or removed the mention)</label>
  <label><input type="checkbox"> Program and intake are correct</label><label><input type="checkbox"> CV (PDF) attached</label></div>
</section>"""
        )
    count = len(records)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><header><h1>{html.escape(title)}</h1>
<div class="meta">{count} email(s) &middot; generated {today.isoformat()} &middot; Nothing is sent from this page.
{"Approved emails: open each in Gmail, attach your CV, press Send yourself, then record it with <code>outreach mark-sent --ids ...</code>." if sendable_ids else "Review each draft and check the evidence links. Research details came from search results of official pages, so confirm them on the profile. Then approve the ones you are happy with (5_approve_drafts.bat). Send buttons appear only on the outbox page, after approval."}</div></header>
<main>{''.join(cards) or '<p>No drafts to review yet. Run the pipeline first.</p>'}</main>
<script>function copyText(id){{const t=document.getElementById(id).innerText;navigator.clipboard&&navigator.clipboard.writeText(t).then(()=>alert('Email text copied.'),()=>alert('Copy failed: select the text and press Ctrl+C.'));}}</script>
</body></html>"""


def write_review_page(records: list[dict], path: Path, title: str, today: date, sender_account: str = "", warnings_by_id=None, sendable_ids=None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_review_page(records, title, today, sender_account, warnings_by_id, sendable_ids), encoding="utf-8")
    return path
