"""Workflow status changes, follow-up dates and the outreach audit log."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from . import models as m
from .config import Settings
from .storage import append_csv_row, read_csv_rows
from .textutil import clean, parse_iso

LOG_COLUMNS = ["timestamp", "record_id", "professor_name", "institutional_email", "action", "details"]


def log_event(settings: Settings, record: dict, action: str, details: str = "") -> None:
    append_csv_row(
        settings.outreach_log_path,
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "record_id": clean(record.get("record_id")),
            "professor_name": clean(record.get("professor_name")),
            "institutional_email": clean(record.get("institutional_email")),
            "action": action,
            "details": details,
        },
        LOG_COLUMNS,
    )


def read_log(settings: Settings) -> list[dict]:
    if not settings.outreach_log_path.exists():
        return []
    rows, _ = read_csv_rows(settings.outreach_log_path)
    return rows


SENT_ACTIONS = {"sent", "follow_up_sent", "sent_via_gmail_api"}


def _logged_subject(details: str) -> str:
    """Log details end with 'subject=<subject>' for sends and Gmail drafts."""
    details = clean(details)
    return details.rsplit("subject=", 1)[1].strip() if "subject=" in details else ""


def _log_matches(row: dict, email: str, subject: str) -> bool:
    from .textutil import normalize_email

    return normalize_email(row.get("institutional_email", "")) == normalize_email(email) and _logged_subject(row.get("details", "")) == clean(subject)


def already_sent(settings: Settings, email: str, subject: str) -> bool:
    """True if the outreach log already records this exact email (same address and same subject) as sent."""
    return any(clean(row.get("action")) in SENT_ACTIONS and _log_matches(row, email, subject) for row in read_log(settings))


def gmail_draft_already_created(settings: Settings, email: str, subject: str) -> bool:
    """True if a Gmail draft was already created for this exact email (prevents duplicate drafts in Gmail)."""
    return any(clean(row.get("action")) == "gmail_draft_created" and _log_matches(row, email, subject) for row in read_log(settings))


def reconcile_with_log(records: list[dict], settings: Settings) -> list[str]:
    """Crash safety: the outreach log is written the moment an email is sent. If the tracker could not be saved
    afterwards (power cut, file open in Excel), an approved record whose exact email is in the log as sent is
    moved to 'sent' here. Returns the ids that were fixed."""
    from .textutil import normalize_email

    sent_on: dict[tuple[str, str], date] = {}
    for row in read_log(settings):
        if clean(row.get("action")) in SENT_ACTIONS:
            day = parse_iso(clean(row.get("timestamp"))[:10])
            if day:
                sent_on[(normalize_email(row.get("institutional_email", "")), _logged_subject(row.get("details", "")))] = day
    fixed = []
    for record in records:
        if clean(record.get("workflow_status")) != m.APPROVED:
            continue
        key = (normalize_email(record.get("institutional_email", "")), clean(record.get("email_subject")))
        if key in sent_on:
            set_status(record, m.SENT, sent_on[key], settings, note="status restored from the outreach log (the email had been sent)")
            fixed.append(clean(record.get("record_id")))
    return fixed


def sent_count_on(settings: Settings, day: date) -> int:
    """How many emails were recorded as sent on a given day (for the daily limit)."""
    prefix = day.isoformat()
    return sum(
        1
        for row in read_log(settings)
        if clean(row.get("action")) in SENT_ACTIONS and clean(row.get("timestamp")).startswith(prefix)
    )


def set_status(record: dict, new_status: str, today: date, settings: Settings | None = None, note: str = "") -> None:
    """Move a record to a new status (validated) and update the related tracking columns."""
    current = clean(record.get("workflow_status")) or m.DISCOVERED
    m.check_transition(current, new_status)
    record["workflow_status"] = new_status
    follow_days = settings.follow_up_days if settings else 10
    max_follow = settings.max_follow_ups if settings else 1
    if new_status == m.SENT:
        count = int(clean(record.get("follow_up_count")) or 0)
        if clean(record.get("last_contact_date")):  # contacted before, so this send is a follow-up
            count += 1
            record["follow_up_count"] = str(count)
        record["last_contact_date"] = today.isoformat()
        if count < max_follow:
            due = today + timedelta(days=follow_days)
            record["follow_up_date"] = due.isoformat()
            record["next_action"] = f"Wait for a reply. If there is none, send one polite follow-up on or after {due.isoformat()}."
        else:
            record["follow_up_date"] = ""
            record["next_action"] = "Wait for a reply. No more follow-ups planned; close the record if there is no answer in 2-3 weeks."
        record["approval_hash"] = ""
    elif new_status == m.REPLIED:
        record["reply_status"] = note or "Replied"
        record["follow_up_date"] = ""
        record["next_action"] = "Read the reply and respond personally."
    elif new_status == m.CLOSED:
        record["follow_up_date"] = ""
        record["next_action"] = note or "Closed."
    elif new_status in m.SUPPRESSED_STATUSES:
        record["opt_out_or_suppression"] = f"{new_status} since {today.isoformat()}"
        record["follow_up_date"] = ""
        record["next_action"] = "Do not contact."
        record["approval_hash"] = ""
    elif new_status == m.NOT_A_FIT:
        record["next_action"] = note or "Not a fit; no outreach planned."
    elif new_status == m.APPROVED:
        record["approved_on"] = today.isoformat()
        record["next_action"] = "Approved. Send it (python -m src.cli send), then record it with mark-sent."
    if note and new_status not in {m.REPLIED, m.CLOSED, m.NOT_A_FIT}:
        record["notes"] = f"{clean(record.get('notes'))} | {today.isoformat()}: {note}".strip(" |")


def refresh_follow_ups(records: list[dict], today: date, settings: Settings) -> list[str]:
    """Mark 'sent' records whose follow-up date has arrived as 'follow_up_due'. Returns their ids."""
    due_ids = []
    for record in records:
        if clean(record.get("workflow_status")) != m.SENT:
            continue
        due = parse_iso(record.get("follow_up_date", ""))
        count = int(clean(record.get("follow_up_count")) or 0)
        if due and due <= today and count < settings.max_follow_ups:
            record["workflow_status"] = m.FOLLOW_UP_DUE
            record["next_action"] = "No reply yet: generate and send ONE polite follow-up (python -m src.cli followups --draft)."
            due_ids.append(clean(record.get("record_id")))
    return due_ids


def status_counts(records: list[dict]) -> dict[str, int]:
    counts = {s: 0 for s in m.WORKFLOW_STATUSES}
    for record in records:
        status = clean(record.get("workflow_status")) or m.DISCOVERED
        counts[status] = counts.get(status, 0) + 1
    return counts


def find_record(records: list[dict], record_id: str) -> dict | None:
    rid = clean(record_id).upper()
    for record in records:
        if clean(record.get("record_id")).upper() == rid:
            return record
    return None
