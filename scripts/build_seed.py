"""Merge the raw research files (data/research/raw/*.jsonl) into the seed files the tool uses:

    data/seed/professors_leads.csv   professor leads (status needs_verification)
    data/seed/programs.csv           graduate programs with funding / intake / English facts
    data/seed/COVERAGE.md            what was covered, by state

Every lead starts as `needs_verification`: the research was done with web-search
summaries (pages could not be opened from the research environment), so the tool's
`verify` command must confirm each official page and email on your own PC first.

Run from the project folder:  python scripts/build_seed.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import models as m  # noqa: E402
from src.dedupe import dedupe_records  # noqa: E402
from src.storage import write_csv  # noqa: E402
from src.textutil import clean, is_blank_or_unknown, join_multi, name_key, normalize_university, split_multi  # noqa: E402

RAW = ROOT / "data" / "research" / "raw"
SEED = ROOT / "data" / "seed"
STATES = (
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK "
    "OR PA RI SC SD TN TX UT VT VA WA WV WI WY"
).split()
UPDATABLE_PROGRAM_FIELDS = {
    "spring_2027_admission", "spring_2027_deadline", "spring_deadline_status", "fall_2027_deadline",
    "ielts_min_overall", "funding_summary", "assistantship_deadline", "international_eligible_for_assistantships",
}
PROGRAM_COLUMNS = [
    "university", "state", "program_name", "degree_level", "department_or_school", "program_url",
    "spring_2027_admission", "spring_2027_deadline", "spring_deadline_status", "fall_2027_deadline",
    "funding_deadline_note", "assistantship_deadline", "assistantship_types", "assistantship_covers",
    "international_eligible_for_assistantships", "funding_summary", "funding_source_url", "ielts_min_overall",
    "ielts_subscore_note", "toefl_min", "english_req_source_url", "gre_policy", "application_fee_usd",
    "advisor_contact_expected", "notes", "source_urls", "date_checked", "research_agent",
]

STOP_WORDS = {"university", "the", "of", "at", "and", "college", "campus", "main", "system"}
ALIASES = {
    "penn state": "pennsylvania state", "virginia tech": "virginia polytechnic", "ut austin": "texas austin",
    "uconn": "connecticut", "umass": "massachusetts", "unh": "new hampshire", "uga": "georgia",
    "ole miss": "mississippi", "lsu": "louisiana state", "unl": "nebraska lincoln", "asu": "arizona state",
    "uiuc": "illinois urbana champaign", "ufl": "florida", "utk": "tennessee knoxville", "msu": "michigan state",
    "uab": "alabama birmingham", "uncg": "north carolina greensboro", "unc": "north carolina", "unlv": "nevada las vegas",
    "ucsf": "california san francisco", "ucla": "california los angeles", "uc davis": "california davis",
    "uc berkeley": "california berkeley", "umn": "minnesota", "wsu": "washington state", "usu": "utah state",
    "csu": "colorado state", "isu": "iowa state", "ksu": "kansas state", "k state": "kansas state", "unh": "new hampshire",
}


def university_tokens(name: str) -> set[str]:
    text = normalize_university(name)
    for short, long in ALIASES.items():
        if text == short or text.startswith(short + " "):
            text = text.replace(short, long, 1)
    return {t for t in text.split() if t not in STOP_WORDS and len(t) > 2}


def same_university(a: str, b: str) -> bool:
    ta, tb = university_tokens(a), university_tokens(b)
    return bool(ta & tb)


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"WARNING: skipped bad JSON in {path.name} line {n}")
    return rows


def text(value) -> str:
    if isinstance(value, list):
        return join_multi([clean(v) for v in value if clean(v)])
    return clean(value)


def to_record(raw: dict) -> dict:
    rec = m.blank_record()
    for key in m.ALL_FIELDS:
        if key in raw:
            rec[key] = text(raw[key])
    rec["matched_topics"] = text(raw.get("matched_topics", ""))
    rec["source_urls"] = text(raw.get("source_urls", ""))
    funding = text(raw.get("funding_or_assistantship_evidence", ""))
    signal = text(raw.get("funding_signal", ""))
    if signal and not is_blank_or_unknown(signal) and not signal.lower().startswith("not verified"):
        funding = signal if is_blank_or_unknown(funding) or funding.lower().startswith("not verified") else f"{funding} | {signal}"
    rec["funding_or_assistantship_evidence"] = funding
    notes = [text(raw.get("confidence_notes", "")), text(raw.get("email_evidence", ""))]
    rec["notes"] = " | ".join(n for n in notes if n)
    rec["record_source"] = f"research:{text(raw.get('research_agent', ''))}".rstrip(":")
    rec["workflow_status"] = m.NEEDS_VERIFICATION
    rec["verification_status"] = m.VER_NOT
    rec["email_verification"] = m.EMAIL_SEEN_IN_SEARCH if rec["institutional_email"] else ""
    rec["record_id"] = ""
    rec["state"] = rec["state"].upper()[:2]
    if not rec["date_checked"]:
        rec["date_checked"] = "2026-10-11"
    return rec


def merge_into(base: dict, extra: dict) -> None:
    """Fill blanks in `base` from `extra`; keep a second publication; union sources and notes."""
    for key, value in extra.items():
        value = clean(value)
        if not value or key in {"record_id", "workflow_status", "verification_status"}:
            continue
        current = clean(base.get(key))
        if key in {"source_urls", "matched_topics"}:
            base[key] = join_multi(split_multi(current) + split_multi(value))
        elif key in {"notes", "funding_or_assistantship_evidence", "recruiting_evidence"}:
            if is_blank_or_unknown(current) or current.lower().startswith("not verified"):
                base[key] = value
            elif value not in current and not value.lower().startswith("not verified"):
                base[key] = f"{current} | {value}"
        elif key == "relevant_publication_1" and current and value.lower() != current.lower():
            if not clean(base.get("relevant_publication_2")):
                base["relevant_publication_2"] = value
                base["publication_2_url"] = clean(extra.get("publication_1_url"))
                base["publication_2_year"] = clean(extra.get("publication_1_year"))
        elif key in {"publication_1_url", "publication_1_year"} and current:
            continue
        elif not current or is_blank_or_unknown(current):
            base[key] = value


def best_program(programs: list[dict]) -> dict | None:
    """Prefer research degrees (PhD / thesis MS) with assistantship evidence."""
    def rank(p: dict):
        level = clean(p.get("degree_level")).lower()
        name = clean(p.get("program_name")).lower()
        research = ("phd" in level or "ph.d" in name or "thesis" in level or "ms" in level or "m.s" in name)
        online = "online" in name or "online" in clean(p.get("notes")).lower()
        funded = not is_blank_or_unknown(clean(p.get("funding_summary"))) and not clean(p.get("funding_summary")).lower().startswith("not verified")
        return (not research, online, not funded, "mph" in level)
    candidates = sorted(programs, key=rank)
    return candidates[0] if candidates else None


def program_to_professor_fields(program: dict) -> dict:
    fields: dict[str, str] = {}
    fields["graduate_program"] = text(program.get("program_name"))
    fields["program_url"] = text(program.get("program_url"))
    spring_admission = text(program.get("spring_2027_admission")).lower()
    spring_deadline = text(program.get("spring_2027_deadline"))
    spring_status = text(program.get("spring_deadline_status"))
    if spring_admission.startswith("no") or spring_status == "no_spring_admission":
        fields["spring_2027_status"] = "No spring admission (per program research)"
    elif spring_deadline and not is_blank_or_unknown(spring_deadline):
        fields["spring_2027_status"] = f"Spring deadline: {spring_deadline}" + (f" [{spring_status}]" if spring_status else "")
    fall = text(program.get("fall_2027_deadline"))
    if fall and not is_blank_or_unknown(fall):
        fields["fall_2027_status"] = f"Fall deadline: {fall}"
    ielts = text(program.get("ielts_min_overall"))
    english = []
    if ielts and not is_blank_or_unknown(ielts):
        english.append(f"IELTS {ielts} overall" + (f" ({text(program.get('ielts_subscore_note'))})" if text(program.get("ielts_subscore_note")) else ""))
    gre = text(program.get("gre_policy"))
    if gre and not is_blank_or_unknown(gre):
        english.append(f"GRE: {gre}")
    if english:
        fields["eligibility_notes"] = "; ".join(english) + " (program-level research)"
    funding = text(program.get("funding_summary"))
    if funding and not is_blank_or_unknown(funding) and not funding.lower().startswith("not verified"):
        fields["funding_or_assistantship_evidence"] = "Program-level: " + funding[:400]
    deadline = text(program.get("assistantship_deadline")) or text(program.get("funding_deadline_note"))
    if deadline and not is_blank_or_unknown(deadline):
        fields["application_deadline"] = deadline[:200]
    if text(program.get("advisor_contact_expected")).lower().startswith("no"):
        fields["notes"] = "Program research: the department discourages contacting faculty before review - do not cold-email."
    return fields


def main() -> int:
    raw_prof, raw_prog = [], []
    for path in sorted(RAW.glob("*_professors.jsonl")):
        raw_prof.extend(read_jsonl(path))
    for path in sorted(RAW.glob("*_programs.jsonl")):
        raw_prog.extend(read_jsonl(path))

    # ---------------- programs: merge duplicates by university + program name
    programs: dict[tuple[str, str], dict] = {}
    for p in raw_prog:
        key = (normalize_university(text(p.get("university"))), " ".join(text(p.get("program_name")).lower().split()))
        clean_p = {c: text(p.get(c, "")) for c in PROGRAM_COLUMNS}
        clean_p["state"] = clean_p["state"].upper()[:2]
        if key in programs:
            base = programs[key]
            newer = clean_p.get("research_agent", "")[:2] in {"w3", "w4"}  # later, more targeted checks win
            for c in PROGRAM_COLUMNS:
                incoming = clean_p[c]
                if not base.get(c) or is_blank_or_unknown(base.get(c, "")):
                    base[c] = incoming
                elif incoming and c in {"source_urls"}:
                    base[c] = join_multi(split_multi(base[c]) + split_multi(incoming))
                elif incoming and incoming != base[c] and not is_blank_or_unknown(incoming) and c in UPDATABLE_PROGRAM_FIELDS:
                    if newer:
                        base["notes"] = f"{base.get('notes', '')} | Earlier research said {c}={base[c]}".strip(" |")
                        base[c] = incoming
                    else:
                        base["notes"] = f"{base.get('notes', '')} | Another source says {c}={incoming}".strip(" |")
        else:
            programs[key] = clean_p
    program_rows = sorted(programs.values(), key=lambda p: (p["state"], p["university"], p["program_name"]))
    by_university: dict[str, list[dict]] = defaultdict(list)
    for p in program_rows:
        by_university[normalize_university(p["university"])].append(p)

    # ---------------- professors: merge enrichment records, attach program facts, dedupe
    by_name: dict[str, list[dict]] = defaultdict(list)
    records: list[dict] = []
    for raw in raw_prof:
        rec = to_record(raw)
        if not rec["professor_name"] or not rec["university"]:
            continue
        nk = name_key(rec["professor_name"])
        candidates = [r for r in by_name.get(nk, []) if same_university(r["university"], rec["university"])]
        if candidates:
            target = candidates[0]
            verified_now = "VERIFIED-CURRENT" in rec.get("notes", "")
            if verified_now:
                for key in ("title", "faculty_profile_url"):
                    if rec.get(key) and rec[key] != target.get(key):
                        if target.get(key):
                            target["notes"] = f"{target.get('notes', '')} | Updated {key} (was: {target[key]})".strip(" |")
                        target[key] = rec[key]
            merge_into(target, rec)
        else:
            by_name[nk].append(rec)
            records.append(rec)
    # Cross-check results: someone who moved, retired or is otherwise unavailable must not be drafted.
    for rec in records:
        note = rec.get("notes", "")
        if re.search(r"WARNING: (moved|retired|emerit|deceased|left|not taking)", note, re.IGNORECASE):
            rec["workflow_status"] = m.NOT_A_FIT
            rec["next_action"] = "Cross-check found this person may have moved/retired or is not taking students - do not contact unless you confirm otherwise."
    for rec in records:
        progs = by_university.get(normalize_university(rec["university"]), [])
        if not progs:
            for uk, plist in by_university.items():  # tolerate small naming differences
                if uk and (uk in normalize_university(rec["university"]) or normalize_university(rec["university"]) in uk):
                    progs = plist
                    break
        program = best_program(progs)
        if program:
            for key, value in program_to_professor_fields(program).items():
                current = clean(rec.get(key))
                if key == "notes":
                    rec["notes"] = f"{current} | {value}".strip(" |") if value not in current else current
                elif not current or is_blank_or_unknown(current) or current.lower().startswith("not verified"):
                    rec[key] = value
            if program.get("program_url"):
                rec["source_urls"] = join_multi(split_multi(rec["source_urls"]) + [program["program_url"]])
        if rec["workflow_status"] != m.NOT_A_FIT:
            rec["next_action"] = "Verify on the official page (python -m src.cli verify), then the pipeline can draft an email."
    result = dedupe_records(records)
    records = sorted(result.records, key=lambda r: (r["state"], r["university"], r["professor_name"]))
    for n, rec in enumerate(records, start=1):
        rec["record_id"] = f"R{n:04d}"

    SEED.mkdir(parents=True, exist_ok=True)
    write_csv(SEED / "professors_leads.csv", records, m.ALL_FIELDS)
    write_csv(SEED / "programs.csv", program_rows, PROGRAM_COLUMNS)

    # ---------------- coverage report
    prof_states = Counter(r["state"] for r in records)
    prog_states = Counter(p["state"] for p in program_rows)
    with_email = sum(1 for r in records if r["institutional_email"])
    with_pub = sum(1 for r in records if r["relevant_publication_1"])
    lines = [
        "# Research coverage",
        "",
        f"Built {date.today().isoformat()} from {len(raw_prof)} raw professor records and {len(raw_prog)} raw program records.",
        "",
        f"- Professor leads: **{len(records)}** (all `needs_verification`)",
        f"- Programs: **{len(program_rows)}**",
        f"- Leads with an email seen in search results (still to be confirmed on the official page): {with_email}",
        f"- Leads with a recent publication recorded: {with_pub}",
        f"- Duplicates merged: {sum(len(g.merged_ids) for g in result.merges)}",
        "",
        "| State | Professors | Programs |",
        "|---|---|---|",
    ]
    lines += [f"| {s} | {prof_states.get(s, 0)} | {prog_states.get(s, 0)} |" for s in STATES]
    missing = [s for s in STATES if prof_states.get(s, 0) == 0]
    lines += ["", f"States with no professor lead yet: {', '.join(missing) or 'none'}", ""]
    lines.append("All facts come from web-search results of official pages on 2026-10-11 and must be re-checked before use.")
    (SEED / "COVERAGE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} professor leads and {len(program_rows)} programs to {SEED}")
    print(f"States without professor leads: {', '.join(missing) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
