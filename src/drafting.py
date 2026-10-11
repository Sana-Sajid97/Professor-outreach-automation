"""Personalised email drafts built ONLY from verified record fields and the applicant's own CV.

Rules enforced here:
- A draft is only written for a verified record with a confirmed institutional email.
- The professor's research is quoted from the record (research_interests / publications).
- The applicant's experience comes word-for-word from her CV (profile.json evidence).
- The email asks about intake and assistantship funding; it never assumes either.
- It never says "I read your paper": it only *mentions* a recorded publication. Add your
  own sentence in the `personal_note` column after you have read the work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from . import models as m
from .profile import evidence_for_topic
from .scoring import _intake_available
from .textutil import clean, collapse_spaces, last_name, normalize_email, short_hash, split_multi
from .topics import TOPICS, match_topics
from .validate import contact_discouraged

SHORT_TOPIC = {
    "community_nutrition": "community nutrition",
    "food_insecurity": "food insecurity",
    "maternal_nutrition": "maternal nutrition",
    "diabetes_metabolic": "diabetes prevention",
    "childhood_obesity": "childhood obesity",
    "clinical_nutrition": "clinical nutrition",
    "nutrition_epidemiology": "nutrition epidemiology",
    "ai_ml": "data-driven nutrition research",
}
SUBJECT_TOPIC = {
    "community_nutrition": "community nutrition",
    "food_insecurity": "food insecurity",
    "maternal_nutrition": "maternal nutrition",
    "diabetes_metabolic": "diabetes prevention",
    "childhood_obesity": "childhood obesity",
    "clinical_nutrition": "clinical nutrition",
    "nutrition_epidemiology": "nutrition epidemiology",
    "ai_ml": "nutrition data science",
}
# Most specific first: used to choose what to name in the subject and the interest sentence.
SPECIFICITY = [
    "childhood_obesity", "maternal_nutrition", "food_insecurity", "diabetes_metabolic",
    "clinical_nutrition", "community_nutrition", "nutrition_epidemiology", "ai_ml",
]
TOPIC_ORDER = list(TOPICS.keys())
QUANT_TOPICS = {"ai_ml", "nutrition_epidemiology", "diabetes_metabolic"}


@dataclass
class Draft:
    subject: str
    body: str
    intake: str
    degree: str
    evidence_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def draft_hash(record: dict) -> str:
    """Fingerprint of what will be sent; approval is invalid if this changes."""
    return short_hash(normalize_email(record.get("institutional_email", "")), record.get("email_subject", ""), record.get("email_draft", ""))


def _variant(record: dict, n: int) -> int:
    key = clean(record.get("record_id")) or clean(record.get("professor_name"))
    return int(short_hash(key), 16) % n


def degree_label(record: dict, profile: dict) -> str:
    program = clean(record.get("graduate_program"))
    has_phd = bool(re.search(r"\bph\.?\s?d\b|doctor", program, re.IGNORECASE))
    has_ms = bool(re.search(r"\bm\.?s\.?c?\b|master|\bmsph\b", program, re.IGNORECASE))
    if has_phd and has_ms:
        return "MS or PhD"
    if has_phd:
        return "PhD"
    if has_ms:
        return "MS"
    targets = profile.get("target_degrees") or ["PhD", "MS"]
    return " or ".join(sorted(set(targets), key=lambda t: t != "MS")) if len(targets) > 1 else targets[0]


def intake_label(record: dict, today: date) -> tuple[str, str]:
    """(long form for the body, short form for the subject)."""
    spring = _intake_available(record.get("spring_2027_status", ""), today)
    fall = _intake_available(record.get("fall_2027_status", ""), today)
    spring_ok = spring is not False
    fall_ok = fall is not False
    if spring_ok and fall_ok:
        return "Spring 2027 or Fall 2027", "Spring/Fall 2027"
    if spring_ok:
        return "Spring 2027", "Spring 2027"
    return "Fall 2027", "Fall 2027"


def research_focus(record: dict, applicant_topics: set[str]) -> tuple[str, list[str]]:
    """Pick the professor's own research phrases that match the applicant's interests."""
    raw = clean(record.get("research_interests"))
    items = split_multi(raw)
    if len(items) == 1 and len(items[0]) > 140:
        chunks, current = [], ""
        for part in items[0].split(", "):
            if len(current) + len(part) > 120 and current:
                break
            current = f"{current}, {part}" if current else part
        chunks.append(current)
        items = chunks
    scored = []
    for position, item in enumerate(items):
        matches = {k: v for k, v in match_topics(item).items() if k in applicant_topics}
        strong = [k for k, v in matches.items() if v.is_strong]
        scored.append((0 if strong else (1 if matches else 2), position, item, list(matches)))
    scored.sort()
    chosen = [s for s in scored if s[0] < 2][:2] or scored[:1]
    chosen.sort(key=lambda s: s[1])
    phrases = [_lower_first(_tidy_phrase(s[2])) for s in chosen]
    phrases = [p for p in phrases if p]
    if len(phrases) == 2 and len(phrases[0]) + len(phrases[1]) > 150:
        phrases = phrases[:1]
    topics: list[str] = []
    for s in chosen:
        for t in s[3]:
            if t not in topics:
                topics.append(t)
    if len(phrases) == 2:
        joiner = ", as well as " if (" and " in phrases[0] or " and " in phrases[1]) else " and "
        return phrases[0] + joiner + phrases[1], topics
    return (phrases[0] if phrases else ""), topics


def _lower_first(text: str) -> str:
    if not text:
        return text
    words = text.split()
    first = words[0]
    if first.isupper() or (len(first) > 1 and any(c.isupper() for c in first[1:])):
        return text  # acronym or brand such as "SNAP" or "mHealth"
    if len(words) > 1 and words[1][:1].isupper():
        return text  # proper noun such as "Head Start" or "Native American"
    return text[0].lower() + text[1:]


def _tidy_phrase(text: str) -> str:
    """Drop parenthetical lists and stray spaces from a research phrase."""
    text = re.sub(r"\s*\([^)]*\)", "", text)
    return re.sub(r"\s+", " ", text).strip(" ,;.")


def order_topics(topics: list[str], research_text: str) -> list[str]:
    """Most specific topics first; drop 'diabetes' when it only came from the word 'obesity' in child-obesity work."""
    topics = list(dict.fromkeys(topics))
    if "childhood_obesity" in topics and "diabetes_metabolic" in topics:
        if not re.search(r"diabet|glyc|glucose|insulin|metabolic|cardiometabolic", research_text or "", re.IGNORECASE):
            topics.remove("diabetes_metabolic")
    return sorted(topics, key=lambda t: SPECIFICITY.index(t) if t in SPECIFICITY else 99)


def _join_topics(keys: list[str]) -> str:
    labels = [SHORT_TOPIC[k] for k in keys if k in SHORT_TOPIC]
    if not labels:
        return "nutrition research"
    if len(labels) == 1:
        return labels[0]
    joiner = " as well as " if " and " in labels[0] or " and " in labels[1] else " and "
    return f"{labels[0]}{joiner}{labels[1]}"


def _publication(record: dict, today: date) -> tuple[str, str]:
    """(year, title) of the most recent relevant publication recorded, or ('', '')."""
    for n in (1, 2):
        title = clean(record.get(f"relevant_publication_{n}")).rstrip(".")
        title = title.replace("\u201c", "\u2018").replace("\u201d", "\u2019").replace('"', "'")
        year_text = clean(record.get(f"publication_{n}_year"))
        try:
            year = int(year_text[:4]) if year_text else None
        except ValueError:
            year = None
        if title and year and year >= today.year - 4:
            return str(year), title
        if title and not year:
            return "", title
    return "", ""


def _ml_strength(item: dict) -> int:
    m_ = match_topics(item.get("text", "") + " " + item.get("context", "")).get("ai_ml")
    return len(m_.strong) if m_ else 0


def _evidence_score(item: dict, professor_topics: list[str]) -> float:
    score = 0.0
    for rank, topic in enumerate(professor_topics):
        if topic == "ai_ml":
            continue
        strength = item.get("topics", {}).get(topic)
        if strength:
            score += (2.0 if strength == "strong" else 1.0) * max(0.4, 1.0 - 0.2 * rank)
    if score == 0:
        return 0.0
    score += 0.4 * int(item.get("priority", 1))
    sentence = item.get("email_sentence", "")
    if len(sentence.split()) > 28:
        score -= 1.0
    if "etc." in sentence or re.search(r"\b(\w{5,})\b.*\b\1\b", sentence.lower()):
        score -= 0.8  # repetitive sentences read badly in an email
    if sentence.count(",") >= 5:
        score -= 1.0  # long lists read badly in an email
    return score


def choose_evidence(profile: dict, professor_topics: list[str]) -> list[dict]:
    """Up to two CV statements: the best match for this professor's topics, plus quantitative skills when relevant."""
    pool = [e for e in profile.get("evidence", []) if e.get("email_sentence") and e.get("use_in_emails", True)]
    ranked = sorted(pool, key=lambda e: (-_evidence_score(e, professor_topics), e.get("id", "")))
    chosen: list[dict] = []
    if ranked and _evidence_score(ranked[0], professor_topics) > 0:
        chosen.append(ranked[0])
    ml_items = sorted(
        [e for e in pool if e.get("topics", {}).get("ai_ml") == "strong"],
        key=lambda e: (-_ml_strength(e), -int(e.get("priority", 1)), e.get("id", "")),
    )
    if "ai_ml" in professor_topics and ml_items:
        topical = [c for c in chosen if c.get("topics", {}).get("ai_ml") != "strong"]
        return ([ml_items[0]] + topical)[:2]
    wants_quant = any(t in QUANT_TOPICS for t in professor_topics)
    if wants_quant and ml_items and ml_items[0] not in chosen:
        item = dict(ml_items[0])
        item["_quant"] = True
        chosen.append(item)
    else:
        first_topics = set(chosen[0].get("topics", {})) if chosen else set()
        for item in ranked[1:]:
            if _evidence_score(item, professor_topics) <= 0:
                break
            if item not in chosen and set(item.get("topics", {})) != first_topics:
                chosen.append(item)
                break
    if not chosen:
        # No CV line matches this professor's topics: use the strongest general nutrition experience,
        # then quantitative skills.
        general = sorted(
            [e for e in pool if e.get("topics", {}).get("clinical_nutrition") == "strong" or e.get("topics", {}).get("community_nutrition") == "strong"],
            key=lambda e: (-int(e.get("priority", 1)), e.get("id", "")),
        )
        if general:
            chosen.append(general[0])
        if ml_items and (len(chosen) < 2):
            item = dict(ml_items[0])
            item["_quant"] = bool(chosen)
            chosen.append(item)
    return chosen[:2]


