"""Funding evidence from NIH RePORTER (official API, no key needed).

An ACTIVE NIH grant led by a professor is good evidence that money for a graduate
research assistant may exist. It is NOT proof that a position is open, so the
email still asks politely.

Endpoint: POST https://api.reporter.nih.gov/v2/projects/search
NIH asks API users to keep to about one request per second and to run large jobs
off-peak; the polite client spaces requests out automatically.
NOTE: this module was written from NIH's published API documentation and tested with
sample responses; it could not be tested against the live API from the cloud build
environment. Run `python -m src.cli check-funding --limit 3` once to confirm it works.
"""

from __future__ import annotations

from datetime import date

from ..textutil import clean, name_tokens, normalize_university, strip_accents

API = "https://api.reporter.nih.gov/v2/projects/search"
PROJECT_URL = "https://reporter.nih.gov/project-details/{appl_id}"


def build_query(first_name: str, last_name: str, fiscal_years: list[int], limit: int = 25) -> dict:
    return {
        "criteria": {
            "pi_names": [{"first_name": first_name, "last_name": last_name}],
            "fiscal_years": fiscal_years,
            "include_active_projects": True,
        },
        "include_fields": [
            "ApplId", "ProjectNum", "ProjectTitle", "FiscalYear", "Organization", "PrincipalInvestigators",
            "ProjectStartDate", "ProjectEndDate", "AgencyIcAdmin", "AwardAmount",
        ],
        "offset": 0,
        "limit": limit,
    }


def _org_matches(org_name: str, university: str) -> bool:
    a, b = normalize_university(org_name), normalize_university(university)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    words_a = {w for w in a.split() if len(w) > 3 and w not in {"university", "college", "school", "health", "sciences", "center"}}
    words_b = {w for w in b.split() if len(w) > 3 and w not in {"university", "college", "school", "health", "sciences", "center"}}
    return bool(words_a & words_b)


def matching_projects(data: dict, professor_name: str, university: str, today: date) -> list[dict]:
    tokens = name_tokens(professor_name)
    if not tokens:
        return []
    first, last = tokens[0], tokens[-1]
    out = []
    for project in (data or {}).get("results") or []:
        pis = project.get("principal_investigators") or []
        pi_match = False
        for pi in pis:
            pf = strip_accents(clean(pi.get("first_name"))).lower()
            pl = strip_accents(clean(pi.get("last_name"))).lower()
            if pl.replace(" ", "-") == last or pl == last.replace("-", " "):
                if not pf or pf.startswith(first[:1]):
                    pi_match = True
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
            f"Active NIH project {clean(p.get('project_num'))} \"{clean(p.get('project_title'))}\""
            f"{f' ({agency})' if agency else ''}{f', ends {end}' if end else ''} - {PROJECT_URL.format(appl_id=appl_id)}"
        )
    return "NIH RePORTER: " + "; ".join(parts) if parts else ""


def check_record(client, record: dict, today: date) -> tuple[str, str]:
    """Return (evidence_text, message). Does not modify the record."""
    tokens = name_tokens(record.get("professor_name", ""))
    if len(tokens) < 2:
        return "", "name too short to search"
    years = [today.year - 1, today.year, today.year + 1]
    status, data, error = client.get_json(API, method="POST", json_body=build_query(tokens[0], tokens[-1], years))
    if status != 200 or data is None:
        return "", f"NIH RePORTER request failed: {error or status}"
    projects = matching_projects(data, record.get("professor_name", ""), record.get("university", ""), today)
    if not projects:
        return "", "no active NIH project found for this name at this university (other funders such as USDA/NSF are not covered)"
    return evidence_text(projects), f"{len(projects)} active NIH project(s) found"
