"""What was actually checked for each professor, where, and what it showed.

Stored in the record's `verification_checks` column as JSON, one entry per check:

    {"profile":     {"status": "passed", "checked_on": "2026-10-12", "url": "...", "detail": "..."},
     "email":       {...},
     "research":    {..., "supported": [...], "partly": [...], "unsupported": [...], "quotes": {...}, "excerpt": "..."},
     "publication": {..., "items": [{"n": 1, "status": "...", "url": "...", "detail": "..."}]},
     "program":     {..., "items": {"degree": {...}, "spring": {...}, "fall": {...}, "deadlines": {...}, "ielts": {...}, "requirements": {...}}},
     "funding":     {"status": "confirmed|possible|not_verified|not_available", "evidence": [{"url", "quote", "kind"}]},
     "edited_text": {...}}

A check that has not run is simply absent: it shows as "not checked yet".
A record counts as VERIFIED only when the profile, email and research checks have all passed
(automatically, or confirmed by you with an official link). A profile that merely exists, or a
draft that was generated, is never enough.
"""

from __future__ import annotations

import json
from datetime import date

from . import models as m
from .textutil import clean

PASSED = "passed"  # checked automatically on an official page or official API
CONFIRMED = "confirmed_by_you"  # you checked it yourself and gave the official link (never mixed up with funding "confirmed")
WARNING = "warning"  # partly supported or unclear: read the evidence before relying on it
FAILED = "failed"  # the official source contradicts the record, or the item could not be found there
NOT_CHECKED = "not_checked"
OK_STATUSES = {PASSED, CONFIRMED}

CHECK_ORDER = ["profile", "email", "research", "publication", "program", "funding"]
REQUIRED_FOR_VERIFIED = ["profile", "email", "research"]
LABELS = {
    "profile": "Official profile",
    "email": "Institutional email",
    "research": "Research described in the email",
    "publication": "Paper mentioned in the email",
    "program": "Program, intake, deadlines and IELTS",
    "funding": "Assistantship funding",
    "edited_text": "Your edits",
}
SHORT = {"profile": "Profile", "email": "Email", "research": "Research", "publication": "Paper", "program": "Program", "funding": "Funding"}
STATUS_WORDS = {
    PASSED: "passed",
    CONFIRMED: "confirmed by you",
    WARNING: "needs a look",
    FAILED: "FAILED",
    NOT_CHECKED: "not checked yet",
}

# Funding is graded rather than passed/failed.
FUNDING_CONFIRMED = "confirmed"  # an official page guarantees funding, or a professor says they are recruiting a funded student
FUNDING_POSSIBLE = "possible"  # assistantships exist in general, or an active grant: ask
FUNDING_NOT_VERIFIED = "not_verified"  # nothing found on the official pages checked
FUNDING_NOT_AVAILABLE = "not_available"  # an official page says there is no funding for this route
FUNDING_WORDS = {
    FUNDING_CONFIRMED: "confirmed on an official page",
    FUNDING_POSSIBLE: "possible (general or grant evidence only)",
    FUNDING_NOT_VERIFIED: "not verified",
    FUNDING_NOT_AVAILABLE: "official page says not available",
    CONFIRMED: "confirmed by you",
    NOT_CHECKED: "not checked yet",
}


def load_checks(record: dict) -> dict:
    raw = clean(record.get("verification_checks"))
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save_checks(record: dict, checks: dict) -> None:
    record["verification_checks"] = json.dumps(checks, ensure_ascii=False, sort_keys=True)
    record["checks_summary"] = summary_text(checks)
    record["funding_level"] = (checks.get("funding") or {}).get("status", "")


def set_check(record: dict, name: str, status: str, today: date, url: str = "", detail: str = "", **extra) -> dict:
    """Record the result of one check (replacing any earlier result for it)."""
    checks = load_checks(record)
    entry: dict = {"status": status, "checked_on": today.isoformat()}
    if url:
        entry["url"] = url
    if detail:
        entry["detail"] = detail
    entry.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    checks[name] = entry
    save_checks(record, checks)
    return entry


def get_check(checks: dict, name: str) -> dict:
    return checks.get(name) or {}


