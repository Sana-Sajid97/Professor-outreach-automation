"""Transparent research-fit scoring (0-10).

The score is a PRIORITISATION AID, not an admission probability. Every point is
explained in plain words, and missing evidence simply earns no points (it lowers
confidence instead of being guessed).

Rubric (from WORKFLOW.md):
  0-3  direct topic alignment with the applicant's research interests
  0-2  education/experience match (does the applicant's CV support those topics?)
  0-2  program fit/eligibility evidence (program open for an intake; English requirement met)
  0-2  recruitment/funding evidence (recruiting statement; assistantship/grant funding)
  0-1  recent relevant publication (within the last 3 years)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .profile import profile_topic_strength
from .textutil import clean, find_dates, is_blank_or_unknown
from .topics import TOPICS, core_topics, match_topics, topic_label
from .validate import ielts_minimum

DISCLAIMER = "Prioritisation aid only - not an admission probability."
_NEGATIVE_INTAKE = ("no spring", "not offered", "fall only", "does not admit", "not accepting", "closed", "passed", "n/a")
_POSITIVE_INTAKE = ("accepting", "open", "rolling", "deadline", "admits", "yes")


@dataclass
class FitResult:
    total: int
    topic: int
    background: int
    program: int
    funding: int
    publication: int
    matched_topics: list[str]
    confidence: str
    explanation: str
    notes: list[str] = field(default_factory=list)


def _intake_available(text: str, today: date) -> bool | None:
    """True if the status text says the intake is open, False if closed, None if unknown."""
    t = clean(text).lower()
    if is_blank_or_unknown(t) or t.startswith("not verified"):
        return None
    if any(neg in t for neg in _NEGATIVE_INTAKE):
        return False
    dates = find_dates(t)
    if dates:
        return any(d >= today for d in dates)
    if any(pos in t for pos in _POSITIVE_INTAKE):
        return True
    return None


def _has_evidence(text: str) -> bool:
    t = clean(text)
    return bool(t) and not is_blank_or_unknown(t) and not t.lower().startswith("not verified") and not t.lower().startswith("none")


def score_record(record: dict, profile: dict, today: date) -> FitResult:
    research_text = " ".join(
        clean(record.get(f, "")) for f in ("research_interests", "relevant_publication_1", "relevant_publication_2")
    )
    matches = match_topics(research_text)
    interests_only = match_topics(clean(record.get("research_interests", "")))
    pub_text = " ".join(clean(record.get(f, "")) for f in ("relevant_publication_1", "relevant_publication_2"))
    pub_matches = match_topics(pub_text)
    applicant_topics = set(profile.get("research_interests") or TOPICS.keys())
    matches = {k: v for k, v in matches.items() if k in applicant_topics}
    core = core_topics(matches)
    strong_core = {k: v for k, v in core.items() if v.is_strong}
    notes: list[str] = []

    # ---- 1. topic alignment (0-3)
    if len(strong_core) >= 2:
        topic = 3
    elif len(strong_core) == 1:
        only = next(iter(strong_core))
        topic = 3 if (only in pub_matches and only in interests_only) else 2
    elif len(core) >= 2:
        topic = 2
    elif core or "ai_ml" in matches:
        topic = 1
    else:
        topic = 0
    if matches:
        topic_reason = "; ".join(
            f"{topic_label(k)} ({'strong' if v.is_strong else 'weak'}: {v.evidence_words()})" for k, v in matches.items()
        )
    else:
        topic_reason = "no overlap found with your interests in the recorded research interests or publications"

    # ---- 2. applicant background (0-2)
    strengths = profile_topic_strength(profile)
    supported = {k: strengths[k] for k in matches if k in strengths}
    if any(v == "strong" for v in supported.values()):
        background = 2
    elif supported:
        background = 1
    else:
        background = 0
    if supported:
        background_reason = "your CV shows " + ", ".join(
            f"{'direct' if v == 'strong' else 'some'} experience in {topic_label(k)}" for k, v in supported.items()
        )
    else:
        background_reason = "your CV has no direct experience in this professor's topics"

    # ---- 3. program fit / eligibility (0-2)
    program = 0
    program_bits = []
    spring = _intake_available(record.get("spring_2027_status", ""), today)
    fall = _intake_available(record.get("fall_2027_status", ""), today)
    if clean(record.get("program_url")) and (spring or fall):
        program += 1
        open_terms = [t for t, ok in (("Spring 2027", spring), ("Fall 2027", fall)) if ok]
        program_bits.append(f"{' and '.join(open_terms)} intake open")
    elif spring is False and fall is False:
        program_bits.append("no open intake found for 2027")
    else:
        program_bits.append("intake/deadline not verified")
    applicant_ielts = None
    try:
        applicant_ielts = float((profile.get("english_test") or {}).get("overall", ""))
    except (TypeError, ValueError):
        pass
    minimum = ielts_minimum(" ".join(clean(record.get(f, "")) for f in ("eligibility_notes", "notes")))
    if minimum is not None and applicant_ielts is not None:
        if minimum <= applicant_ielts:
            program += 1
            program_bits.append(f"IELTS minimum {minimum:g} is met by your {applicant_ielts:g}")
        else:
            program_bits.append(f"IELTS minimum {minimum:g} is ABOVE your {applicant_ielts:g}")
            notes.append(f"English requirement (IELTS {minimum:g}) is above your score.")
    else:
        program_bits.append("English requirement not verified")

    # ---- 4. recruiting / funding (0-2)
    funding = 0
    funding_bits = []
    if _has_evidence(record.get("recruiting_evidence", "")):
        funding += 1
        funding_bits.append("recruiting evidence recorded")
    else:
        funding_bits.append("no recruiting statement found")
    if _has_evidence(record.get("funding_or_assistantship_evidence", "")):
        funding += 1
        funding_bits.append("funding/assistantship evidence recorded")
    else:
        funding_bits.append("no funding evidence found")

    # ---- 5. recent relevant publication (0-1)
    publication = 0
    pub_reason = "no recent relevant publication recorded"
    for n in (1, 2):
        title = clean(record.get(f"relevant_publication_{n}"))
        year_text = clean(record.get(f"publication_{n}_year"))
        try:
            year = int(year_text[:4]) if year_text else None
        except ValueError:
            year = None
        if title and year and year >= today.year - 3 and match_topics(title):
            publication = 1
            pub_reason = f"{year} paper on {', '.join(topic_label(k) for k in match_topics(title))}"
            break
        if title and not year:
            pub_reason = "publication recorded but its year is unknown"

    total = topic + background + program + funding + publication
    evidence_points = program + funding + publication
    verified = clean(record.get("verification_status")) == "verified"
    if verified and evidence_points >= 3:
        confidence = "high"
    elif verified or evidence_points >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    explanation = (
        f"Fit {total}/10 ({DISCLAIMER}) "
        f"Topic {topic}/3: {topic_reason}. "
        f"Background {background}/2: {background_reason}. "
        f"Program {program}/2: {'; '.join(program_bits)}. "
        f"Funding {funding}/2: {'; '.join(funding_bits)}. "
        f"Publication {publication}/1: {pub_reason}. "
        f"Confidence: {confidence}."
    )
    return FitResult(total, topic, background, program, funding, publication, list(matches), confidence, explanation, notes)


def apply_scores(records: list[dict], profile: dict, today: date) -> None:
    for record in records:
        result = score_record(record, profile, today)
        record["fit_score"] = str(result.total)
        record["fit_score_breakdown"] = result.explanation
        if result.matched_topics:
            record["matched_topics"] = "; ".join(result.matched_topics)
