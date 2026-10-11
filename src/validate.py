"""Validate professor records before they are used for outreach.

Errors block a record from moving forward (drafting, approval, sending).
Warnings are shown so a human can double-check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from . import models as m
from .textutil import (
    clean,
    collapse_spaces,
    email_domain,
    find_dates,
    is_blank_or_unknown,
    is_generic_email,
    is_official_academic_host,
    is_valid_email,
    is_valid_url,
    meaningful,
    normalize_email,
    parse_iso,
    registrable_domain,
    split_multi,
    url_host,
)

PLACEHOLDER_RE = re.compile(r"\{\{|\}\}|\[(?:your|insert|add|todo|tbd|professor|name)[^\]]*\]|lorem ipsum|xxx", re.IGNORECASE)
FAKE_DOMAIN_RE = re.compile(r"(^|\.)(example\.(com|org|net|edu)|test|invalid|localhost)$", re.IGNORECASE)
STALE_AFTER_DAYS = 180
MAX_DRAFT_WORDS = 300


@dataclass
class Issue:
    record_id: str
    field: str
    severity: str  # "error" or "warning"
    message: str

    def __str__(self) -> str:  # pragma: no cover - formatting helper
        return f"[{self.severity.upper()}] {self.record_id} {self.field}: {self.message}"


def ielts_minimum(text: str) -> float | None:
    """Find an IELTS overall minimum in free text such as 'IELTS 6.5 overall' or 'IELTS: 7.0'."""
    match = re.search(r"IELTS[^0-9]{0,40}?([5-9](?:\.[05])?)\b", text or "", re.IGNORECASE)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value if 4.0 <= value <= 9.0 else None


def contact_discouraged(record: dict) -> bool:
    text = " ".join(clean(record.get(f, "")) for f in ("eligibility_notes", "notes", "recruiting_evidence")).lower()
    return bool(
        re.search(r"discourag\w*[^.]{0,80}contact", text)
        or re.search(r"do not (?:cold[- ]?)?(?:email|contact)", text)
        or "do_not_cold_email" in text
    )


def validate_record(
    record: dict,
    today: date,
    suppressed_emails: set[str] | None = None,
    applicant_ielts: float | None = None,
) -> list[Issue]:
    rid = record.get("record_id") or "(no id)"
    issues: list[Issue] = []

    def add(field: str, severity: str, message: str) -> None:
        issues.append(Issue(rid, field, severity, message))

    status = clean(record.get("workflow_status"))
    vstatus = clean(record.get("verification_status"))
    advanced = status in {m.VERIFIED, m.DRAFT_READY, m.APPROVED}

    # ---- required identity fields
    if not clean(record.get("professor_name")):
        add("professor_name", "error", "Professor name is missing.")
    if not clean(record.get("university")):
        add("university", "error", "University is missing.")

    # ---- statuses
    if status not in m.WORKFLOW_STATUSES:
        add("workflow_status", "error", f"Unknown status '{status}'. Use one of: {', '.join(m.WORKFLOW_STATUSES)}.")
    if vstatus not in m.VERIFICATION_STATUSES:
        add("verification_status", "error", f"Unknown verification status '{vstatus}'. Use: {', '.join(m.VERIFICATION_STATUSES)}.")
    if advanced and vstatus != m.VER_VERIFIED:
        add("verification_status", "error", f"Status is '{status}' but the record is not verified yet. Run 'verify' or confirm the email manually.")

    # ---- profile URL
    profile_url = clean(record.get("faculty_profile_url"))
    if not profile_url:
        add("faculty_profile_url", "error" if advanced else "warning", "Official faculty profile URL is missing.")
    elif not is_valid_url(profile_url):
        add("faculty_profile_url", "error", f"Not a valid web address: {profile_url}")
    else:
        host = url_host(profile_url)
        if FAKE_DOMAIN_RE.search(host) and clean(record.get("record_source")) != "sample":
            add("faculty_profile_url", "error", f"'{host}' is a placeholder/test domain, not a real university site.")
        elif not is_official_academic_host(host):
            add("faculty_profile_url", "warning", f"'{host}' is not a .edu address. Confirm it is the official university or institute site.")
        if profile_url.lower().startswith("http://"):
            add("faculty_profile_url", "warning", "Uses http:// instead of https://.")

    # ---- email
    email = normalize_email(record.get("institutional_email", ""))
    if email:
        if not is_valid_email(email):
            add("institutional_email", "error", f"'{record.get('institutional_email')}' is not a valid email address.")
        else:
            domain = email_domain(email)
            if FAKE_DOMAIN_RE.search(domain) and clean(record.get("record_source")) != "sample":
                add("institutional_email", "error", f"'{domain}' is a placeholder/test domain.")
            elif not domain.endswith(".edu"):
                add("institutional_email", "warning", f"Email domain '{domain}' is not .edu. Confirm it is an official institutional address.")
            if is_generic_email(email):
                add("institutional_email", "warning", f"'{email}' looks like a general office address, not the professor's own email.")
            if profile_url and is_valid_url(profile_url):
                if registrable_domain(domain) != registrable_domain(url_host(profile_url)):
                    add(
                        "institutional_email",
                        "warning",
                        f"Email domain '{domain}' does not match the profile site '{registrable_domain(url_host(profile_url))}'.",
                    )
        source = clean(record.get("email_source_url"))
        if not source:
            add("email_source_url", "warning", "Where was this email found? Add the official page URL (email_source_url).")
        elif not is_valid_url(source):
            add("email_source_url", "error", f"Not a valid web address: {source}")
        elif not is_official_academic_host(url_host(source)):
            add("email_source_url", "warning", "The email source is not a .edu page. Confirm it on the official university site.")
        method = clean(record.get("email_verification"))
        if (advanced or status == m.SENT) and method not in m.TRUSTED_EMAIL_METHODS | {m.EMAIL_SAMPLE}:
            add("email_verification", "error", "Email has not been confirmed on an official page. Run 'verify' or 'confirm-email'.")
    elif advanced:
        add("institutional_email", "error", "Email is missing, so this record cannot be drafted or sent.")

    if suppressed_emails and email and email in suppressed_emails and status not in m.SUPPRESSED_STATUSES:
        add("workflow_status", "error", "This email is on the suppression list (opt-out/bounce/do-not-contact) but the record is still active.")

    # ---- other URLs
    for field in m.URL_FIELDS:
        if field in {"faculty_profile_url", "email_source_url"}:
            continue
        value = clean(record.get(field))
        if value and not is_valid_url(value):
            add(field, "warning", f"Not a valid web address: {value}")
    bad_sources = [u for u in split_multi(record.get("source_urls", "")) if not is_valid_url(u)]
    if bad_sources:
        add("source_urls", "warning", f"{len(bad_sources)} entry(ies) are not web addresses: {bad_sources[0][:80]}")
    if not split_multi(record.get("source_urls", "")) and not profile_url:
        add("source_urls", "warning", "No source URLs recorded. Every fact should be traceable to a source.")

    # ---- dates
    checked = clean(record.get("date_checked"))
    if checked:
        d = parse_iso(checked)
        if not d:
            add("date_checked", "warning", f"Use the format YYYY-MM-DD (found '{checked}').")
        elif d > today:
            add("date_checked", "warning", "date_checked is in the future.")
        elif (today - d).days > STALE_AFTER_DAYS:
            add("date_checked", "warning", f"Information was last checked {(today - d).days} days ago. Re-verify before contacting.")
    elif advanced:
        add("date_checked", "warning", "No date_checked recorded.")
    for field_name in ("follow_up_date", "last_contact_date", "approved_on"):
        value = clean(record.get(field_name))
        if value and not parse_iso(value):
            add(field_name, "warning", f"The date '{value}' cannot be read safely (day or month first?). Write it as YYYY-MM-DD"
                + (" - follow-up reminders do not work for this record until then." if field_name == "follow_up_date" else "."))

    # ---- research evidence
    if not meaningful(record.get("research_interests", "")) and (advanced or status == m.NEEDS_VERIFICATION):
        add("research_interests", "error" if advanced else "warning", "Research interests are missing; the email cannot be personalised.")

    # ---- drafts
    if status in {m.DRAFT_READY, m.APPROVED}:
        subject, body = clean(record.get("email_subject")), clean(record.get("email_draft"))
        if not subject or not body:
            add("email_draft", "error", "Status says a draft exists, but the subject or body is empty.")
        for field, text in (("email_subject", subject), ("email_draft", body)):
            if text and PLACEHOLDER_RE.search(text):
                add(field, "error", "The draft still contains a placeholder such as [..] or {{..}}. Edit it before approving.")
        if body and len(body.split()) > MAX_DRAFT_WORDS:
            add("email_draft", "warning", f"The draft has {len(body.split())} words. Professors prefer short emails (under about 250 words).")
    if status == m.APPROVED and clean(record.get("approval_hash")):
        from .drafting import draft_hash  # local import avoids a cycle

        if draft_hash(record) != clean(record.get("approval_hash")):
            add("approval_hash", "error", "The email was changed after you approved it. Approve it again before sending.")

    # ---- scores
    score = clean(record.get("fit_score"))
    if score:
        try:
            value = float(score)
            if not 0 <= value <= 10:
                add("fit_score", "warning", "Fit score should be between 0 and 10.")
        except ValueError:
            add("fit_score", "warning", f"Fit score '{score}' is not a number.")

    # ---- eligibility and contact policy
    if applicant_ielts is not None:
        minimum = ielts_minimum(" ".join(clean(record.get(f, "")) for f in ("eligibility_notes", "notes")))
        if minimum is not None and minimum > applicant_ielts:
            add("eligibility_notes", "warning", f"Program asks for IELTS {minimum:g}, above your {applicant_ielts:g}. Check for exceptions or plan a retake.")
    if contact_discouraged(record):
        add("notes", "warning", "Sources say this department discourages contacting faculty before review. Do not cold-email.")
    spring = clean(record.get("spring_2027_status"))
    if spring and not is_blank_or_unknown(spring):
        past = [d for d in find_dates(spring) if d < today]
        if past and "passed" not in spring.lower() and not [d for d in find_dates(spring) if d >= today]:
            add("spring_2027_status", "warning", f"The Spring 2027 date ({past[0].isoformat()}) appears to have passed.")
    return issues


def validate_all(
    records: list[dict],
    today: date,
    suppressed_emails: set[str] | None = None,
    applicant_ielts: float | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    seen_ids: dict[str, int] = {}
    for record in records:
        rid = clean(record.get("record_id"))
        if rid:
            seen_ids[rid] = seen_ids.get(rid, 0) + 1
        issues.extend(validate_record(record, today, suppressed_emails, applicant_ielts))
    for rid, count in seen_ids.items():
        if count > 1:
            issues.append(Issue(rid, "record_id", "error", f"record_id {rid} is used {count} times."))
    from .textutil import name_key, normalize_url

    active_by_email: dict[str, list[str]] = {}
    for record in records:
        email = normalize_email(record.get("institutional_email", ""))
        if email and clean(record.get("workflow_status")) not in m.SUPPRESSED_STATUSES | {m.CLOSED, m.NOT_A_FIT}:
            active_by_email.setdefault(email, []).append(clean(record.get("record_id")) or "(no id)")
    for email, ids in active_by_email.items():
        if len(ids) > 1:
            for rid in ids:
                issues.append(Issue(rid, "institutional_email", "error",
                                    f"{email} is used by {len(ids)} active records ({', '.join(ids)}). Merge them (dedupe) "
                                    "or close one, so nobody gets the same email twice."))

    by_url: dict[str, set[str]] = {}
    for record in records:
        url = clean(record.get("faculty_profile_url"))
        if url:
            by_url.setdefault(normalize_url(url), set()).add(name_key(record.get("professor_name", "")))
    for record in records:
        url = clean(record.get("faculty_profile_url"))
        if url and len(by_url.get(normalize_url(url), set())) > 1:
            issues.append(
                Issue(
                    clean(record.get("record_id")) or "(no id)",
                    "faculty_profile_url",
                    "warning",
                    f"This URL is also used for {len(by_url[normalize_url(url)]) - 1} other professor(s); it is probably a "
                    "department list. Add this person's own profile page if one exists.",
                )
            )
    return issues


def has_errors(issues: list[Issue], record_id: str) -> bool:
    return any(i.severity == "error" and i.record_id == record_id for i in issues)


def issues_by_record(issues: list[Issue]) -> dict[str, list[Issue]]:
    grouped: dict[str, list[Issue]] = {}
    for issue in issues:
        grouped.setdefault(issue.record_id, []).append(issue)
    return grouped


def summarize_issues(issues: list[Issue]) -> str:
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warning")
    records = len({i.record_id for i in issues})
    return f"{errors} error(s) and {warnings} warning(s) across {records} record(s)."


def word_count(text: str) -> int:
    return len(collapse_spaces(text).split())
