"""Record fields and workflow statuses.

A "record" is one professor (one row in the tracker). Records are plain
dictionaries whose keys are the column names below, so they map 1:1 onto the
CSV/Excel files a non-programmer can open.
"""

from __future__ import annotations

from .errors import TransitionError

# Columns from professors_template.csv (kept in exactly this order).
TEMPLATE_FIELDS = [
    "record_id",
    "professor_name",
    "title",
    "university",
    "state",
    "department_or_school",
    "faculty_profile_url",
    "institutional_email",
    "email_source_url",
    "lab_url",
    "research_interests",
    "relevant_publication_1",
    "publication_1_url",
    "relevant_publication_2",
    "publication_2_url",
    "research_fit_explanation",
    "graduate_program",
    "program_url",
    "spring_2027_status",
    "fall_2027_status",
    "recruiting_evidence",
    "funding_or_assistantship_evidence",
    "application_deadline",
    "eligibility_notes",
    "email_subject",
    "email_draft",
    "source_urls",
    "date_checked",
    "verification_status",
    "fit_score",
    "workflow_status",
    "last_contact_date",
    "reply_status",
    "opt_out_or_suppression",
    "next_action",
    "notes",
]

# Extra columns added by this tool (appended after the template columns).
EXTRA_FIELDS = [
    "publication_1_year",
    "publication_2_year",
    "matched_topics",
    "fit_score_breakdown",
    "email_verification",
    "personal_note",
    "follow_up_date",
    "follow_up_count",
    "approved_on",
    "approval_hash",
    "duplicate_of",
    "record_source",
]

ALL_FIELDS = TEMPLATE_FIELDS + EXTRA_FIELDS

URL_FIELDS = [
    "faculty_profile_url",
    "email_source_url",
    "lab_url",
    "publication_1_url",
    "publication_2_url",
    "program_url",
]

# ---------------- workflow statuses ----------------
DISCOVERED = "discovered"
NEEDS_VERIFICATION = "needs_verification"
VERIFIED = "verified"
DRAFT_READY = "draft_ready"
APPROVED = "approved"
SENT = "sent"
FOLLOW_UP_DUE = "follow_up_due"
REPLIED = "replied"
CLOSED = "closed"
NOT_A_FIT = "not_a_fit"
BOUNCED = "bounced"
OPTED_OUT = "opted_out"
DO_NOT_CONTACT = "do_not_contact"

WORKFLOW_STATUSES = [
    DISCOVERED,
    NEEDS_VERIFICATION,
    VERIFIED,
    DRAFT_READY,
    APPROVED,
    SENT,
    FOLLOW_UP_DUE,
    REPLIED,
    CLOSED,
    NOT_A_FIT,
    BOUNCED,
    OPTED_OUT,
    DO_NOT_CONTACT,
]

SUPPRESSED_STATUSES = {BOUNCED, OPTED_OUT, DO_NOT_CONTACT}
CONTACTED_STATUSES = {SENT, FOLLOW_UP_DUE, REPLIED, CLOSED}

# Normal forward moves. Suppression (bounced / opted_out / do_not_contact) is
# always allowed from any status and is handled separately.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    DISCOVERED: {NEEDS_VERIFICATION, VERIFIED, NOT_A_FIT},
    NEEDS_VERIFICATION: {VERIFIED, NOT_A_FIT, DISCOVERED},
    VERIFIED: {DRAFT_READY, NEEDS_VERIFICATION, NOT_A_FIT},
    DRAFT_READY: {APPROVED, VERIFIED, NEEDS_VERIFICATION, NOT_A_FIT},
    APPROVED: {SENT, DRAFT_READY, NEEDS_VERIFICATION, NOT_A_FIT},
    SENT: {REPLIED, FOLLOW_UP_DUE, CLOSED},
    FOLLOW_UP_DUE: {DRAFT_READY, REPLIED, CLOSED},  # a follow-up is drafted, then approved like any email
    REPLIED: {CLOSED},
    CLOSED: {REPLIED},
    NOT_A_FIT: {NEEDS_VERIFICATION},
    BOUNCED: {NEEDS_VERIFICATION},  # only after the email address is corrected
    OPTED_OUT: set(),
    DO_NOT_CONTACT: set(),
}

# How "far along" a status is; used to keep the most advanced record when merging duplicates.
STATUS_RANK = {
    DISCOVERED: 0,
    NEEDS_VERIFICATION: 1,
    NOT_A_FIT: 1,
    VERIFIED: 2,
    DRAFT_READY: 3,
    APPROVED: 4,
    SENT: 5,
    FOLLOW_UP_DUE: 6,
    REPLIED: 7,
    CLOSED: 7,
    BOUNCED: 8,
    OPTED_OUT: 9,
    DO_NOT_CONTACT: 9,
}

# ---------------- verification statuses ----------------
VER_VERIFIED = "verified"  # official profile + institutional email confirmed on an official page
VER_PARTIAL = "partially_verified"  # official profile confirmed, email (or another key fact) not yet
VER_NOT = "not_verified"
VERIFICATION_STATUSES = [VER_VERIFIED, VER_PARTIAL, VER_NOT]

# How the email was confirmed (column email_verification)
EMAIL_FOUND_ON_PAGE = "found_on_official_page"
EMAIL_CONFIRMED_MANUALLY = "confirmed_manually"
EMAIL_SEEN_IN_SEARCH = "seen_in_search_result"
EMAIL_NOT_FOUND = "not_found_on_page"
EMAIL_SAMPLE = "sample_data"
TRUSTED_EMAIL_METHODS = {EMAIL_FOUND_ON_PAGE, EMAIL_CONFIRMED_MANUALLY}


def blank_record() -> dict[str, str]:
    return {name: "" for name in ALL_FIELDS}


def normalize_record(raw: dict) -> dict[str, str]:
    """Return a record with every known column present (as text) plus any extra columns kept."""
    record = blank_record()
    for key, value in raw.items():
        if key is None:
            continue
        key = str(key).strip().lstrip("﻿")
        if not key:
            continue
        record[key] = _to_text(value)
    if not record.get("workflow_status"):
        record["workflow_status"] = DISCOVERED
    if not record.get("verification_status"):
        record["verification_status"] = VER_NOT
    return record


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value != value:  # NaN
            return ""
        if value.is_integer():
            return str(int(value))
    if isinstance(value, (list, tuple)):
        return "; ".join(_to_text(v) for v in value if _to_text(v))
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            return value.isoformat()[:10]
        except Exception:  # pragma: no cover - defensive
            pass
    return str(value).strip()


def is_suppressed_status(status: str) -> bool:
    return status in SUPPRESSED_STATUSES


def check_transition(current: str, new: str) -> None:
    """Raise TransitionError if a record may not move from `current` to `new`."""
    if new not in WORKFLOW_STATUSES:
        raise TransitionError(
            f"'{new}' is not a valid status. Valid statuses: {', '.join(WORKFLOW_STATUSES)}"
        )
    if current not in WORKFLOW_STATUSES:
        # Unknown/legacy status: allow moving to a valid one.
        return
    if new == current:
        return
    if new in SUPPRESSED_STATUSES:
        return
    if new not in ALLOWED_TRANSITIONS.get(current, set()):
        allowed = sorted(ALLOWED_TRANSITIONS.get(current, set()) | SUPPRESSED_STATUSES)
        raise TransitionError(
            f"A record that is '{current}' cannot be changed to '{new}'. "
            f"Allowed next statuses: {', '.join(allowed)}."
        )
