"""Profile import from a CV, page verification and the polite web client."""

from __future__ import annotations

import json

from src import models as m
from src.http_client import FetchResult, PoliteClient, _parse_crawl_delay
from src.profile import first_person, import_profile, parse_profile, profile_topic_strength
from src.verify import choose_email, confirm_email_manually, decode_cloudflare, extract_emails, verify_record

from .conftest import FakeResponse, FakeSession, make_record

CV_TEXT = """
                                   Alex Applicant
        Phone: +00 (000) 000-0000 | alex.applicant@example.com | LinkedIn | GitHub
  ACHIEVEMENTS
     ●     CGPA: Graduated with a CGPA of 3.70, ranking among the top of my class.
     ●     IELTS: Achieved an overall Band 7.0
  EDUCATION
   Example University of Agriculture, Exampletown(Link)                         Exampletown, Testland
   Bachelor of Human Nutrition & Dietetics                                         Sep 2020-Jul 2024
   CGPA: 3.70/4.00
   Relevant Coursework: Community Nutrition, Biostatistics
  SKILLS
   Clinical Nutrition:                             SGA, MNA, NCP
   Programming:                                    Python, R
  Clinical Experience
          • Provided nutrition counseling for pregnant women attending an antenatal clinic.
          • Managed dietary interventions for patients with type 2 diabetes
          and hypertension.
  PROJECT
   Developed a machine learning model to predict anemia from dietary intake data.
"""


def test_parse_profile_from_text():
    profile = parse_profile([CV_TEXT], ["https://www.linkedin.com/in/alex-applicant", "https://github.com/alexapp"], "cv.txt")
    assert profile["name"] == "Alex Applicant"
    assert profile["email"] == "alex.applicant@example.com"
    assert profile["cgpa"] == "3.70/4.00"
    assert profile["english_test"]["overall"] == "7.0"
    assert profile["institution"] == "Example University of Agriculture, Exampletown"
    assert profile["degree_short"] == "BS in Human Nutrition and Dietetics"
    assert profile["graduation"] == "Jul 2024"
    assert "Biostatistics" in profile["coursework"]
    assert profile["links"]["github"] == "https://github.com/alexapp"
    sentences = [e["email_sentence"] for e in profile["evidence"]]
    assert "I provided nutrition counseling for pregnant women attending an antenatal clinic." in sentences
    assert "I managed dietary interventions for patients with type 2 diabetes and hypertension." in sentences  # wrapped line joined
    strengths = profile_topic_strength(profile)
    assert strengths["maternal_nutrition"] == "strong"
    assert strengths["diabetes_metabolic"] == "strong"
    assert strengths["ai_ml"] == "strong"
    assert "+00" not in " ".join(profile["signature_lines"])  # phone number never goes in emails


def test_first_person_rules():
    assert first_person("Managed dietary interventions for patients") == "I managed dietary interventions for patients."
    assert first_person("IELTS Trainer: Trained 200+ students (Recording)") == "I trained 200+ students."
    assert first_person("Successfully led awareness campaigns.") == "I successfully led awareness campaigns."
    assert first_person("Awarded for outstanding contribution.") == "I was awarded for outstanding contribution."
    assert first_person("Meta Hacker Cup Competition") == ""
    assert first_person('Delivered a workshop on "Coding."') == 'I delivered a workshop on "Coding."'


