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

import re
from dataclasses import dataclass, field
from datetime import date

from .profile import profile_topic_strength
from .textutil import clean, find_dates, find_month_days, is_blank_or_unknown, meaningful
from .topics import TOPICS, core_topics, match_topics, topic_label
from .validate import ielts_minimum

DISCLAIMER = "Prioritisation aid only - not an admission probability."
# Intake status texts are free text written during research. Whole words only; unknown beats everything.
_UNKNOWN_INTAKE = re.compile(r"\bnot verified\b|\bnot yet\b|\bnot posted\b|\bunknown\b|\bunclear\b|\bconflicting\b|\bunconfirmed\b")
_HARD_NO_INTAKE = re.compile(
    r"^no\b|\bno spring\b|\bnot offered\b|\bfall only\b|\bdoes not admit\b|\bnot accepting\b|\bnot open\b|\bno longer\b|\bn/a\b"
    r"|\b(?:likely|probably) (?:closed|passed)\b|\b(?:closed|passed) for international\b"  # the international date is the one that counts
)
# Research dates ("as of 2026-10-11", "checked Oct 11, 2026") are not deadlines.
_RESEARCH_DATE = re.compile(
    r"\b(?:as of|checked(?: on)?|accessed(?: on)?|updated(?: on)?|retrieved(?: on)?|verified(?: on)?)\s+"
    r"(?:20\d\d-\d{1,2}-\d{1,2}|[a-z]{3,9}\.? \d{1,2}(?:st|nd|rd|th)?,? 20\d\d|\d{1,2} [a-z]{3,9},? 20\d\d|\d{1,2}/\d{1,2}/20\d\d)"
)
_PASSED_INTAKE = re.compile(r"\bpassed\b|\bclosed\b|\bexpired\b")
_POSITIVE_INTAKE = re.compile(r"^yes\b|\baccepting\b|\bopen\b|\brolling\b|\badmits\b|\bapply anytime\b|\byear-round\b")


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


def _cycle_year(month: int, intake: str) -> int | None:
    """Year of a standing deadline (written without a year) in the 2027 application cycle."""
    if intake == "spring":  # Spring 2027 deadlines run from about March 2026 to January 2027
        return 2026 if month >= 3 else 2027
    if intake == "fall":  # Fall 2027 deadlines run from about August 2026 to July 2027
        return 2026 if month >= 8 else 2027
    return None


def _intake_available(text: str, today: date, intake: str = "") -> bool | None:
    """True if the status text says the intake is still open, False if not, None if unknown.

    intake ("spring" or "fall") lets standing deadlines without a year ("December 1") be placed in the 2027 cycle.
    """
    t = clean(text).lower()
    if is_blank_or_unknown(t) or _UNKNOWN_INTAKE.search(t):
        return None
    if _HARD_NO_INTAKE.search(t):
        return False
    t = _RESEARCH_DATE.sub(" ", t)
    dates = list(find_dates(t))
    for month, day in find_month_days(t):
        year = _cycle_year(month, intake)
        if year:
            try:
                dates.append(date(year, month, day))
            except ValueError:
                pass
    if dates:
        return any(d >= today for d in dates)  # "priority date passed; final 2027-01-15" is still open
    if _PASSED_INTAKE.search(t):
        return False
    if _POSITIVE_INTAKE.search(t):
        return True
    return None


def _has_evidence(text: str) -> bool:
    t = clean(text)
    return bool(t) and not is_blank_or_unknown(t) and not t.lower().startswith("not verified") and not t.lower().startswith("none")


def score_record(record: dict, profile: dict, today: date) -> FitResult:
    research_text = " ".join(
        meaningful(record.get(f, "")) for f in ("research_interests", "relevant_publication_1", "relevant_publication_2")
    )
    matches = match_topics(research_text)
    interests_only = match_topics(meaningful(record.get("research_interests", "")))
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
    spring = _intake_available(record.get("spring_2027_status", ""), today, "spring")
    fall = _intake_available(record.get("fall_2027_status", ""), today, "fall")
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
