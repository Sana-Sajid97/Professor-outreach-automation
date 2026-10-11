"""Suppression list: people who must never be emailed again.

Anyone who opts out, asks not to be contacted, or whose email bounced is added
here (workspace/suppression_list.csv). Every drafting and sending step checks this
list first, so a suppressed person cannot be emailed by mistake even if their
record is imported again later.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from . import models as m
from .storage import read_csv_rows, write_csv
from .textutil import clean, name_key, normalize_email, normalize_university

COLUMNS = ["email", "professor_name", "university", "reason", "date_added", "notes"]
REASONS = {m.OPTED_OUT, m.BOUNCED, m.DO_NOT_CONTACT}


class SuppressionList:
    def __init__(self, entries: list[dict] | None = None):
        self.entries: list[dict] = entries or []
        self._rebuild()

    def _rebuild(self) -> None:
        self.emails = {normalize_email(e.get("email", "")): e for e in self.entries if normalize_email(e.get("email", ""))}
        self.people = {}
        for e in self.entries:
            nk, uk = name_key(e.get("professor_name", "")), normalize_university(e.get("university", ""))
            if nk and uk:
                self.people[f"{nk}|{uk}"] = e

    @classmethod
    def load(cls, path: Path) -> "SuppressionList":
        path = Path(path)
        if not path.exists():
            return cls([])
        rows, _ = read_csv_rows(path)
        return cls([{c: clean(r.get(c, "")) for c in COLUMNS} for r in rows])

    def save(self, path: Path) -> None:
        write_csv(Path(path), self.entries, COLUMNS)

    def lookup(self, record: dict) -> dict | None:
        email = normalize_email(record.get("institutional_email", ""))
        if email and email in self.emails:
            return self.emails[email]
        key = f"{name_key(record.get('professor_name', ''))}|{normalize_university(record.get('university', ''))}"
        return self.people.get(key)

    def is_suppressed(self, record: dict) -> bool:
        return self.lookup(record) is not None

    def add(self, record: dict, reason: str, today: date, notes: str = "") -> dict:
        if reason not in REASONS:
            raise ValueError(f"reason must be one of {sorted(REASONS)}")
        existing = self.lookup(record)
        if existing:
            return existing
        entry = {
            "email": normalize_email(record.get("institutional_email", "")),
            "professor_name": clean(record.get("professor_name")),
            "university": clean(record.get("university")),
            "reason": reason,
            "date_added": today.isoformat(),
            "notes": notes,
        }
        self.entries.append(entry)
        self._rebuild()
        return entry

    def apply(self, records: list[dict], today: date) -> int:
        """Mark matching records as suppressed. Returns the number of records changed."""
        changed = 0
        for record in records:
            entry = self.lookup(record)
            if not entry:
                continue
            reason = entry.get("reason") if entry.get("reason") in REASONS else m.DO_NOT_CONTACT
            if record.get("workflow_status") != reason:
                record["workflow_status"] = reason
                changed += 1
            record["opt_out_or_suppression"] = f"{reason} since {entry.get('date_added') or today.isoformat()}"
            record["next_action"] = "Do not contact."
            record["email_draft"] = record.get("email_draft", "")
            record["approval_hash"] = ""
        return changed

    @property
    def email_set(self) -> set[str]:
        return set(self.emails)