def _minimal_pdf(lines: list[str]) -> bytes:
    """Build a tiny valid PDF with one page of text (no external libraries)."""
    content = "BT /F1 11 Tf 72 740 Td 14 TL " + " ".join(f"({ln.replace('(', '[').replace(')', ']')}) Tj T*" for ln in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def test_import_profile_from_pdf(tmp_path):
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(_minimal_pdf(["Alex Applicant", "alex.applicant@example.com", "CGPA: 3.70/4.00", "IELTS: overall Band 7.0"]))
    target = tmp_path / "private_profile" / "profile.json"
    profile = import_profile(pdf, target)
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["email"] == "alex.applicant@example.com"
    assert saved["cgpa"] == "3.70/4.00"
    assert profile["english_test"]["overall"] == "7.0"


# ------------------------------------------------------------------ email extraction
PROFILE_HTML = """
<html><body><h1>Jamie Testperson, PhD</h1><p>Associate Professor of Nutrition</p>
<p>Contact: <a href="mailto:jamie.testperson@testing.edu?subject=Hello">Email me</a></p>
<p>Department office: <a href="mailto:nutrition@testing.edu">nutrition@testing.edu</a></p>
<script>var x = "tracking@ads.example.com";</script>
</body></html>
"""


def test_extract_emails_mailto_and_text():
    emails = dict(extract_emails(PROFILE_HTML))
    assert "jamie.testperson@testing.edu" in emails
    assert "nutrition@testing.edu" in emails
    assert "tracking@ads.example.com" not in emails  # script contents ignored


def test_extract_obfuscated_and_cloudflare():
    key = 0x42
    encoded = f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in "pat.lee@state.edu")
    html = f"""<p>Pat Lee: plee [at] state [dot] edu</p>
    <a href="/cdn-cgi/l/email-protection#{encoded}">[email protected]</a>
    <span class="__cf_email__" data-cfemail="{encoded}">[email protected]</span>"""
    emails = dict(extract_emails(html))
    assert "plee@state.edu" in emails
    assert "pat.lee@state.edu" in emails
    assert decode_cloudflare(encoded) == "pat.lee@state.edu"


def test_choose_email_rules():
    emails = [("nutrition@testing.edu", "mailto"), ("jamie.testperson@testing.edu", "mailto"), ("jamie@gmail.com", "text")]
    email, _, reason = choose_email(emails, "Jamie Testperson", "https://nutrition.testing.edu/people/jamie")
    assert email == "jamie.testperson@testing.edu"
    # wrong domain and generic office addresses are never chosen
    email, _, reason = choose_email([("jamie@gmail.com", "x"), ("info@testing.edu", "x")], "Jamie Testperson", "https://testing.edu/p")
    assert email == ""


class StubClient:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, use_cache=True):
        if url in self.pages:
            return FetchResult(url, True, 200, self.pages[url], final_url=url)
        return FetchResult(url, False, 404, error="Page not found (404).")


def test_verify_record_success(today):
    rec = make_record(institutional_email="", email_source_url="", email_verification="", verification_status="not_verified", workflow_status="needs_verification")
    client = StubClient({rec["faculty_profile_url"]: PROFILE_HTML})
    outcome = verify_record(rec, client, today)
    assert outcome.status == m.VER_VERIFIED
    assert rec["institutional_email"] == "jamie.testperson@testing.edu"
    assert rec["email_verification"] == m.EMAIL_FOUND_ON_PAGE
    assert rec["workflow_status"] == m.VERIFIED
    assert rec["date_checked"] == today.isoformat()


def test_verify_record_conflict_is_not_overwritten(today):
    rec = make_record(institutional_email="someone.else@testing.edu", verification_status="not_verified", workflow_status="needs_verification")
    client = StubClient({rec["faculty_profile_url"]: PROFILE_HTML})
    outcome = verify_record(rec, client, today)
    assert outcome.status == m.VER_PARTIAL
    assert rec["institutional_email"] == "someone.else@testing.edu"
    assert "CONFLICT" in rec["notes"]


def test_verify_record_missing_page_and_hidden_email(today):
    rec = make_record(faculty_profile_url="https://testing.edu/gone", email_source_url="", lab_url="", institutional_email="", workflow_status="needs_verification", verification_status="not_verified")
    assert verify_record(rec, StubClient({}), today).status == m.VER_NOT
    hidden = "<h1>Jamie Testperson</h1><p>Email: use the contact form</p>"
    rec2 = make_record(faculty_profile_url="https://testing.edu/jt", email_source_url="", lab_url="", institutional_email="", workflow_status="needs_verification", verification_status="not_verified")
    outcome = verify_record(rec2, StubClient({"https://testing.edu/jt": hidden}), today)
    assert outcome.status == m.VER_PARTIAL
    assert "confirm-email" in rec2["next_action"]


