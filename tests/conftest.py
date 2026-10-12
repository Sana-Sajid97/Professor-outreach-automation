"""Shared test fixtures. All people, emails and universities here are fictional."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_settings  # noqa: E402
from src.models import blank_record  # noqa: E402

TODAY = date(2026, 10, 11)


@pytest.fixture
def today():
    return TODAY


@pytest.fixture
def settings(tmp_path):
    s = load_settings(root=tmp_path, environ={})
    s.ensure_folders()
    (tmp_path / "data" / "seed").mkdir(parents=True, exist_ok=True)
    return s


@pytest.fixture
def profile():
    """A fictional applicant profile shaped like profile.json."""
    return {
        "schema_version": 1,
        "name": "Test Applicant",
        "email": "applicant@example.com",
        "degree": "Bachelor of Human Nutrition & Dietetics",
        "degree_short": "BS in Human Nutrition and Dietetics",
        "institution": "Example Agricultural University",
        "country": "Testland",
        "cgpa": "3.80/4.00",
        "english_test": {"type": "IELTS Academic", "overall": "6.5"},
        "coursework": ["Public Health Nutrition", "Statistics"],
        "target_degrees": ["PhD", "MS"],
        "research_interests": [
            "community_nutrition", "food_insecurity", "maternal_nutrition", "diabetes_metabolic",
            "childhood_obesity", "clinical_nutrition", "nutrition_epidemiology", "ai_ml",
        ],
        "evidence": [
            {"id": "E01", "section": "Clinical Experience", "context": "", "priority": 3, "use_in_emails": True,
             "text": "Provided nutrition counseling for underserved patients.",
             "email_sentence": "I provided nutrition counseling for underserved patients.",
             "topics": {"clinical_nutrition": "strong", "food_insecurity": "weak"}},
            {"id": "E02", "section": "Clinical Experience", "context": "", "priority": 3, "use_in_emails": True,
             "text": "Managed dietary interventions for patients with diabetes and obesity.",
             "email_sentence": "I managed dietary interventions for patients with diabetes and obesity.",
             "topics": {"diabetes_metabolic": "strong", "clinical_nutrition": "strong"}},
            {"id": "E03", "section": "Internship Experience", "context": "", "priority": 3, "use_in_emails": True,
             "text": "Led nutrition awareness campaigns in the community.",
             "email_sentence": "I led nutrition awareness campaigns in the community.",
             "topics": {"community_nutrition": "strong"}},
            {"id": "E04", "section": "Projects", "context": "Biomarker ML Project | Used: XGBoost, SHAP", "priority": 2, "use_in_emails": True,
             "text": "Developed an ML model using XGBoost and SHAP on clinical biomarkers.",
             "email_sentence": "I developed an ML model using XGBoost and SHAP on clinical biomarkers.",
             "topics": {"ai_ml": "strong"}},
        ],
        "signature_lines": ["Test Applicant", "BS in Human Nutrition and Dietetics", "applicant@example.com"],
        "email_preferences": {"greeting": "Dear Dr. {last_name},", "max_words": 220, "mention_cv_attached": True},
    }


def make_record(**overrides) -> dict:
    record = blank_record()
    record.update(
        {
            "record_id": "R0001",
            "professor_name": "Jamie Testperson",
            "title": "Associate Professor",
            "university": "State University of Testing",
            "state": "ZZ",
            "department_or_school": "Department of Nutrition",
            "faculty_profile_url": "https://nutrition.testing.edu/people/jamie-testperson",
            "institutional_email": "jamie.testperson@testing.edu",
            "email_source_url": "https://nutrition.testing.edu/people/jamie-testperson",
            "email_verification": "found_on_official_page",
            "research_interests": "household food insecurity; maternal diet quality during pregnancy; SNAP program evaluation",
            "relevant_publication_1": "Food insecurity and diet quality in pregnancy",
            "publication_1_url": "https://doi.org/10.0000/test.1",
            "publication_1_year": "2025",
            "graduate_program": "PhD in Nutrition",
            "program_url": "https://nutrition.testing.edu/grad",
            "spring_2027_status": "Accepting - international deadline 2026-11-15",
            "fall_2027_status": "Accepting - deadline 2026-12-15",
            "recruiting_evidence": "Lab page: recruiting a PhD student for 2027",
            "funding_or_assistantship_evidence": "Active grant funds a graduate research assistant",
            "eligibility_notes": "Graduate school minimum IELTS 6.5 overall",
            "source_urls": "https://nutrition.testing.edu/people/jamie-testperson",
            "date_checked": "2026-10-01",
            "verification_status": "verified",
            "workflow_status": "verified",
            "fit_score": "8",
        }
    )
    record.update(overrides)
    return record


@pytest.fixture
def record():
    return make_record()


def write_profile(settings, profile_dict) -> Path:
    settings.private_dir.mkdir(parents=True, exist_ok=True)
    settings.profile_path.write_text(json.dumps(profile_dict), encoding="utf-8")
    return settings.profile_path


class FakeResponse:
    def __init__(self, status_code=200, text="", headers=None, url="", json_data=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.url = url
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    """Maps URL -> FakeResponse (or a list of responses returned in order)."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    def _respond(self, url):
        self.calls.append(url)
        value = self.routes.get(url)
        if value is None:
            for key, val in self.routes.items():
                if key.endswith("*") and url.startswith(key[:-1]):
                    value = val
                    break
        if value is None:
            return FakeResponse(404, "not found", url=url)
        if isinstance(value, list):
            value = value.pop(0) if len(value) > 1 else value[0]
        if isinstance(value, Exception):
            raise value
        return value

    def get(self, url, headers=None, timeout=None, allow_redirects=True, params=None):
        return self._respond(url)

    def post(self, url, json=None, params=None, headers=None, timeout=None):
        return self._respond(url)


def make_pdf(path: Path, lines: list[str], pages: int = 1) -> Path:
    """A small, valid PDF with real text on each page (for CV checks)."""
    content = "BT /F1 12 Tf 72 720 Td " + " ".join(f"({line}) Tj 0 -16 Td" for line in lines) + " ET"
    page_ids = list(range(3, 3 + pages))
    content_id, font_id = 3 + pages, 4 + pages
    objects = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{i} 0 R' for i in page_ids)}] /Count {pages} >>",
        content_id: f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        font_id: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for i in page_ids:
        objects[i] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
                      f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>")
    out, offsets = b"%PDF-1.4\n", {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n{objects[number]}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for number in sorted(objects):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    return path
