"""Discover candidate professors from recent publications using the official OpenAlex API.

Facts checked for this project (October 2026):
- An API key is REQUIRED for all requests since 2026-02-13 (free key at openalex.org/settings/api).
  The old "mailto" polite pool no longer exists.
- per_page tops out at 100. Usage is billed against a free daily allowance; keyword search
  costs more than plain filters, so this module keeps queries few and small.
- HTTP 429 (and sometimes 403) means "slow down": the client backs off.

Output records are LEADS (status "discovered"). They contain no email: the official
faculty page must be found and verified before any outreach.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from .. import models as m
from ..errors import UserFacingError
from ..textutil import clean
from ..topics import match_topics, topic_label

API = "https://api.openalex.org/works"
DEFAULT_QUERIES = {
    "food_insecurity": "food insecurity nutrition",
    "maternal_nutrition": "maternal nutrition pregnancy",
    "diabetes_metabolic": "diabetes prevention diet",
    "childhood_obesity": "childhood obesity prevention",
    "community_nutrition": "community nutrition intervention",
    "clinical_nutrition": "medical nutrition therapy dietary intervention",
    "nutrition_epidemiology": "nutritional epidemiology diet quality",
    "ai_ml": "machine learning nutrition",
}


def build_params(query: str, api_key: str, from_date: str, per_page: int = 50, page: int = 1) -> dict:
    if not api_key:
        raise UserFacingError(
            "OpenAlex now requires a free API key. Get one at https://openalex.org/settings/api and add "
            "OPENALEX_API_KEY=... to your .env file."
        )
    return {
        "search": query,
        "filter": f"authorships.institutions.country_code:US,from_publication_date:{from_date},type:article",
        "per_page": max(1, min(100, per_page)),
        "page": page,
        "select": "id,doi,display_name,publication_year,authorships",
        "api_key": api_key,
    }


def candidates_from_works(works: list[dict], topic_key: str) -> dict[str, dict]:
    """Collect senior (last or corresponding) authors at US institutions from a list of works."""
    people: dict[str, dict] = {}
    for work in works:
        title = clean(work.get("display_name") or work.get("title"))
        year = work.get("publication_year")
        doi = clean(work.get("doi"))
        for authorship in work.get("authorships") or []:
            position = authorship.get("author_position")
            if position != "last" and not authorship.get("is_corresponding"):
                continue
            institutions = [i for i in (authorship.get("institutions") or []) if (i or {}).get("country_code") == "US"]
            if not institutions:
                continue
            author = authorship.get("author") or {}
            author_id = clean(author.get("id"))
            name = clean(author.get("display_name"))
            if not author_id or not name:
                continue
            person = people.setdefault(
                author_id,
                {"name": name, "author_id": author_id, "orcid": clean(author.get("orcid")), "institutions": defaultdict(int), "works": [], "topics": set()},
            )
            for inst in institutions:
                person["institutions"][clean(inst.get("display_name"))] += 1
            person["works"].append({"title": title, "year": year, "doi": doi})
            person["topics"].add(topic_key)
            for t in match_topics(title):
                person["topics"].add(t)
    return people


def to_records(people: dict[str, dict], today: date, min_works: int = 1) -> list[dict]:
    records = []
    for person in people.values():
        if len(person["works"]) < min_works:
            continue
        institution = max(person["institutions"].items(), key=lambda kv: kv[1])[0] if person["institutions"] else ""
        works = sorted(person["works"], key=lambda w: -(w.get("year") or 0))
        record = m.blank_record()
        record.update(
            {
                "professor_name": person["name"],
                "university": institution,
                "research_interests": "; ".join(topic_label(t) for t in sorted(person["topics"])),
                "relevant_publication_1": works[0]["title"] if works else "",
                "publication_1_url": works[0]["doi"] if works else "",
                "publication_1_year": str(works[0]["year"] or "") if works else "",
                "relevant_publication_2": works[1]["title"] if len(works) > 1 else "",
                "publication_2_url": works[1]["doi"] if len(works) > 1 else "",
                "publication_2_year": str(works[1]["year"] or "") if len(works) > 1 else "",
                "source_urls": "; ".join([person["author_id"]] + [w["doi"] for w in works[:3] if w.get("doi")]),
                "date_checked": today.isoformat(),
                "workflow_status": m.DISCOVERED,
                "verification_status": m.VER_NOT,
                "record_source": "openalex",
                "research_fit_explanation": f"Senior author of {len(works)} recent US paper(s) on {', '.join(topic_label(t) for t in sorted(person['topics']))} (from OpenAlex).",
                "next_action": f'Find the official faculty page: search "{person["name"]}" "{institution}" faculty profile, then add faculty_profile_url and run verify.',
                "notes": "Lead from OpenAlex. Not verified: confirm the person is current faculty who supervises graduate students.",
            }
        )
        records.append(record)
    return records


def discover(client, api_key: str, today: date, topics: list[str] | None = None, per_topic: int = 50, since_year: int | None = None) -> tuple[list[dict], list[str]]:
    """Run one OpenAlex query per topic. Returns (lead records, messages)."""
    since_year = since_year or today.year - 3
    messages: list[str] = []
    people: dict[str, dict] = {}
    for topic in topics or list(DEFAULT_QUERIES):
        query = DEFAULT_QUERIES.get(topic, topic)
        params = build_params(query, api_key, f"{since_year}-01-01", per_page=per_topic)
        status, data, error = client.get_json(API, params=params)
        if status != 200 or not data:
            messages.append(f"OpenAlex query '{query}' failed: {error or status}")
            if status in (401, 403):
                messages.append("Check that OPENALEX_API_KEY is correct and that you have not used up today's free allowance.")
                break
            continue
        found = candidates_from_works(data.get("results") or [], topic if topic in DEFAULT_QUERIES else "community_nutrition")
        for author_id, person in found.items():
            if author_id in people:
                existing = people[author_id]
                existing["works"].extend(person["works"])
                existing["topics"] |= person["topics"]
                for inst, n in person["institutions"].items():
                    existing["institutions"][inst] += n
            else:
                people[author_id] = person
        messages.append(f"OpenAlex '{query}': {len(data.get('results') or [])} papers, {len(found)} senior US authors.")
    return to_records(people, today), messages