def test_manual_confirmation_requires_official_source(today):
    rec = make_record(email_verification="", verification_status="not_verified", workflow_status="needs_verification")
    import pytest

    from src.errors import UserFacingError

    with pytest.raises(UserFacingError):
        confirm_email_manually(rec, "jt@testing.edu", "https://www.linkedin.com/in/jt", today)
    confirm_email_manually(rec, "JT@testing.edu", "https://testing.edu/people/jt", today)
    assert rec["institutional_email"] == "jt@testing.edu"
    assert rec["email_verification"] == m.EMAIL_CONFIRMED_MANUALLY
    assert rec["workflow_status"] == m.VERIFIED


# ------------------------------------------------------------------ polite client
def _client(routes, sleeps):
    clock = {"t": 0.0}

    def sleep(seconds):
        sleeps.append(seconds)
        clock["t"] += seconds

    return PoliteClient("TestAgent/1.0", delay_seconds=2, session=FakeSession(routes), sleep=sleep, clock=lambda: clock["t"])


def test_robots_disallow_is_respected():
    sleeps = []
    client = _client({"https://site.edu/robots.txt": FakeResponse(200, "User-agent: *\nDisallow: /private\n"), "https://site.edu/public": FakeResponse(200, "ok")}, sleeps)
    assert client.get("https://site.edu/public").ok
    blocked = client.get("https://site.edu/private/page")
    assert not blocked.ok and blocked.blocked_by_robots


def test_robots_403_means_no_automated_access():
    client = _client({"https://locked.edu/robots.txt": FakeResponse(403, "")}, [])
    result = client.get("https://locked.edu/page")
    assert not result.ok and result.blocked_by_robots


def test_missing_robots_allows_and_rate_limit_backs_off():
    sleeps = []
    routes = {
        "https://busy.edu/robots.txt": FakeResponse(404, ""),
        "https://busy.edu/page": [FakeResponse(429, "", headers={"Retry-After": "7"}), FakeResponse(200, "<html>ok</html>")],
    }
    client = _client(routes, sleeps)
    result = client.get("https://busy.edu/page")
    assert result.ok
    assert 7 in sleeps  # honoured Retry-After


def test_access_denied_is_not_bypassed():
    client = _client({"https://x.edu/robots.txt": FakeResponse(404, ""), "https://x.edu/p": FakeResponse(403, "captcha")}, [])
    result = client.get("https://x.edu/p")
    assert not result.ok and "Not bypassed" in result.error


def test_crawl_delay_parsing_including_fractions():
    text = "User-agent: *\nCrawl-delay: 2.5\n\nUser-agent: TestAgent\nCrawl-delay: 10\n"
    assert _parse_crawl_delay(text, "TestAgent/1.0") == 10
    assert _parse_crawl_delay(text, "Other/1.0") == 2.5


def test_cache_avoids_second_request(tmp_path):
    session = FakeSession({"https://c.edu/robots.txt": FakeResponse(404, ""), "https://c.edu/p": FakeResponse(200, "cached text")})
    client = PoliteClient("TestAgent/1.0", 1, cache_dir=tmp_path, session=session, sleep=lambda s: None)
    assert client.get("https://c.edu/p").text == "cached text"
    calls = len(session.calls)
    again = client.get("https://c.edu/p")
    assert again.from_cache and len(session.calls) == calls


def test_list_like_cv_lines_are_held_back():
    text = """
  PROJECT
     ●     Assessed patients, symptoms, gave diet plans, took follow-ups, and responses for COPD, diabetes, hypertension, pregnancy, diabetes.
     ●     Provided nutrition counseling for underserved patients.
"""
    profile = parse_profile([text], [], "cv.txt")
    flags = {e["text"][:8]: (e["use_in_emails"], e["needs_rewrite"]) for e in profile["evidence"]}
    assert flags["Assessed"] == (False, True)
    assert flags["Provided"] == (True, False)
