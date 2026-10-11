"""Import the applicant's profile from her CV/portfolio (PDF or text).

The importer only *extracts* what is written in the file. It never adds
achievements. The result is saved to `private_profile/profile.json` (Git-ignored),
which you can open and edit; the email drafts use only facts from that file.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from .errors import UserFacingError
from .textutil import EMAIL_FIND_RE, collapse_spaces
from .topics import TOPICS, match_topics

PROFILE_SCHEMA_VERSION = 1

BULLET_CHARS = "●•○◦▪■▸►-*–"
KNOWN_HEADINGS = {
    "achievements", "education", "skills", "project", "projects", "experience", "clinical experience",
    "research experience", "work experience", "internship experience", "teaching/volunteer experience",
    "teaching experience", "volunteer experience", "health hackathons projects", "international hackathons",
    "internation hackathons", "international competitions", "publications", "certifications", "awards",
    "workshops/webinars", "leadership", "assessments and research on patients", "public speaking",
    "communication skills", "global exposure & leadership", "curriculum vitae",
}
SECTION_PRIORITY = {
    "clinical experience": 3,
    "internship experience": 3,
    "assessments and research on patients": 3,
    "project": 3,
    "projects": 3,
    "research experience": 3,
    "award-winning leadership in national innovation expo": 2,
    "health hackathons projects": 2,
    "international hackathons": 1,
    "internation hackathons": 1,
}
IRREGULAR_PAST = {
    "led", "taught", "built", "won", "ran", "wrote", "gave", "made", "held", "took", "became", "brought",
    "drew", "sought", "spoke", "met", "set", "put", "read", "found", "grew", "began", "co-led", "co-founded",
}
PASSIVE_STARTS = {"awarded", "selected", "ranked", "invited", "nominated", "recognized", "chosen"}
NOT_VERBS = {"used", "need", "speed", "seed", "red", "bed", "feed", "embed"}
LINK_LABELS = re.compile(
    r"\s*\((?:link|github|certificate|recording|see here|here|video|pdf|slides)\)\s*", re.IGNORECASE
)
LABEL_PREFIX = re.compile(r"^([A-Z][\w/&+.' -]{1,40}):\s+(?=[A-Z])")


# ---------------------------------------------------------------- text extraction
def extract_pdf(path: Path) -> tuple[list[str], list[str]]:
    """Return (page_texts, link_urls) from a PDF."""
    try:
        import pypdf
    except ImportError as exc:  # pragma: no cover
        raise UserFacingError("Reading PDFs needs pypdf. Run: pip install -r requirements.txt") from exc
    try:
        reader = pypdf.PdfReader(str(path))
    except Exception as exc:
        raise UserFacingError(f"Could not open the PDF {path}: {exc}") from exc
    pages, links = [], []
    for page in reader.pages:
        text = ""
        try:
            text = page.extract_text(extraction_mode="layout") or ""
        except TypeError:  # older pypdf without layout mode
            text = ""
        except Exception:
            text = ""
        if not text.strip():
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            text = _rejoin_word_per_line(text)
        pages.append(text.replace("​", ""))
        try:
            annots = page.get("/Annots") or []
            for annot in annots:
                obj = annot.get_object()
                action = obj.get("/A")
                if action is not None:
                    uri = action.get_object().get("/URI")
                    if uri and str(uri) not in links:
                        links.append(str(uri))
        except Exception:
            continue
    return pages, links


def _rejoin_word_per_line(text: str) -> str:
    """Some PDF exports put one word per line; join them back into lines at bullets."""
    lines = [ln.strip() for ln in text.splitlines()]
    words = [w for w in lines if w]
    if not words or len(words) < 0.6 * max(1, len(lines)) or sum(len(w.split()) for w in words) > 1.3 * len(words):
        return text
    joined = " ".join(words)
    joined = re.sub(rf"\s*([{re.escape(BULLET_CHARS[:6])}])\s+", r"\n\1 ", joined)
    return joined


def read_profile_source(path: Path) -> tuple[list[str], list[str]]:
    path = Path(path)
    if not path.exists():
        raise UserFacingError(f"Profile file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        pages = re.split(r"\f|\n={5,}\s*page\s*\d+\s*={5,}\n", text, flags=re.IGNORECASE)
        return pages, re.findall(r"https?://\S+", text)
    raise UserFacingError("Please provide your CV as a .pdf or .txt file.")


# ---------------------------------------------------------------- parsing helpers
def _split_columns(line: str) -> list[str]:
    """Split a layout line into left/right parts separated by 3+ spaces."""
    return [p.strip() for p in re.split(r"\s{3,}", line.strip()) if p.strip()]


def _is_heading(line: str) -> bool:
    text = collapse_spaces(line).strip(":")
    if not text or len(text) > 70:
        return False
    if text.lower() in KNOWN_HEADINGS:
        return True
    letters = re.sub(r"[^A-Za-z]", "", text)
    return len(letters) >= 4 and letters.isupper() and len(text.split()) <= 5


def _starts_with_bullet(line: str) -> bool:
    s = line.lstrip()
    return bool(s) and s[0] in BULLET_CHARS and (len(s) == 1 or s[1] in " \t")


def _strip_bullet(line: str) -> str:
    s = line.lstrip()
    while s and s[0] in BULLET_CHARS:
        s = s[1:].lstrip()
    return s


def _is_past_verb(word: str) -> bool:
    w = word.lower().strip(",.;:")
    if w in NOT_VERBS:
        return False
    return w in IRREGULAR_PAST or (w.endswith("ed") and len(w) > 4)


def first_person(text: str) -> str:
    """Rewrite a CV bullet ('Managed dietary interventions...') as 'I managed dietary interventions...'.

    Returns '' when the bullet does not start with a past-tense verb (it is then
    kept as evidence but not used verbatim in emails).
    """
    t = collapse_spaces(LINK_LABELS.sub(" ", text)).strip()
    t = re.sub(r"\s+([,.;:])", r"\1", t)
    label = LABEL_PREFIX.match(t)
    if label:
        rest = t[label.end():]
        words = rest.split()
        if words and (_is_past_verb(words[0]) or words[0].lower() in PASSIVE_STARTS):
            t = rest
    words = t.split()
    if not words:
        return ""
    first = words[0]
    if first.lower() in PASSIVE_STARTS:
        sentence = "I was " + first.lower() + " " + " ".join(words[1:])
    elif _is_past_verb(first):
        sentence = "I " + first.lower() + " " + " ".join(words[1:])
    elif first.lower().endswith("ly") and len(words) > 1 and _is_past_verb(words[1]):
        sentence = "I " + first.lower() + " " + words[1].lower() + " " + " ".join(words[2:])
    else:
        return ""
    sentence = sentence.strip()
    if sentence and sentence.rstrip("\"'”’)")[-1:] not in {".", "!", "?"}:
        sentence += "."
    return sentence


# ---------------------------------------------------------------- main parser
def parse_profile(pages: list[str], links: list[str], source_name: str = "", today: date | None = None) -> dict:
    today = today or date.today()
    all_text = "\n".join(pages)
    flat = collapse_spaces(all_text)

    profile: dict = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "source_file": source_name,
        "imported_on": today.isoformat(),
        "review_note": "Auto-imported from your CV. Please check every field; edit this file if anything is wrong.",
        "name": "",
        "email": "",
        "phone": "",
        "links": {},
        "degree": "",
        "degree_short": "",
        "institution": "",
        "location": "",
        "country": "",
        "graduation": "",
        "cgpa": "",
        "english_test": {},
        "coursework": [],
        "skills": {},
        "target_degrees": ["PhD", "MS"],
        "target_intakes": ["Spring 2027", "Fall 2027"],
        "research_interests": [
            "community_nutrition", "food_insecurity", "maternal_nutrition", "diabetes_metabolic",
            "childhood_obesity", "clinical_nutrition", "nutrition_epidemiology", "ai_ml",
        ],
        "evidence": [],
        "signature_lines": [],
        "email_preferences": {"greeting": "Dear Dr. {last_name},", "max_words": 220, "mention_cv_attached": True},
        "warnings": [],
    }

    # ---- contact details
    emails = [e for e in EMAIL_FIND_RE.findall(all_text)]
    if emails:
        profile["email"] = emails[0].lower()
    phone = re.search(r"Phone:\s*(\+?[\d][\d\s()\-]{7,}\d)", all_text)
    if phone:
        profile["phone"] = collapse_spaces(phone.group(1))
    for url in links:
        low = url.lower()
        if "linkedin.com/in/" in low and "linkedin" not in profile["links"]:
            profile["links"]["linkedin"] = url
        elif re.match(r"https?://(www\.)?github\.com/[^/]+/?$", low) and "github" not in profile["links"]:
            profile["links"]["github"] = url

    # ---- name: a short line of capitalised words right before the contact line
    for page in pages:
        lines = [ln.strip() for ln in page.splitlines() if ln.strip()]
        for i, line in enumerate(lines):
            if ("@" in line or "phone" in line.lower()) and i > 0:
                cand = collapse_spaces(lines[i - 1])
                if re.fullmatch(r"(?:[A-Z][a-zA-Z'’-]+\s){1,3}[A-Z][a-zA-Z'’-]+", cand):
                    profile["name"] = cand
                    break
        if profile["name"]:
            break

    # ---- grades and tests
    cgpa = re.search(r"CGPA[:\s]*([0-4]\.\d{1,2})\s*/\s*(\d(?:\.\d{1,2})?)", flat)
    if cgpa:
        profile["cgpa"] = f"{cgpa.group(1)}/{cgpa.group(2)}"
    else:
        cgpa = re.search(r"CGPA[^0-9]{0,30}([0-4]\.\d{1,2})", flat)
        if cgpa:
            profile["cgpa"] = cgpa.group(1)
    ielts = re.search(r"IELTS[^.]{0,60}?(?:band|overall|score)[^0-9]{0,15}([1-9](?:\.[05])?)\b", flat, re.IGNORECASE)
    if ielts:
        profile["english_test"] = {"type": "IELTS Academic" if "academic" in flat.lower() else "IELTS", "overall": ielts.group(1)}
    toefl = re.search(r"TOEFL[^.]{0,40}?(\d{2,3})\b", flat)
    if toefl and not profile["english_test"]:
        profile["english_test"] = {"type": "TOEFL iBT", "overall": toefl.group(1)}

    # ---- education block
    for page in pages:
        lines = page.splitlines()
        for i, raw in enumerate(lines):
            if collapse_spaces(raw).upper() != "EDUCATION":
                continue
            block = [ln for ln in lines[i + 1 : i + 8] if ln.strip()]
            for ln in block:
                parts = _split_columns(ln)
                left = LINK_LABELS.sub("", parts[0]).strip() if parts else ""
                left = re.sub(r"\((?:link)\)", "", left, flags=re.IGNORECASE).strip()
                if not profile["institution"] and re.search(r"universit|college|institute", left, re.IGNORECASE):
                    profile["institution"] = left.rstrip("(").strip()
                    if len(parts) > 1:
                        profile["location"] = parts[-1]
                elif not profile["degree"] and re.search(r"\b(bachelor|b\.?s\.?c?|master|m\.?s\.?c?)\b", left, re.IGNORECASE):
                    profile["degree"] = left
                    if len(parts) > 1:
                        span = parts[-1]
                        end = re.split(r"\s*[-–]\s*", span)[-1]
                        profile["graduation"] = end.strip()
                elif left.lower().startswith("relevant coursework"):
                    items = left.split(":", 1)[1] if ":" in left else ""
                    profile["coursework"] = [c.strip() for c in items.split(",") if c.strip()]
            break
        if profile["institution"]:
            break
    if profile["location"] and "," in profile["location"]:
        profile["country"] = profile["location"].split(",")[-1].strip()
    if profile["degree"]:
        d = profile["degree"]
        m = re.match(r"bachelor(?:'s)?\s+of\s+(?:science\s+in\s+)?(.*)", d, re.IGNORECASE)
        if m:
            profile["degree_short"] = "BS in " + m.group(1).replace("&", "and").strip()
        else:
            profile["degree_short"] = d

    # ---- skills block
    for page in pages:
        lines = page.splitlines()
        for i, raw in enumerate(lines):
            if collapse_spaces(raw).upper() != "SKILLS":
                continue
            for ln in lines[i + 1 : i + 12]:
                if not ln.strip():
                    continue
                if _is_heading(ln):
                    break
                parts = _split_columns(ln)
                if len(parts) >= 2 and parts[0].endswith(":"):
                    profile["skills"][parts[0].rstrip(":").strip()] = [s.strip() for s in parts[1].split(",") if s.strip()]
                elif ":" in ln:
                    label, _, items = ln.partition(":")
                    profile["skills"][collapse_spaces(label)] = [s.strip() for s in items.split(",") if s.strip()]
            break

    profile["evidence"] = extract_evidence(pages)

    # ---- signature (no phone number by default)
    sig = [profile["name"] or "[Your name]"]
    if profile["degree_short"] and profile["institution"]:
        sig.append(f"{profile['degree_short']}, {profile['institution']}" + (f", {profile['country']}" if profile["country"] and profile["country"] not in profile["institution"] else ""))
    if profile["email"]:
        sig.append(profile["email"])
    if profile["links"].get("linkedin"):
        sig.append("LinkedIn: " + profile["links"]["linkedin"].replace("http://", "https://"))
    profile["signature_lines"] = sig

    for key, label in [("name", "your name"), ("email", "your email"), ("degree", "your degree"),
                       ("institution", "your university"), ("cgpa", "your CGPA")]:
        if not profile[key]:
            profile["warnings"].append(f"Could not find {label} in the CV. Please add it to profile.json.")
    if not profile["english_test"]:
        profile["warnings"].append("Could not find an English test score (IELTS/TOEFL). Add it to profile.json if you have one.")
    if not any(e["email_sentence"] for e in profile["evidence"]):
        profile["warnings"].append("No experience sentences were detected. Add some under 'evidence' in profile.json.")
    return profile


def extract_evidence(pages: list[str]) -> list[dict]:
    """Collect experience statements (bullets and verb-led lines) with topic tags."""
    items: list[dict] = []
    for page_no, page in enumerate(pages, start=1):
        section = ""
        context = ""
        current: dict | None = None
        lines = page.splitlines()
        first_content = next((collapse_spaces(ln) for ln in lines if collapse_spaces(ln) and not collapse_spaces(ln).isdigit()), "")
        for raw in lines:
            line = raw.rstrip()
            text = collapse_spaces(line)
            if not text or text.isdigit():
                continue
            if _is_heading(text):
                section = text.strip(":")
                context = ""
                current = None
                continue
            if _starts_with_bullet(line):
                body = _strip_bullet(line)
                current = {"page": page_no, "section": section or first_content, "context": context, "text": collapse_spaces(body)}
                items.append(current)
                continue
            parts = _split_columns(line)
            left = parts[0] if parts else text
            if left.lower().startswith("used:"):
                context = (context + " | " if context else "") + left
                current = None
                continue
            words = left.split()
            if words and (_is_past_verb(words[0]) or words[0].lower() in PASSIVE_STARTS) and len(words) >= 5:
                current = {"page": page_no, "section": section or first_content, "context": context, "text": collapse_spaces(left)}
                items.append(current)
                continue
            indent = len(line) - len(line.lstrip())
            if current is not None and indent >= 6 and len(parts) == 1:
                current["text"] = collapse_spaces(current["text"] + " " + text)  # wrapped continuation line
                continue
            # A title line such as "Renal AI Wellness Hackathon (Link)        Dec, 2025".
            context = collapse_spaces(LINK_LABELS.sub(" ", left))
            current = None

    seen: set[str] = set()
    evidence: list[dict] = []
    for item in items:
        text = collapse_spaces(item["text"])
        text = re.sub(r"\s+([,.;:])", r"\1", text)
        key = re.sub(r"[^a-z0-9]", "", text.lower())[:120]
        if len(text) < 25 or key in seen:
            continue
        seen.add(key)
        topic_text = text + " " + item.get("context", "")
        matches = match_topics(topic_text)
        topics = {k: ("strong" if m.is_strong else "weak") for k, m in matches.items()}
        section_key = collapse_spaces(item["section"]).lower()
        sentence = first_person(text)
        needs_rewrite = bool(sentence) and _reads_badly(sentence)
        evidence.append(
            {
                "id": f"E{len(evidence) + 1:02d}",
                "page": item["page"],
                "section": item["section"],
                "context": item.get("context", ""),
                "text": text,
                "email_sentence": sentence,
                "topics": topics,
                "priority": SECTION_PRIORITY.get(section_key, 1),
                "use_in_emails": not needs_rewrite,
                "needs_rewrite": needs_rewrite,
            }
        )
    return evidence


def _reads_badly(sentence: str) -> bool:
    """Long comma lists, 'etc.' or a repeated word read badly in an email; such lines need a human rewrite first."""
    lowered = sentence.lower()
    if "etc." in lowered or sentence.count(",") >= 6:
        return True
    words = [w for w in re.findall(r"[a-z]{5,}", lowered)]
    return len(words) != len(set(words)) and any(words.count(w) > 1 for w in set(words) if w not in {"nutrition", "patients", "students"})


# ---------------------------------------------------------------- save / load
def import_profile(source: Path, target: Path, today: date | None = None) -> dict:
    pages, links = read_profile_source(Path(source))
    profile = parse_profile(pages, links, source_name=Path(source).name, today=today)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    return profile


def load_profile(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise UserFacingError(
            "Your profile has not been imported yet. Put your CV/portfolio PDF in the 'private_profile' "
            "folder and run:  python -m src.cli import-profile"
        )
    try:
        profile = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise UserFacingError(
            f"{path.name} has a formatting error near line {exc.lineno}: {exc.msg}. "
            "If you edited it, check for a missing comma or quote, or re-run import-profile."
        ) from exc
    for evidence in profile.get("evidence", []):
        evidence.setdefault("topics", {})
        evidence.setdefault("use_in_emails", True)
        evidence.setdefault("priority", 1)
        evidence.setdefault("email_sentence", "")
    return profile


def find_profile_source(private_dir: Path, root: Path) -> Path | None:
    """Locate a CV/portfolio file: private_profile/ first, then the repository folder."""
    for folder in (Path(private_dir), Path(root)):
        if not folder.exists():
            continue
        pdfs = sorted(folder.glob("*.pdf"), key=lambda p: ("portfolio" not in p.name.lower() and "cv" not in p.name.lower(), p.name))
        if pdfs:
            return pdfs[0]
    return None


def evidence_for_topic(profile: dict, topic: str) -> list[dict]:
    """Evidence items for a topic, best first (strong before weak, then by section priority)."""
    out = []
    for e in profile.get("evidence", []):
        strength = e.get("topics", {}).get(topic)
        if strength and e.get("use_in_emails", True):
            out.append(e)
    out.sort(key=lambda e: (e["topics"][topic] != "strong", -int(e.get("priority", 1)), e["id"]))
    return out


def profile_topic_strength(profile: dict) -> dict[str, str]:
    """Best evidence strength the applicant has for each topic ('strong'/'weak')."""
    best: dict[str, str] = {}
    for e in profile.get("evidence", []):
        if not e.get("use_in_emails", True):
            continue
        for topic, strength in e.get("topics", {}).items():
            if topic not in TOPICS:
                continue
            if best.get(topic) != "strong":
                best[topic] = strength
    for course in profile.get("coursework", []):
        for topic, m in match_topics(course).items():
            best.setdefault(topic, "weak")
    return best


def summarize_profile(profile: dict) -> str:
    lines = [
        f"Name:        {profile.get('name') or '(not found)'}",
        f"Email:       {profile.get('email') or '(not found)'}",
        f"Degree:      {profile.get('degree') or '(not found)'}",
        f"University:  {profile.get('institution') or '(not found)'}",
        f"Graduation:  {profile.get('graduation') or '(not found)'}",
        f"CGPA:        {profile.get('cgpa') or '(not found)'}",
        f"English:     {(profile.get('english_test') or {}).get('type', '')} {(profile.get('english_test') or {}).get('overall', '(not found)')}",
        f"Coursework:  {', '.join(profile.get('coursework', [])) or '(not found)'}",
        f"Evidence:    {len(profile.get('evidence', []))} experience statements "
        f"({sum(1 for e in profile.get('evidence', []) if e.get('email_sentence') and e.get('use_in_emails', True))} usable in emails)",
    ]
    strengths = profile_topic_strength(profile)
    if strengths:
        lines.append("Topics your CV supports: " + ", ".join(f"{k} ({v})" for k, v in sorted(strengths.items())))
    rewrite = [e["id"] for e in profile.get("evidence", []) if e.get("needs_rewrite")]
    if rewrite:
        lines.append(
            f"NOTE: {len(rewrite)} sentence(s) read like long lists ({', '.join(rewrite)}). They are kept out of emails until you "
            "rewrite 'email_sentence' in profile.json and set \"use_in_emails\": true."
        )
    for w in profile.get("warnings", []):
        lines.append("WARNING: " + w)
    return "\n".join(lines)
