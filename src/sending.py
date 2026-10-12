"""Approval and sending: always separate from the one-click pipeline, always human-approved.

Workflow:
  1. approve   - you read each draft (recipient, subject, body, evidence) and type 'yes'.
  2. send      - choose how:
       manual        (default, no setup) an "outbox" page with Open-in-Gmail buttons; you press Send.
       gmail-drafts  creates real drafts in your Gmail (with your CV attached); you press Send in Gmail.
       gmail-api     sends for you, ONLY if EMAIL_MODE=send_enabled, within the daily limit,
                     after you type the exact confirmation phrase.
  3. mark-sent - record what you actually sent (manual and gmail-drafts methods).

An approval is tied to the exact text approved: if the subject, body or recipient
changes afterwards, the record must be approved again.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import models as m
from .config import Settings
from .drafting import draft_hash
from .errors import UserFacingError
from .review import write_review_page
from .suppression import SuppressionList
from .textutil import clean, email_domain, normalize_email, split_multi
from .tracker import already_sent, gmail_draft_already_created, log_event, sent_count_on, set_status

TEST_DOMAINS = (".example", "example.com", "example.org", "example.net", "example.edu", ".test", ".invalid")


@dataclass
class SendReport:
    method: str
    sent: list[str] = field(default_factory=list)
    drafted: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    outbox_path: Path | None = None
    attachment_notes: list[tuple[str, str]] = field(default_factory=list)  # (record id, what was checked about the CV)


CV_MENTION_RE = re.compile(r"\battach\w*\b[^.]{0,40}\b(?:cv|resume|r\u00e9sum\u00e9|curriculum vitae)\b|\b(?:cv|resume)\b[^.]{0,20}\battached\b", re.IGNORECASE)


def mentions_cv(record: dict) -> bool:
    """True when the email says a CV is attached, so it must not go out without one."""
    return bool(CV_MENTION_RE.search(record.get("email_draft", "") or ""))


def preview(record: dict, cv_report=None) -> str:
    from . import checks as ck

    lines = [
        "=" * 72,
        f"{clean(record.get('record_id'))}  |  Fit {clean(record.get('fit_score')) or '?'}/10  |  {clean(record.get('workflow_status'))}",
        f"TO:      {clean(record.get('professor_name'))} <{clean(record.get('institutional_email'))}>",
        f"         {clean(record.get('title'))}, {clean(record.get('university'))}",
        f"SUBJECT: {clean(record.get('email_subject'))}",
        "-" * 72,
        record.get("email_draft", "") or "(empty)",
        "-" * 72,
    ]
    if cv_report is not None and mentions_cv(record):
        lines.append(f"ATTACHMENT: {cv_report.summary()}")
        lines += [f"  PROBLEM: {p}" for p in cv_report.problems] + [f"  check:   {w}" for w in cv_report.warnings]
    checks = ck.load_checks(record)
    lines.append("CHECKS:  " + ck.summary_text(checks))
    problems, attention = ck.problems(record), ck.attention(record)
    if problems:
        lines.append("  PROBLEMS (fix them in the editor, or approve anyway only if you are sure):")
        lines += [f"   x {p}" for p in problems]
    if attention:
        lines.append("  To look at:")
        lines += [f"   - {a}" for a in attention]
    funding = ck.get_check(checks, "funding")
    if funding.get("evidence"):
        lines.append(f"  Funding quote: \u201c{funding['evidence'][0].get('quote', '')[:200]}\u201d ({funding['evidence'][0].get('url', '')})")
    lines += [
        "EVIDENCE (open these to double-check):",
        f"  Official profile:   {clean(record.get('faculty_profile_url')) or '(missing)'}",
        f"  Email found at:     {clean(record.get('email_source_url')) or '(missing)'}  [{clean(record.get('email_verification'))}]",
    ]
    for n in (1, 2):
        if clean(record.get(f"relevant_publication_{n}")):
            lines.append(f"  Publication:        {clean(record.get(f'relevant_publication_{n}'))} {clean(record.get(f'publication_{n}_url'))}")
    if clean(record.get("program_url")):
        lines.append(f"  Program:            {clean(record.get('program_url'))}")
    lines.append(f"  Earlier research notes (not checked): {clean(record.get('funding_or_assistantship_evidence'))[:200] or 'none'}")
    lines.append(f"  Why: {clean(record.get('fit_score_breakdown'))[:400]}")
    return "\n".join(lines)


def cv_problem(record: dict, cv_report) -> str:
    """Why this email cannot go out with the current CV ('' when it can)."""
    if cv_report is None or not mentions_cv(record):
        return ""
    if not cv_report.ok_to_attach:
        return "the email says your CV is attached, but the CV is not ready: " + (cv_report.problems[0] if cv_report.problems else "check it with: outreach cv")
    approved_with = clean(record.get("cv_fingerprint"))
    if approved_with and approved_with != cv_report.fingerprint:
        return (f"the CV file changed after you approved this email (approved {approved_with}, now {cv_report.fingerprint}). "
                "Approve it again so you know which CV goes out")
    return ""


def _is_test_address(email: str) -> bool:
    domain = email_domain(email)
    return not domain or any(domain.endswith(t) or domain == t.strip(".") for t in TEST_DOMAINS)


def approval_problem(record: dict, suppression: SuppressionList) -> str:
    if suppression.is_suppressed(record) or clean(record.get("workflow_status")) in m.SUPPRESSED_STATUSES:
        return "on the suppression list"
    if clean(record.get("workflow_status")) != m.DRAFT_READY:
        return f"status is '{clean(record.get('workflow_status'))}', not draft_ready"
    if clean(record.get("verification_status")) != m.VER_VERIFIED:
        return "not verified"
    if not clean(record.get("email_subject")) or not clean(record.get("email_draft")):
        return "draft is empty"
    from .validate import PLACEHOLDER_RE

    if PLACEHOLDER_RE.search(record.get("email_draft", "")) or PLACEHOLDER_RE.search(record.get("email_subject", "")):
        return "draft still contains a placeholder like [..]"
    return ""


def send_problem(record: dict, suppression: SuppressionList) -> str:
    if suppression.is_suppressed(record) or clean(record.get("workflow_status")) in m.SUPPRESSED_STATUSES:
        return "on the suppression list"
    status = clean(record.get("workflow_status"))
    if status != m.APPROVED:
        return f"status is '{status}', not approved"
    if not clean(record.get("approval_hash")) or clean(record.get("approval_hash")) != draft_hash(record):
        return "the email changed after approval (or was never approved) - approve it again"
    email = normalize_email(record.get("institutional_email", ""))
    if not email:
        return "no email address"
    if clean(record.get("email_verification")) not in m.TRUSTED_EMAIL_METHODS:
        return "email was not confirmed on an official page"
    if clean(record.get("record_source")) == "sample" or _is_test_address(email):
        return "sample/test record - never sent"
    return ""


def approve(
    records: list[dict],
    settings: Settings,
    suppression: SuppressionList,
    today: date,
    ids: list[str] | None = None,
    input_fn=input,
    print_fn=print,
    profile: dict | None = None,
) -> int:
    """Show each draft with its checks and the CV, and approve only on an explicit answer.
    'yes' approves a clean email; an email with FAILED checks needs 'approve anyway'."""
    from . import checks as ck
    from .cv_check import inspect_cv

    wanted = {i.strip().upper() for i in (ids or []) if i.strip()}
    candidates = [r for r in records if clean(r.get("workflow_status")) == m.DRAFT_READY]
    if wanted:
        candidates = [r for r in candidates if clean(r.get("record_id")).upper() in wanted]
    if not candidates:
        print_fn("No drafts are waiting for approval. Run the pipeline first (or check the IDs).")
        return 0
    cv_report = inspect_cv(settings, profile or {})
    approved = 0
    for record in candidates:
        problem = approval_problem(record, suppression)
        if not problem and mentions_cv(record) and not cv_report.ok_to_attach:
            problem = "the email says your CV is attached, but the CV is not ready: " + "; ".join(cv_report.problems)
        if problem:
            print_fn(f"Skipping {record.get('record_id')}: {problem}.")
            continue
        print_fn(preview(record, cv_report))
        has_problems = bool(ck.problems(record))
        if has_problems:
            prompt = "This email has problems (marked x above). Type 'approve anyway' to approve it as it is, 'skip' to fix it first, 'quit' to stop: "
        else:
            prompt = "Approve this email? Type 'yes' to approve, 'skip' to skip, 'quit' to stop: "
        answer = input_fn(prompt).strip().lower()
        if answer == "quit":
            break
        if answer != ("approve anyway" if has_problems else "yes"):
            print_fn("Not approved." + (" (Fix it in the editor: edit_drafts.bat)" if has_problems else ""))
            continue
        set_status(record, m.APPROVED, today, settings)
        record["approval_hash"] = draft_hash(record)
        record["cv_fingerprint"] = cv_report.fingerprint if mentions_cv(record) else ""
        details = f"subject={clean(record.get('email_subject'))}; hash={record['approval_hash']}"
        if record["cv_fingerprint"]:
            details = f"cv={cv_report.filename} {cv_report.fingerprint}; " + details
        if has_problems:
            details = "approved anyway despite failed checks; " + details
        log_event(settings, record, "approved", details)
        approved += 1
        print_fn(f"Approved {record.get('record_id')}." + (f" CV that goes with it: {cv_report.summary()}" if record["cv_fingerprint"] else ""))
    return approved


def send(
    records: list[dict],
    settings: Settings,
    suppression: SuppressionList,
    today: date,
    method: str = "manual",
    limit: int | None = None,
    ids: list[str] | None = None,
    input_fn=input,
    print_fn=print,
    gmail_service=None,
    sleep=time.sleep,
    save_fn=None,
    profile: dict | None = None,
) -> SendReport:
    """save_fn: saves the tracker. It is called before the first Gmail send (to make sure saving works) and after
    every successful send, so a sent email is recorded at once and can never be sent twice.
    The CV is checked first: an email that says a CV is attached never goes out without the same CV you approved."""
    from .cv_check import inspect_cv

    report = SendReport(method)
    cv_report = inspect_cv(settings, profile or {})
    wanted = {i.strip().upper() for i in (ids or []) if i.strip()}
    ready = []
    for record in records:
        if clean(record.get("workflow_status")) != m.APPROVED:
            continue
        if wanted and clean(record.get("record_id")).upper() not in wanted:
            continue
        problem = send_problem(record, suppression) or cv_problem(record, cv_report)
        if not problem and normalize_email(record.get("institutional_email", "")) in {normalize_email(r.get("institutional_email", "")) for r in ready}:
            problem = "another approved email in this batch goes to the same address"
        if not problem and already_sent(settings, record.get("institutional_email", ""), record.get("email_subject", "")):
            problem = (
                "the outreach log shows this exact email (same address and subject) was already sent - not sending it again. "
                "If it truly must go again (e.g. a temporary bounce), change the subject and approve it again"
            )
        if not problem and method == "gmail-drafts" and gmail_draft_already_created(
            settings, record.get("institutional_email", ""), record.get("email_subject", "")
        ):
            problem = "a Gmail draft for this exact email already exists - send it from Gmail's Drafts folder (or use --method manual)"
        if problem:
            report.skipped.append((clean(record.get("record_id")), problem))
            continue
        ready.append(record)
    already_today = sent_count_on(settings, today)
    room = max(0, settings.daily_send_limit - already_today)
    cap = min(room, limit) if limit else room
    if len(ready) > cap:
        for record in ready[cap:]:
            report.skipped.append((clean(record.get("record_id")), f"daily limit of {settings.daily_send_limit} reached"))
        ready = ready[:cap]
    if not ready:
        print_fn("Nothing to send. Approve drafts first (python -m src.cli approve).")
        for rid, why in report.skipped:
            print_fn(f"  skipped {rid}: {why}")
        return report

    if method == "manual":
        path = settings.exports_dir / f"outbox_{today.isoformat()}.html"
        report.outbox_path = write_review_page(
            ready, path, f"Outbox - {len(ready)} approved email(s)", today, sendable_ids={clean(r.get("record_id")) for r in ready},
            cv_report=cv_report if any(mentions_cv(r) for r in ready) else None,
        )
        print_fn(f"Open this page and send each email from Gmail yourself:\n  {report.outbox_path}")
        if any(mentions_cv(r) for r in ready):
            print_fn(f"Attach this CV to every email: {cv_report.path}  ({cv_report.summary()})")
        print_fn("After sending, record them with:  python -m src.cli mark-sent --ids " + ",".join(clean(r.get("record_id")) for r in ready))
        return report

    if method not in {"gmail-drafts", "gmail-api"}:
        raise UserFacingError("Unknown method. Use: manual, gmail-drafts, or gmail-api.")
    if method == "gmail-api" and not settings.sending_enabled:
        raise UserFacingError(
            "Automatic sending is switched off (EMAIL_MODE=drafts_only). Use --method gmail-drafts or manual, "
            "or set EMAIL_MODE=send_enabled in your .env file if you really want the tool to send."
        )
    needs_cv = any(mentions_cv(r) for r in ready)
    attachment = cv_report.path if needs_cv else None
    if gmail_service is None:
        from .gmail_client import get_service

        gmail_service = get_service(settings.gmail_client_path, settings.gmail_token_path)
    from .gmail_client import build_raw_message, create_draft, draft_attachments, raw_attachments, send_raw

    print_fn(f"\nYou are about to {'SEND' if method == 'gmail-api' else 'create Gmail drafts for'} {len(ready)} email(s):")
    for record in ready:
        print_fn(f"  {clean(record.get('record_id'))}: {clean(record.get('professor_name'))} <{clean(record.get('institutional_email'))}> - {clean(record.get('email_subject'))}")
    if attachment:
        print_fn(f"Attachment for every email: {cv_report.summary()}")
    else:
        print_fn("No attachment: these emails do not say a CV is attached.")
    phrase = f"SEND {len(ready)}" if method == "gmail-api" else f"DRAFT {len(ready)}"
    answer = input_fn(f"Type exactly '{phrase}' to continue (anything else cancels): ").strip()
    if answer != phrase:
        print_fn("Cancelled. Nothing was sent.")
        return report

    if save_fn is not None:
        save_fn()  # fails here (e.g. tracker open in Excel) BEFORE anything is sent or drafted
    for index, record in enumerate(ready):
        rid = clean(record.get("record_id"))
        try:
            this_attachment = attachment if mentions_cv(record) else None
            raw = build_raw_message(clean(record.get("institutional_email")), clean(record.get("email_subject")), record.get("email_draft", ""), attachment=this_attachment)
            if this_attachment:  # prove the approved CV is inside this exact message before Gmail gets it
                inside = raw_attachments(raw)
                if [(name, sha) for name, _, sha in inside] != [(this_attachment.name, cv_report.fingerprint)]:
                    raise UserFacingError(f"{rid}: the CV inside the message is not the approved CV. Nothing was sent; check it with: outreach cv")
            if method == "gmail-drafts":
                draft_id = create_draft(gmail_service, raw)
                if this_attachment:
                    try:
                        found = draft_attachments(gmail_service, draft_id)
                        if (this_attachment.name, cv_report.size_bytes) in found:
                            report.attachment_notes.append((rid, f"Gmail confirms the draft has {this_attachment.name} attached ({cv_report.size_bytes // 1024} KB)."))
                        else:
                            report.attachment_notes.append((rid, f"WARNING: Gmail's draft does not show {this_attachment.name} attached (it shows {found or 'no attachment'}). Attach it in Gmail before sending."))
                    except Exception as exc:  # reading back is a check, not a requirement
                        report.attachment_notes.append((rid, f"Could not read the draft back to check the attachment ({exc.__class__.__name__}). Open it in Gmail and check."))
                record["notes"] = f"{clean(record.get('notes'))} | {today.isoformat()}: Gmail draft created (id {draft_id}); send it from Gmail, then mark-sent.".strip(" |")
                log_event(settings, record, "gmail_draft_created", f"draft_id={draft_id}; subject={clean(record.get('email_subject'))}")
                report.drafted.append(rid)
                if save_fn is not None:
                    save_fn()
            else:
                message_id = send_raw(gmail_service, raw)
                if this_attachment:
                    report.attachment_notes.append((rid, f"Sent with {this_attachment.name} attached (fingerprint {cv_report.fingerprint})."))
                set_status(record, m.SENT, today, settings)
                log_event(settings, record, "sent_via_gmail_api", f"message_id={message_id}; subject={clean(record.get('email_subject'))}")
                report.sent.append(rid)
                if save_fn is not None:
                    try:
                        save_fn()
                    except UserFacingError as exc:
                        raise UserFacingError(
                            f"{rid} was sent and recorded in the outreach log, but the tracker could not be saved ({exc}). "
                            "Sending stopped. The log prevents this email from being sent again."
                        ) from exc
                if index < len(ready) - 1:
                    sleep(random.uniform(45, 90))  # spread emails out; never bursts
        except UserFacingError:
            raise
        except Exception as exc:  # stop at the first failure; nothing is marked sent unless Gmail confirmed it
            report.failed.append((rid, f"{exc.__class__.__name__}: {exc}"))
            log_event(settings, record, "send_failed", str(exc)[:300])
            print_fn(f"Stopped: {rid} failed ({exc}). Earlier emails in this batch were processed; the rest were not.")
            break
    return report


def mark_sent(
    records: list[dict],
    ids: list[str],
    settings: Settings,
    today: date,
    input_fn=input,
    print_fn=print,
    sent_on: date | None = None,
    suppression: SuppressionList | None = None,
    profile: dict | None = None,
) -> int:
    """Record emails you sent yourself. Only APPROVED emails (unchanged since approval) can be recorded."""
    suppression = suppression or SuppressionList.load(settings.suppression_path)
    wanted = [i.strip().upper() for i in ids if i.strip()]
    chosen = [r for r in records if clean(r.get("record_id")).upper() in wanted]
    missing = set(wanted) - {clean(r.get("record_id")).upper() for r in chosen}
    for rid in sorted(missing):
        print_fn(f"No record with id {rid}.")
    ok = []
    for record in chosen:
        status = clean(record.get("workflow_status"))
        if status != m.APPROVED:
            print_fn(f"{record.get('record_id')}: status is '{status}'. Only approved emails can be marked as sent (approve it first).")
            continue
        problem = send_problem(record, suppression)
        if problem:
            print_fn(f"{record.get('record_id')}: cannot be recorded as sent - {problem}.")
            continue
        if already_sent(settings, record.get("institutional_email", ""), record.get("email_subject", "")):
            print_fn(f"{record.get('record_id')}: the outreach log already shows this exact email as sent.")
            continue
        ok.append(record)
    if not ok:
        return 0
    from .cv_check import inspect_cv

    cv_report = inspect_cv(settings, profile or {})
    with_cv = [r for r in ok if mentions_cv(r)]
    for record in with_cv:
        note = cv_problem(record, cv_report)
        if note:
            print_fn(f"Note for {record.get('record_id')}: {note}.")
    cv_words = f", with your CV ({cv_report.filename}) attached" if with_cv and cv_report.filename else ""
    answer = input_fn(f"Did you actually send these {len(ok)} email(s) yourself{cv_words}? Type 'yes' to record them as sent: ").strip().lower()
    if answer != "yes":
        print_fn("Nothing changed.")
        return 0
    day = sent_on or today
    for record in ok:
        was_follow_up = bool(clean(record.get("last_contact_date")))
        set_status(record, m.SENT, day, settings)
        log_event(settings, record, "follow_up_sent" if was_follow_up else "sent", f"recorded by user; subject={clean(record.get('email_subject'))}")
    return len(ok)


def reset_approval_for_import(record: dict) -> None:
    """Imported or restored rows never carry approvals: everything must be re-approved in this tracker."""
    record["approval_hash"] = ""
    record["approved_on"] = ""
    if clean(record.get("workflow_status")) == m.APPROVED:
        record["workflow_status"] = m.DRAFT_READY


def _ids(value: str) -> list[str]:
    return [v for v in split_multi(value.replace(",", ";")) if v]
