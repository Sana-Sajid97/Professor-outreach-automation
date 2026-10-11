"""OpenAlex and NIH RePORTER parsers (offline, with sample responses shaped like the documented APIs)."""

from __future__ import annotations

import pytest

from src.discovery import nih_reporter, openalex
from src.errors import UserFacingError

WORKS = [
    {
        "id": "https://openalex.org/W1",
        "doi": "https://doi.org/10.1/abc",
        "display_name": "Food insecurity and gestational diabetes",
        "publication_year": 2025,
        "authorships": [
            {"author_position": "first", "author": {"id": "https://openalex.org/A1", "display_name": "Student First"},
             "institutions": [{"display_name": "Test University", "country_code": "US"}]},
            {"author_position": "last", "author": {"id": "https://openalex.org/A2", "display_name": "Pat Senior"},
             "institutions": [{"display_name": "Test University", "country_code": "US"}]},
        ],
    },
    {
        "id": "https://openalex.org/W2",
        "doi": None,
        "display_name": "Diet quality in rural Canada",
        "publication_year": 2024,
        "authorships": [
            {"author_position": "last", "author": {"id": "https://openalex.org/A3", "display_name": "Abroad Author"},
             "institutions": [{"display_name": "Some Canadian University", "country_code": "CA"}]},
        ],
    },
]


def test_openalex_requires_api_key():
    with pytest.raises(UserFacingError, match="API key"):
        openalex.build_params("food insecurity", "", "2023-01-01")
    params = openalex.build_params("food insecurity", "KEY", "2023-01-01", per_page=500)
    assert params["per_page"] == 100  # OpenAlex maximum
    assert "country_code:US" in params["filter"]
    assert params["api_key"] == "KEY"


def test_openalex_keeps_only_senior_us_authors(today):
    people = openalex.candidates_from_works(WORKS, "food_insecurity")
    assert set(people) == {"https://openalex.org/A2"}
    records = openalex.to_records(people, today)
    rec = records[0]
    assert rec["professor_name"] == "Pat Senior"
    assert rec["university"] == "Test University"
    assert rec["workflow_status"] == "discovered"
    assert rec["institutional_email"] == ""  # never guessed
    assert rec["research_interests"] == ""  # never filled from the search query; copied from the official profile later
    assert "diabetes" in rec["notes"]  # what the search was about is kept as a note


class FakeAPIClient:
    def __init__(self, status, data):
        self.status, self.data, self.calls = status, data, []

    def get_json(self, url, params=None, method="GET", json_body=None):
        self.calls.append((url, method, params, json_body))
        return self.status, self.data, "" if self.status == 200 else "error"


def test_openalex_discover_handles_errors(today):
    leads, messages = openalex.discover(FakeAPIClient(403, None), "KEY", today, topics=["food_insecurity"])
    assert leads == []
    assert any("OPENALEX_API_KEY" in m for m in messages)
    leads, _ = openalex.discover(FakeAPIClient(200, {"results": WORKS}), "KEY", today, topics=["food_insecurity"])
    assert [r["professor_name"] for r in leads] == ["Pat Senior"]


NIH = {
    "meta": {"total": 2},
    "results": [
        {"appl_id": 111, "project_num": "R01DK000001", "project_title": "Food insecurity in pregnancy", "project_end_date": "2029-06-30T00:00:00",
         "organization": {"org_name": "STATE UNIVERSITY OF TESTING"}, "agency_ic_admin": {"abbreviation": "NIDDK"},
         "principal_investigators": [{"first_name": "Jamie", "last_name": "Testperson"}]},
        {"appl_id": 222, "project_num": "R03HD000002", "project_title": "Old project", "project_end_date": "2020-01-01T00:00:00",
         "organization": {"org_name": "STATE UNIVERSITY OF TESTING"}, "principal_investigators": [{"first_name": "Jamie", "last_name": "Testperson"}]},
    ],
}


def test_nih_matching_and_evidence(record, today):
    projects = nih_reporter.matching_projects(NIH, record["professor_name"], record["university"], today)
    assert [p["appl_id"] for p in projects] == [111]  # ended project ignored
    text = nih_reporter.evidence_text(projects)
    assert "R01DK000001" in text and "https://reporter.nih.gov/project-details/111" in text
    client = FakeAPIClient(200, NIH)
    evidence, message = nih_reporter.check_record(client, record, today)
    assert evidence and "1 active" in message
    body = client.calls[0][3]
    assert body["criteria"]["pi_names"][0]["last_name"] == "testperson"
    other = dict(record, university="Different College")
    assert nih_reporter.matching_projects(NIH, other["professor_name"], other["university"], today) == []