def _evidence_sentences(evidence: list[dict]) -> str:
    parts = []
    for item in evidence:
        sentence = item["email_sentence"]
        if item.get("_quant") and parts and sentence.startswith("I "):
            sentence = "I also bring quantitative skills: I " + sentence[2:]
        parts.append(sentence)
    return " ".join(parts)


def can_draft(record: dict, today: date, min_fit: int, suppressed: bool = False, force: bool = False) -> tuple[bool, str]:
    status = clean(record.get("workflow_status"))
    if suppressed or status in m.SUPPRESSED_STATUSES:
        return False, "on the suppression list (opted out, bounced, or do-not-contact)"
    if status in m.CONTACTED_STATUSES:
        return False, f"already contacted (status '{status}')"
    if status == m.DRAFT_READY and not force:
        return False, "already has a draft (use --force to rewrite it)"
    if status == m.APPROVED and not force:
        return False, "already approved"
    if status not in {m.VERIFIED, m.DRAFT_READY, m.APPROVED}:
        return False, f"not verified yet (status '{status}')"
    if clean(record.get("verification_status")) != m.VER_VERIFIED:
        return False, "verification_status is not 'verified'"
    if clean(record.get("email_verification")) not in m.TRUSTED_EMAIL_METHODS | {m.EMAIL_SAMPLE}:
        return False, "email not confirmed on an official page"
    if not clean(record.get("research_interests")):
        return False, "no research interests recorded"
    if contact_discouraged(record):
        return False, "department discourages contacting faculty before review"
    try:
        score = int(float(clean(record.get("fit_score")) or 0))
    except ValueError:
        score = 0
    if score < min_fit:
        return False, f"fit score {score} is below the minimum {min_fit}"
    return True, ""


