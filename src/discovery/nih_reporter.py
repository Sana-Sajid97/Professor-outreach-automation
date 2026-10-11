"""Funding evidence from NIH RePORTER (official API, no key needed).

An ACTIVE NIH grant led by a professor is good evidence that money for a graduate
research assistant may exist. It is NOT proof that a position is open, so the
email still asks politely.

Endpoint: POST https://api.reporter.nih.gov/v2/projects/search
NIH asks API users to keep to about one request per second and to run large jobs
off-peak; the polite client spaces requests out automatically.
Checked against NIH's API documentation (Oct 2026): criteria.pi_names takes objects with
first_name / last_name / any_name; fiscal_years is a list of integers; include_active_projects
is a boolean; limit is at most 500; and NIH asks for no more than one request per second, with
large jobs run on weekends or overnight (US Eastern).
NOTE: it could not be tested against the live API from the cloud build environment.
Run `python -m src.cli check-funding --limit 3` once to confirm it works.
"""

from __future__ import annotations

import re
from datetime import date

from ..textutil import clean, last_name, name_tokens, normalize_university, strip_accents

API = "https://api.reporter.nih.gov/v2/projects/search"
PROJECT_URL = "https://reporter.nih.gov/project-details/{appl_id}"


def build_query(first_name: str, last_name: str, fiscal_years: list[int], limit: int = 25) -> dict:
    """Search by surname only (the documented pattern); the first name and university are checked on our side.

    No include_fields list is sent, so the API returns its standard full record. That avoids depending on exact
    field-name spellings.
    """
    return {
        "criteria": {
            "pi_names": [{"last_name": last_name}],
            "fiscal_years": fiscal_years,
            "include_active_projects": True,
        },
        "offset": 0,
        "limit": limit,
    }


def _org_matches(org_name: str, university: str) -> bool:
    """Same institution: identical names, or one name continues the other with a campus
    ("university michigan" / "university michigan ann arbor"). Shared words alone are NOT enough:
    "Washington State University" must never match "University of Washington"."""
    a, b = normalize_university(org_name), normalize_university(university)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    return len(short.split()) >= 2 and long.startswith(short + " ")


def _compact(text: str) -> str:
    return re.sub(r"[^a-z]", "", strip_accents(clean(text)).lower())


def _first_names_match(ours: str, theirs: str) -> bool:
    """Full first name, or a shortened form of at least 3 letters (Chris / Christopher). An initial is not enough."""
    words = strip_accents(clean(theirs)).lower().split()
    ours, theirs = _compact(ours), _compact(words[0]) if words else ""
    if len(ours) < 2 or len(theirs) < 2:
        return False
    if ours == theirs:
        return True
    short, long = sorted((ours, theirs), key=len)
    return len(short) >= 3 and long.startswith(short)


def matching_projects(data: dict, professor_name: str, university: str, today: date) -> list[dict]:
    tokens = name_tokens(professor_name)
    if len(tokens) < 2:
        return []
    first = tokens[0]
    surnames = {_compact(last_name(professor_name)), _compact(tokens[-1])} - {""}
    out = []
    for project in (data or {}).get("results") or (data or {}).get("data") or []:
        pi_match = any(
            _compact(pi.get("last_name")) in surnames and _first_names_match(first, pi.get("first_name"))
            for pi in (project.get("principal_investigators") or [])
        )
        org = clean((project.get("organization") or {}).get("org_name"))
        end = clean(project.get("project_end_date"))[:10]
        active = not end or end >= today.isoformat()
        if pi_match and active and _org_matches(org, university):
            out.append(project)
    return out


def evidence_text(projects: list[dict]) -> str:
    parts = []
    for p in projects[:3]:
        appl_id = p.get("appl_id")
        agency = clean((p.get("agency_ic_admin") or {}).get("abbreviation"))
        end = clean(p.get("project_end_date"))[:10]
        parts.append(
            f"Active NIH project {clean(p.get('project_num') or p.get('core_project_num'))} \"{clean(p.get('project_title'))}\""
            f"{f' ({agency})' if agency else ''}{f', ends {end}' if end else ''} - {PROJECT_URL.format(appl_id=appl_id)}"
        )
    return "NIH RePORTER: " + "; ".join(parts) if parts else ""


def check_record(client, record: dict, today: date) -> tuple[str, str]:
    """Return (evidence_text, message). Does not modify the record."""
    tokens = name_tokens(record.get("professor_name", ""))
    if len(tokens) < 2:
        return "", "name too short to search"
    years = [today.year - 1, today.year, today.year + 1]
    surname = strip_accents(last_name(record.get("professor_name", ""))).lower() or tokens[-1]
    status, data, error = client.get_json(API, method="POST", json_body=build_query(tokens[0], surname, years))
    if status != 200 or data is None:
        return "", f"NIH RePORTER request failed: {error or status}"
    projects = matching_projects(data, record.get("professor_name", ""), record.get("university", ""), today)
    if not projects:
        return "", (
            "no active NIH project matched this exact name and university (other funders such as USDA/NSF are not covered, "
            "and a different spelling can hide a grant - search reporter.nih.gov by hand if it matters)"
        )
    return evidence_text(projects), f"{len(projects)} active NIH project(s) found"
