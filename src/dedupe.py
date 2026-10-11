"""Find and merge duplicate professor records.

Two records are the SAME person when they share any of:
  1. the institutional email,
  2. the faculty profile URL (after normalising),
  3. the name (first + last) together with the university.

Very similar names at the same university (e.g. a typo) are only *flagged* as
"possible duplicates" for a human to decide; they are never merged automatically.
Merging never loses outreach history: the record furthest along the workflow
(for example 'sent') is kept as the main record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .models import STATUS_RANK
from .textutil import (
    clean,
    join_multi,
    name_key,
    name_tokens,
    normalize_email,
    normalize_university,
    normalize_url,
    split_multi,
)

MULTI_VALUE_FIELDS = {"source_urls", "matched_topics"}
APPEND_FIELDS = {"notes"}
NEVER_COPY = {"record_id", "duplicate_of"}


@dataclass
class MergeGroup:
    kept_id: str
    merged_ids: list[str]
    reasons: list[str]
    conflicts: list[str] = field(default_factory=list)


@dataclass
class DedupeResult:
    records: list[dict]
    merges: list[MergeGroup]
    possible: list[tuple[str, str, str]]  # (id_a, id_b, reason): similar names, maybe the same person
    shared: list[tuple[str, str, str]] = field(default_factory=list)  # different people sharing a URL/email


def _keys(record: dict) -> list[tuple[str, str]]:
    keys = []
    email = normalize_email(record.get("institutional_email", ""))
    if email:
        keys.append(("email", email))
    url = clean(record.get("faculty_profile_url"))
    if url:
        keys.append(("url", normalize_url(url)))
    nk, uk = name_key(record.get("professor_name", "")), normalize_university(record.get("university", ""))
    if nk and uk:
        keys.append(("name+university", f"{nk}|{uk}"))
    return keys


def names_compatible(a: str, b: str) -> bool:
    """Could these two names belong to the same person? (same surname + same first name or initial)"""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return True  # a missing name can't contradict
    if ta[-1] != tb[-1]:
        return False
    fa, fb = ta[0], tb[0]
    return fa == fb or (len(fa) == 1 and fb.startswith(fa)) or (len(fb) == 1 and fa.startswith(fb))


def _completeness(record: dict) -> int:
    return sum(1 for v in record.values() if clean(v))


def _choose_primary(group: list[dict]) -> dict:
    return max(
        group,
        key=lambda r: (STATUS_RANK.get(clean(r.get("workflow_status")), 0), _completeness(r), -group.index(r)),
    )


def merge_group(group: list[dict]) -> tuple[dict, list[str]]:
    """Merge records describing the same person. Returns (merged_record, conflict_notes)."""
    chosen = _choose_primary(group)
    primary = dict(chosen)
    conflicts: list[str] = []
    others = [r for r in group if r is not chosen]  # by identity: records may not have ids yet
    for other in others:
        for key, value in other.items():
            value = clean(value)
            if not value or key in NEVER_COPY:
                continue
            current = clean(primary.get(key))
            if key in MULTI_VALUE_FIELDS:
                primary[key] = join_multi(split_multi(current) + split_multi(value))
            elif key in APPEND_FIELDS:
                if value not in current:
                    primary[key] = f"{current} | {value}".strip(" |")
            elif not current:
                primary[key] = value
            elif key == "institutional_email" and normalize_email(current) != normalize_email(value):
                conflicts.append(f"different email in {other.get('record_id')}: {value}")
    ids = ", ".join(clean(r.get("record_id")) for r in others if clean(r.get("record_id")))
    if ids:
        note = f"Merged duplicate record(s): {ids}."
        if conflicts:
            note += " CHECK: " + "; ".join(conflicts)
        primary["notes"] = f"{clean(primary.get('notes'))} | {note}".strip(" |")
    return primary, conflicts


def find_duplicates(records: list[dict]) -> DedupeResult:
    """Group duplicates (union-find over shared keys), merge them, and flag near-duplicates."""
    parent = list(range(len(records)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    owners: dict[tuple[str, str], list[int]] = {}
    reasons: dict[frozenset, set[str]] = {}
    shared_conflicts: list[tuple[int, int, str]] = []
    for i, record in enumerate(records):
        for key in _keys(record):
            for j in owners.get(key, []):
                if key[0] == "name+university" or names_compatible(records[j].get("professor_name", ""), record.get("professor_name", "")):
                    union(j, i)
                    reasons.setdefault(frozenset((j, i)), set()).add(key[0])
                else:
                    # A department roster URL or shared office email used for two different people: never merge.
                    shared_conflicts.append((j, i, key[0]))
            owners.setdefault(key, []).append(i)

    groups: dict[int, list[int]] = {}
    for i in range(len(records)):
        groups.setdefault(find(i), []).append(i)

    merged_records: list[dict] = []
    merges: list[MergeGroup] = []
    for root in sorted(groups, key=lambda r: min(groups[r])):
        members = groups[root]
        if len(members) == 1:
            merged_records.append(records[members[0]])
            continue
        group = [records[i] for i in members]
        merged, conflicts = merge_group(group)
        why = set()
        for a in members:
            for b in members:
                why |= reasons.get(frozenset((a, b)), set())
        merged_records.append(merged)
        merges.append(
            MergeGroup(
                kept_id=clean(merged.get("record_id")),
                merged_ids=[clean(records[i].get("record_id")) for i in members if records[i] is not merged and clean(records[i].get("record_id")) != clean(merged.get("record_id"))],
                reasons=sorted(why),
                conflicts=conflicts,
            )
        )

    possible = find_possible_duplicates(merged_records)
    shared = []
    for j, i, kind in shared_conflicts:
        a, b = records[j], records[i]
        if find(i) == find(j):
            continue
        what = "profile URL" if kind == "url" else "email"
        shared.append((clean(a.get("record_id")), clean(b.get("record_id")), what))
    return DedupeResult(merged_records, merges, possible, shared)


def find_possible_duplicates(records: list[dict], threshold: float = 0.88) -> list[tuple[str, str, str]]:
    """Similar names at the same university (not merged; for human review)."""
    by_univ: dict[str, list[dict]] = {}
    for record in records:
        by_univ.setdefault(normalize_university(record.get("university", "")), []).append(record)
    flagged = []
    for univ, group in by_univ.items():
        if not univ or len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = name_key(group[i].get("professor_name", "")), name_key(group[j].get("professor_name", ""))
                if not a or not b or a == b:
                    continue
                ratio = SequenceMatcher(None, a, b).ratio()
                same_last = a.split()[-1] == b.split()[-1]
                if ratio >= threshold or (same_last and a[0] == b[0]):
                    flagged.append(
                        (
                            clean(group[i].get("record_id")),
                            clean(group[j].get("record_id")),
                            f"similar names at the same university ({group[i].get('professor_name')} / {group[j].get('professor_name')})",
                        )
                    )
    return flagged


def dedupe_records(records: list[dict]) -> DedupeResult:
    result = find_duplicates(records)
    by_id = {clean(r.get("record_id")): r for r in result.records if clean(r.get("record_id"))}
    for id_a, id_b, reason in result.possible:
        record = by_id.get(id_b)
        if record is not None and not clean(record.get("duplicate_of")):
            record["duplicate_of"] = f"possible duplicate of {id_a} - {reason}"
    shared_note = "Shared department page: this {what} is also listed for other professors; find this person's own profile page."
    for id_a, id_b, what in result.shared:
        for rid in (id_a, id_b):
            record = by_id.get(rid)
            if record is not None:
                note = shared_note.format(what=what)
                if note not in clean(record.get("notes")):
                    record["notes"] = f"{clean(record.get('notes'))} | {note}".strip(" |")
    return result
