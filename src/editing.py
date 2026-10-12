"""Editing a draft by hand: recipient, subject and body, with the same safety rules as everything else.

- Only emails that are not sent yet (draft ready or approved) can be edited.
- Changing the recipient needs the official page where you saw the new address; it is then recorded
  as "confirmed by you", exactly like confirm-email.
- Editing an approved email cancels the approval: you approve the new text again.
- Your edited text is kept: drafting never overwrites it (unless you ask with --discard-edits).
- Sentences about the professor ("your research on ...") are re-checked against the saved copy of their
  official page, and words that do not appear there are flagged for you to double-check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import checks as ck
from . import models as m
from .textutil import (
    clean,
    collapse_spaces,
    email_domain,
    is_generic_email,
    is_official_academic_host,
    is_valid_email,
    is_valid_url,
    join_multi,
    normalize_email,
    split_multi,
    url_host,
)

MAX_SUBJECT = 150
LONG_BODY_WORDS = 300


@dataclass
class EditResult:
    changed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    approval_cancelled: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors


def normalize_body(text: str) -> str:
    """Browser text boxes send Windows line endings; keep the email tidy."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def body_word_count(body: str) -> int:
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    inner = paragraphs[1:-1] if len(paragraphs) > 2 else paragraphs  # greeting and signature not counted
    return sum(len(p.split()) for p in inner)


def recheck_edited_text(record: dict, today: date, evidence_dir: Path | None) -> None:
    """Flag words in sentences about the professor that their official page does not contain."""
    from .evidence import load_snapshot
    from .page_facts import unsupported_claim_words

    texts = []
    for field_name in ("faculty_profile_url", "lab_url", "email_source_url"):
        snap = load_snapshot(evidence_dir, clean(record.get(field_name)))
        if snap:
            texts.append(snap[0])
    if not texts:
        ck.set_check(record, "edited_text", ck.NOT_CHECKED, today,
                     detail="Your edits could not be compared with the official page (no saved copy yet: run verify first).")
        return
    titles = " ".join(clean(record.get(f"relevant_publication_{n}")) for n in (1, 2))
    text = clean(record.get("email_subject")) + "\n" + (record.get("email_draft", "") or "")
    missing = unsupported_claim_words(text, " ".join(texts), titles)
    if missing:
        ck.set_check(record, "edited_text", ck.WARNING, today, url=clean(record.get("faculty_profile_url")),
                     detail="In sentences about the professor, these words are not on their official page: "
                     + ", ".join(missing[:10]) + ". Make sure each claim is true before approving.",
                     words=missing[:20])
    else:
        ck.set_check(record, "edited_text", ck.PASSED, today, url=clean(record.get("faculty_profile_url")),
                     detail="Your sentences about the professor only use words found on their official page.")


def apply_edit(record: dict, to: str, subject: str, body: str, today: date, email_source_url: str = "",
               evidence_dir: Path | None = None) -> EditResult:
    """Validate and apply a hand edit. Nothing changes when there are errors."""
    from .tracker import set_status
    from .validate import PLACEHOLDER_RE

    result = EditResult()
    status = clean(record.get("workflow_status"))
    if status not in {m.DRAFT_READY, m.APPROVED}:
        result.errors.append(f"Only emails that are not sent yet can be edited (this one is '{status}').")
        return result
    new_to = normalize_email(to)
    new_subject = collapse_spaces(subject)
    new_body = normalize_body(body)
    source = clean(email_source_url)
    email_changed = new_to != normalize_email(record.get("institutional_email", ""))

    if not is_valid_email(new_to):
        result.errors.append(f"'{clean(to)}' is not a valid email address.")
    elif is_generic_email(new_to):
        result.errors.append("That looks like a department or office address. Use the professor's own address.")
    elif not email_domain(new_to).endswith(".edu"):
        result.errors.append("Use the professor's institutional (.edu) address.")
    elif email_changed and not (is_valid_url(source) and is_official_academic_host(url_host(source))):
        result.errors.append("You changed the email address: paste the official university (.edu) page where you saw it, so it can be checked.")
    if not new_subject:
        result.errors.append("The subject line is empty.")
    elif len(new_subject) > MAX_SUBJECT:
        result.errors.append(f"The subject line is too long ({len(new_subject)} characters; keep it under {MAX_SUBJECT}).")
    if not new_body:
        result.errors.append("The email text is empty.")
    for text in (new_subject, new_body):
        hit = PLACEHOLDER_RE.search(text)
        if hit:
            result.errors.append(f"Replace the placeholder '{hit.group(0)}' first.")
            break
    if result.errors:
        return result

    if new_to != normalize_email(record.get("institutional_email", "")):
        result.changed.append("recipient")
    if new_subject != clean(record.get("email_subject")):
        result.changed.append("subject")
    if new_body != normalize_body(record.get("email_draft", "")):
        result.changed.append("email text")
    if not result.changed:
        result.warnings.append("Nothing changed.")
        return result

    if email_changed:
        record["institutional_email"] = new_to
        record["email_source_url"] = source
        record["email_verification"] = m.EMAIL_CONFIRMED_MANUALLY
        record["source_urls"] = join_multi(split_multi(record.get("source_urls", "")) + [source])
        ck.set_check(record, "email", ck.CONFIRMED, today, url=source, detail=f"{new_to}: changed by you; seen on {source}.")
    record["email_subject"] = new_subject
    record["email_draft"] = new_body
    if status == m.APPROVED:
        set_status(record, m.DRAFT_READY, today)
        result.approval_cancelled = True
    record["approval_hash"] = ""
    record["approved_on"] = ""
    record["draft_edited_on"] = today.isoformat()
    record["next_action"] = "Edited by you. Review it once more, then approve it (5_approve_drafts.bat)."
    words = body_word_count(new_body)
    if words > LONG_BODY_WORDS:
        result.warnings.append(f"The email is {words} words long. Professors often skim: under 220 words works best.")
    if result.changed:
        recheck_edited_text(record, today, evidence_dir)
        entry = ck.get_check(ck.load_checks(record), "edited_text")
        if entry.get("status") == ck.WARNING:
            result.warnings.append(entry.get("detail", ""))
    if result.approval_cancelled:
        result.warnings.append("This email was approved before. Your edit cancelled the approval: approve the new text again.")
    return result