def status_of(checks: dict, name: str) -> str:
    return get_check(checks, name).get("status", NOT_CHECKED)


def derive_verification_status(checks: dict) -> str:
    if all(status_of(checks, n) in OK_STATUSES for n in REQUIRED_FOR_VERIFIED):
        return m.VER_VERIFIED
    if any(status_of(checks, n) in OK_STATUSES for n in ("profile", "email")):
        return m.VER_PARTIAL
    return m.VER_NOT


def apply_derived_status(record: dict) -> str:
    """Set verification_status from the checks and move new leads to verified / needs_verification."""
    status = derive_verification_status(load_checks(record))
    record["verification_status"] = status
    workflow = clean(record.get("workflow_status"))
    if status == m.VER_VERIFIED and workflow in {m.DISCOVERED, m.NEEDS_VERIFICATION}:
        record["workflow_status"] = m.VERIFIED
    elif status != m.VER_VERIFIED and workflow in {m.DISCOVERED, m.VERIFIED}:
        record["workflow_status"] = m.NEEDS_VERIFICATION
    return status


def missing_for_verified(checks: dict) -> list[str]:
    """Plain-language list of the required checks that have not passed yet."""
    return [f"{LABELS[n]}: {STATUS_WORDS[status_of(checks, n)]}" for n in REQUIRED_FOR_VERIFIED if status_of(checks, n) not in OK_STATUSES]


def summary_text(checks: dict) -> str:
    """One readable line (plain text, so it shows correctly in Excel and in any console)."""
    parts = []
    for name in CHECK_ORDER:
        status = status_of(checks, name)
        if name == "funding":
            parts.append(f"Funding: {FUNDING_WORDS.get(status, status)}")
        else:
            parts.append(f"{SHORT[name]}: {STATUS_WORDS.get(status, status)}")
    return " | ".join(parts)


def problems(record: dict) -> list[str]:
    """Checks that FAILED: approval needs an explicit 'approve anyway' while any of these remain."""
    checks = load_checks(record)
    out = []
    for name in CHECK_ORDER + ["edited_text"]:
        if name == "funding":
            continue  # funding is graded, never a failure of the email itself
        entry = get_check(checks, name)
        if entry.get("status") == FAILED:
            out.append(f"{LABELS[name]}: {entry.get('detail') or 'failed'}")
    return out


def attention(record: dict) -> list[str]:
    """Things to look at before approving: warnings, and required checks not run yet."""
    checks = load_checks(record)
    out = []
    for name in CHECK_ORDER + ["edited_text"]:
        if name == "funding":
            continue
        entry = get_check(checks, name)
        status = entry.get("status", NOT_CHECKED)
        if status == WARNING:
            out.append(f"{LABELS[name]}: {entry.get('detail') or 'needs a look'}")
        elif status == NOT_CHECKED and name in REQUIRED_FOR_VERIFIED:
            out.append(f"{LABELS[name]}: not checked yet")
    if not checks and clean(record.get("verification_status")) == m.VER_VERIFIED:
        out.append("Marked verified under the earlier, simpler rules (email only). Run verify again to check the research claims.")
    return out


def confirm_check(record: dict, name: str, source_url: str, today: date, note: str = "") -> dict:
    """You checked something yourself on an official page (or in the professor's reply): record it honestly."""
    from .errors import UserFacingError
    from .textutil import is_official_academic_host, is_valid_url, url_host

    if name not in {"profile", "research", "publication", "program", "funding"}:
        raise UserFacingError(f"'{name}' cannot be confirmed this way. Emails are confirmed with confirm-email.")
    if not is_valid_url(source_url):
        raise UserFacingError("Give the official web address where you checked it (it should start with https://).")
    if name != "publication" and not is_official_academic_host(url_host(source_url)):
        raise UserFacingError("Use the university's official (.edu) page as the source.")
    detail = f"Checked by you on {today.isoformat()}" + (f": {note.strip()}" if note.strip() else "")
    entry = set_check(record, name, CONFIRMED, today, url=source_url, detail=detail)
    apply_derived_status(record)
    return entry
