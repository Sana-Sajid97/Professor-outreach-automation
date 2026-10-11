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
from .tracker import log_event, sent_count_on, set_status

TEST_DOMAINS = (".example", "example.com", "example.org", "example.net", "example.edu", ".test", ".invalid")


@dataclass
class SendReport:
    method: str
    sent: list[str] = field(default_factory=list)
    drafted: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    outbox_path: Path | None = None


def preview(record: dict) -> str:
    lines = [
        "=" * 72,
        f"{clean(record.get('record_id'))}  |  Fit {clean(record.get('fit_score')) or '?'}/10  |  {clean(record.get('workflow_status'))}",
        f"TO:      {clean(record.get('professor_name'))} <{clean(record.get('institutional_email'))}>",
        f"         {clean(record.get('title'))}, {clean(record.get('university'))}",
        f"SUBJECT: {clean(record.get('email_subject'))}",
        "-" * 72,
        record.get("email_draft", "") or "(empty)",
        "-" * 72,
        "EVIDENCE (open these to double-check):",
        f"  Official profile:   {clean(record.get('faculty_profile_url')) or '(missing)'}",
        f"  Email found at:     {clean(record.get('email_source_url')) or '(missing)'}  [{clean(record.get('email_verification'))}]",
    ]
    for n in (1, 2):
        if clean(record.get(f"relevant_publication_{n}")):
            lines.append(f"  Publication:        {clean(record.get(f'relevant_publication_{n}'))} {clean(record.get(f'publication_{n}_url'))}")
    if clean(record.get("program_url")):
        lines.append(f"  Program:            {clean(record.get('program_url'))}")
    lines.append(f"  Funding evidence:   {clean(record.get('funding_or_assistantship_evidence')) or 'Not verified'}")
    lines.append(f"  Why: {clean(record.get('fit_score_breakdown'))[:400]}")
    return "\n".join(lines)


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
) -> int:
    """Show each draft and approve only on an explicit 'yes'."""
    wanted = {i.strip().upper() for i in (ids or []) if i.strip()}
    candidates = [r for r in records if clean(r.get("workflow_status")) == m.DRAFT_READY]
    if wanted:
        candidates = [r for r in candidates if clean(r.get("record_id")).upper() in wanted]
    if not candidates:
        print_fn("No drafts are waiting for approval. Run the pipeline first (or check the IDs).")
        return 0
    approved = 0
    for record in candidates:
        problem = approval_problem(record, suppression)
        if problem:
            print_fn(f"Skipping {record.get('record_id')}: {problem}.")
            continue
        print_fn(preview(record))
        answer = input_fn("Approve this email? Type 'yes' to approve, 'skip' to skip, 'quit' to stop: ").strip().lower()
        if answer == "quit":
            break
        if answer != "yes":
            print_fn("Not approved.")
            continue
        set_status(record, m.APPROVED, today, settings)
        record["approval_hash"] = draft_hash(record)
        log_event(settings, record, "approved", f"subject={clean(record.get('email_subject'))}; hash={record['approval_hash']}")
        approved += 1
        print_fn(f"Approved {record.get('record_id')}.")
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
) -> SendReport:
    report = SendReport(method)
    wanted = {i.strip().upper() for i in (ids or []) if i.strip()}
    ready = []
    for record in records:
        if clean(record.get("workflow_status")) != m.APPROVED:
            continue
        if wanted and clean(record.get("record_id")).upper() not in wanted:
            continue
        problem = send_problem(record, suppression)
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
        report.outbox_path = write_review_page(ready, path, f"Outbox - {len(ready)} approved email(s)", today)
        print_fn(f"Open this page and send each email from Gmail yourself:\n  {report.outbox_path}")
        print_fn("After sending, record them with:  python -m src.cli mark-sent --ids " + ",".join(clean(r.get("record_id")) for r in ready))
        return report

    if method not in {"gmail-drafts", "gmail-api"}:
        raise UserFacingError("Unknown method. Use: manual, gmail-drafts, or gmail-api.")
    if method == "gmail-api" and not settings.sending_enabled:
        raise UserFacingError(
            "Automatic sending is switched off (EMAIL_MODE=drafts_only). Use --method gmail-drafts or manual, "
            "or set EMAIL_MODE=send_enabled in your .env file if you really want the tool to send."
        )
    attachment = Path(settings.cv_attachment) if settings.cv_attachment else None
    if attachment and not attachment.is_absolute():
        attachment = settings.root / attachment
    if gmail_service is None:
        from .gmail_client import get_service

        gmail_service = get_service(settings.gmail_client_path, settings.gmail_token_path)
    from .gmail_client import build_raw_message, create_draft, send_raw

    print_fn(f"\nYou are about to {'SEND' if method == 'gmail-api' else 'create Gmail drafts for'} {len(ready)} email(s):")
    for record in ready:
        print_fn(f"  {clean(record.get('record_id'))}: {clean(record.get('professor_name'))} <{clean(record.get('institutional_email'))}> - {clean(record.get('email_subject'))}")
    if attachment:
        print_fn(f"Attachment: {attachment.name}")
    else:
        print_fn("WARNING: no CV attachment configured (CV_ATTACHMENT in .env).")
    phrase = f"SEND {len(ready)}" if method == "gmail-api" else f"DRAFT {len(ready)}"
    answer = input_fn(f"Type exactly '{phrase}' to continue (anything else cancels): ").strip()
    if answer != phrase:
        print_fn("Cancelled. Nothing was sent.")
        return report

    for index, record in enumerate(ready):
        rid = clean(record.get("record_id"))
        try:
            raw = build_raw_message(clean(record.get("institutional_email")), clean(record.get("email_subject")), record.get("email_draft", ""), attachment=attachment)
            if method == "gmail-drafts":
                draft_id = create_draft(gmail_service, raw)
                record["notes"] = f"{clean(record.get('notes'))} | {today.isoformat()}: Gmail draft created (id {draft_id}); send it from Gmail, then mark-sent.".strip(" |")
                log_event(settings, record, "gmail_draft_created", f"draft_id={draft_id}")
                report.drafted.append(rid)
            else:
                message_id = send_raw(gmail_service, raw)
                set_status(record, m.SENT, today, settings)
                log_event(settings, record, "sent_via_gmail_api", f"message_id={message_id}; subject={clean(record.get('email_subject'))}")
                report.sent.append(rid)
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
) -> int:
    wanted = [i.strip().upper() for i in ids if i.strip()]
    chosen = [r for r in records if clean(r.get("record_id")).upper() in wanted]
    missing = set(wanted) - {clean(r.get("record_id")).upper() for r in chosen}
    for rid in sorted(missing):
        print_fn(f"No record with id {rid}.")
    ok = []
    for record in chosen:
        status = clean(record.get("workflow_status"))
        if status not in {m.APPROVED, m.FOLLOW_UP_DUE}:
            print_fn(f"{record.get('record_id')}: status is '{status}'. Only approved emails (or due follow-ups) can be marked as sent.")
            continue
        ok.append(record)
    if not ok:
        return 0
    answer = input_fn(f"Did you actually send these {len(ok)} email(s) yourself? Type 'yes' to record them as sent: ").strip().lower()
    if answer != "yes":
        print_fn("Nothing changed.")
        return 0
    day = sent_on or today
    for record in ok:
        was_follow_up = clean(record.get("workflow_status")) == m.FOLLOW_UP_DUE
        set_status(record, m.SENT, day, settings)
        log_event(settings, record, "follow_up_sent" if was_follow_up else "sent", f"recorded by user; subject={clean(record.get('email_subject'))}")
    return len(ok)


def _ids(value: str) -> list[str]:
    return [v for v in split_multi(value.replace(",", ";")) if v]