def build_draft(record: dict, profile: dict, today: date) -> Draft:
    warnings: list[str] = []
    applicant_topics = set(profile.get("research_interests") or TOPICS.keys())
    name = clean(profile.get("name")) or "[Your name]"
    degree_short = clean(profile.get("degree_short")) or clean(profile.get("degree"))
    institution = clean(profile.get("institution"))
    country = clean(profile.get("country"))
    cgpa = clean(profile.get("cgpa"))
    place = institution + (f", {country}" if country and country not in institution else "")

    prof_last = last_name(record.get("professor_name", ""))
    title = clean(record.get("title")).lower()
    prefs = profile.get("email_preferences") or {}
    greeting_template = prefs.get("greeting") or "Dear Dr. {last_name},"
    if "professor" in title and "{last_name}" in greeting_template and greeting_template.startswith("Dear Dr."):
        greeting = f"Dear Professor {prof_last},"
    else:
        greeting = greeting_template.replace("{last_name}", prof_last)

    degree = degree_label(record, profile)
    intake_long, intake_short = intake_label(record, today)
    focus, focus_topics = research_focus(record, applicant_topics)
    record_topics = [t for t in split_multi(record.get("matched_topics", "")) if t in applicant_topics]
    professor_topics = order_topics(
        focus_topics or record_topics or list(match_topics(record.get("research_interests", ""))),
        clean(record.get("research_interests")),
    )
    pub_topics = match_topics(" ".join(clean(record.get(f"relevant_publication_{n}")) for n in (1, 2)))
    if "ai_ml" in pub_topics and pub_topics["ai_ml"].is_strong and "ai_ml" not in professor_topics:
        professor_topics.append("ai_ml")  # their own recent paper uses data-science methods
    if not focus:
        warnings.append("No research interests to quote; the email will be generic. Add research_interests first.")
        focus = "nutrition"
    interest_phrase = _join_topics([t for t in professor_topics if t != "ai_ml"][:2] or professor_topics[:1])
    pub_year, pub_title = _publication(record, today)
    pub = bool(pub_title)
    paper = f'your {pub_year} paper, "{pub_title},"' if pub_year else f'your paper, "{pub_title},"'

    v = _variant(record, 2)
    if cgpa:
        intro = (
            f"My name is {name}, and I recently completed a {degree_short} at {place}, with a CGPA of {cgpa}."
            if v == 0
            else f"I am {name}, a recent graduate of {place}, where I completed a {degree_short} with a CGPA of {cgpa}."
        )
    else:
        intro = f"My name is {name}, and I recently completed a {degree_short} at {place}."
    if v == 0:
        focus_text = f"{focus}," if ", as well as " in focus else focus
        interest = f"I am writing because your research on {focus_text} closely aligns with my interest in {interest_phrase}."
        if pub:
            interest += f" {paper[0].upper() + paper[1:]} is especially relevant to the questions I hope to study."
    else:
        focus_text = f"{focus}," if ", as well as " in focus else focus
        interest = f"I am reaching out because your work on {focus_text} matches the research I hope to pursue in graduate school, particularly in {interest_phrase}."
        if pub:
            interest += f" I noticed {paper} which is closely related to the questions I hope to study."
    personal = collapse_spaces(record.get("personal_note", ""))
    if personal:
        if personal[-1] not in ".!?":
            personal += "."
        interest += " " + personal
    else:
        warnings.append("Tip: after reading their recent work, add one sentence of your own in 'personal_note'.")
    if not pub:
        warnings.append("No recent publication is recorded for this professor.")

    evidence = choose_evidence(profile, professor_topics)
    if evidence:
        lead = "This connects with my own experience." if v == 0 else "My background has prepared me for this kind of work."
        background = lead + " " + _evidence_sentences(evidence)
    else:
        background = ""
        warnings.append("No matching experience was found in your profile for this professor's topics.")

    program = clean(record.get("graduate_program"))
    university = clean(record.get("university"))
    if program and university and university.lower() not in program.lower():
        target = f"the {program} at {university}" if not program.lower().startswith("the ") else f"{program} at {university}"
    elif program:
        target = program
    else:
        target = f"graduate programs at {university}" if university else "your graduate program"
    ask = (
        f"I am planning to apply to {target} for {intake_long}, and I would be grateful to know whether you expect "
        f"to accept a new {degree} student in your group. I would also appreciate knowing whether a graduate research "
        f"or teaching assistantship might be available."
    )
    closing = (
        "I have attached my CV for your reference and would be happy to share any additional information. "
        "Thank you very much for your time and consideration."
        if prefs.get("mention_cv_attached", True)
        else "Thank you very much for your time and consideration."
    )
    signature = "\n".join(clean(line) for line in (profile.get("signature_lines") or [name]) if clean(line))
    paragraphs = [greeting, intro + " " + interest, background, ask, closing, "Sincerely,\n" + signature]
    body = "\n\n".join(p for p in paragraphs if p)

    max_words = int(prefs.get("max_words", 220) or 220)

    def body_words(paras: list[str]) -> int:
        return sum(len(p.split()) for p in paras[1:-1] if p)  # greeting and signature not counted

    words = body_words(paragraphs)
    if words > max_words and len(evidence) > 1:
        evidence = evidence[:1]
        background = lead + " " + _evidence_sentences(evidence)
        paragraphs[2] = background
        body = "\n\n".join(p for p in paragraphs if p)
        words = body_words(paragraphs)
    if words > max_words:
        warnings.append(f"The email body has {words} words (target {max_words}). Consider shortening it.")

    subject_topics = [t for t in professor_topics if t != "ai_ml"][:1] or professor_topics[:1]
    topic_for_subject = SUBJECT_TOPIC.get(subject_topics[0], "nutrition") if subject_topics else "nutrition"
    subject = f"Prospective {degree} student ({intake_short}): interest in your {topic_for_subject} research"
    if len(subject) > 95:
        subject = f"Prospective {degree} student ({intake_short}): research inquiry"
    return Draft(subject, body, intake_long, degree, [e["id"] for e in evidence], warnings)


def build_follow_up(record: dict, profile: dict, today: date) -> Draft:
    name = clean(profile.get("name")) or "[Your name]"
    prof_last = last_name(record.get("professor_name", ""))
    greeting = f"Dear Professor {prof_last}," if "professor" in clean(record.get("title")).lower() else f"Dear Dr. {prof_last},"
    sent_on = clean(record.get("last_contact_date")) or "last week"
    degree = degree_label(record, profile)
    intake_long, _ = intake_label(record, today)
    focus, _ = research_focus(record, set(profile.get("research_interests") or TOPICS.keys()))
    original = clean(record.get("email_subject"))
    if original.lower().startswith("re:"):
        subject = original
    else:
        subject = f"Re: {original}" if original else f"Following up: prospective {degree} student ({intake_long})"
    signature = "\n".join(clean(line) for line in (profile.get("signature_lines") or [name]) if clean(line))
    body = "\n\n".join(
        [
            greeting,
            f"I hope you are well. I am following up on my email of {sent_on} about joining your research group as a "
            f"{degree} student for {intake_long}. I remain very interested in your work on {focus or 'nutrition'}, and I would be "
            "grateful for any guidance on whether you are considering new students or have assistantship opportunities.",
            "If you are not taking new students at this time, I completely understand, and I will not follow up again. "
            "Thank you for your time.",
            "Sincerely,\n" + signature,
        ]
    )
    return Draft(subject, body, intake_long, degree, [], [])


def apply_draft(record: dict, draft: Draft, today: date) -> None:
    record["email_subject"] = draft.subject
    record["email_draft"] = draft.body
    record["approval_hash"] = ""
    record["approved_on"] = ""
    if clean(record.get("workflow_status")) in {m.VERIFIED, m.APPROVED, m.DRAFT_READY}:
        record["workflow_status"] = m.DRAFT_READY
    tips = "; ".join(draft.warnings)
    record["next_action"] = "Review the draft, then approve it" + (f" (notes: {tips})" if tips else "")
