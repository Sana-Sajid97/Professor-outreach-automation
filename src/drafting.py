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
from .scoring import _intake_available
from .textutil import clean, collapse_spaces, last_name, meaningful, normalize_email, normalize_university, short_hash, split_multi
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


_PHD_RE = re.compile(r"\bph\.?\s?d\b|doctor", re.IGNORECASE)
_MS_RE = re.compile(r"\bm\.?s\.?c?\b|master|\bmsph\b", re.IGNORECASE)
# A PhD that needs a master's first is not open to a bachelor's graduate; a self-funded MS is not an assistantship route.
_PHD_NEEDS_MS_RE = re.compile(
    r"(?:requires?|expects?)\s+(?:a\s+|an\s+)?(?:master'?s|m\.?s\.?)\b|after\s+an?\s+(?:m\.?s|master)|\bm\.?s\.?\s+first", re.IGNORECASE
)
_MS_UNFUNDED_RE = re.compile(r"\bm\.?s\.?\b[^;.]*\b(?:self-funded|unfunded|not funded)\b", re.IGNORECASE)


def degree_label(record: dict, profile: dict) -> str:
    program = clean(record.get("graduate_program"))
    has_phd = bool(_PHD_RE.search(program)) and not _PHD_NEEDS_MS_RE.search(program)
    has_ms = bool(_MS_RE.search(program)) and not _MS_UNFUNDED_RE.search(program)
    if has_phd and has_ms:
        return "MS or PhD"
    if has_phd:
        return "PhD"
    if has_ms:
        return "MS"
    targets = profile.get("target_degrees") or ["PhD", "MS"]
    return " or ".join(sorted(set(targets), key=lambda t: t != "MS")) if len(targets) > 1 else targets[0]


_PROGRAM_NOTE_RE = re.compile(
    r"\b(?:not verified|not confirmed|probably|possibly|likely|unclear|unknown|confirm|she|he|her|his)\b", re.IGNORECASE
)
_INSTITUTION_WORDS_RE = re.compile(
    r"\b(?:university|college|school|department|dept|division|gsas|institute|campus)\b", re.IGNORECASE
)
_DEGREE_SUFFIX_RE = re.compile(
    r"(.+?),\s*((?:M\.?S\.?|Ph\.?D\.?)(?:\s*(?:and|or|/)\s*(?:M\.?S\.?|Ph\.?D\.?))?)", re.IGNORECASE
)


def clean_program_name(program: str, university: str = "") -> str:
    """A program name fit for an email: "PhD in Nutritional Sciences" from research notes such as
    "PhD in Nutritional Sciences (Graduate Program ...); the MS is self-funded, so ...". Returns "" when the
    research text is only a guess ("Probably ...", "Not verified ...")."""
    text = clean(program)
    if not text or re.match(r"(?:not verified|probably|possibly|likely|unclear|unknown)\b", text, re.IGNORECASE):
        return ""
    text = re.sub(r"\s*\([^)]*\)", "", text)  # bracketed notes
    text = re.split(r"\s*\(|\s*;|\s+[-\u2013\u2014]\s+", text, maxsplit=1)[0]  # notes after ';' or ' - '
    uni_words = {w for w in normalize_university(university).split() if len(w) > 3 and w not in {"university", "college", "state"}}
    pieces = text.split(", ")
    kept = [pieces[0]]
    for piece in pieces[1:]:
        if _INSTITUTION_WORDS_RE.search(piece) or (uni_words & set(normalize_university(piece).split())):
            break  # ", Department of ...", ", University of ...", ", UMass Amherst"
        kept.append(piece)
    text = ", ".join(kept).strip(" ,;")
    if text.endswith(".") and not re.search(r"(?:M\.S|Ph\.D|M\.Sc|Ed\.D)\.$", text, re.IGNORECASE):
        text = text[:-1]  # keep the full stop of "M.S." and "Ph.D."
    m = _DEGREE_SUFFIX_RE.fullmatch(text)
    if m:
        text = f"{m.group(2)} in {m.group(1)}"  # "Food Science, M.S." -> "M.S. in Food Science"
    if not text or _PROGRAM_NOTE_RE.search(text) or len(text) > 100:
        return ""
    if not re.search(r"\b(?:ph\.?\s?d|m\.?s|master|doctor|program)\b", text, re.IGNORECASE):
        return ""  # e.g. "Graduate study in Nutrition": no clear program name
    return text


def clean_university_name(university: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s*\([^)]*\)", "", clean(university))).strip()


def intake_label(record: dict, today: date) -> tuple[str, str]:
    """(long form for the body, short form for the subject)."""
    spring = _intake_available(record.get("spring_2027_status", ""), today, "spring")
    fall = _intake_available(record.get("fall_2027_status", ""), today, "fall")
    spring_ok = spring is not False
    fall_ok = fall is not False
    if spring_ok and fall_ok:
        return "Spring 2027 or Fall 2027", "Spring/Fall 2027"
    if spring_ok:
        return "Spring 2027", "Spring 2027"
    return "Fall 2027", "Fall 2027"


def _split_interests(raw: str) -> list[str]:
    """Split research interests on ';', '|' or new lines, but never inside brackets."""
    items, depth, current = [], 0, []
    for ch in raw:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch in ";|\n" and depth == 0:
            items.append("".join(current))
            current = []
        else:
            current.append(ch)
    items.append("".join(current))
    seen, out = set(), []
    for item in (clean(i) for i in items):
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out


def focus_parts(record: dict, applicant_topics: set[str]) -> list[tuple[str, list[str], int]]:
    """Up to two of the professor's own research phrases that match the applicant's interests:
    [(phrase, applicant topics it matches, rank)] in the professor's own order. Rank 0 = strong match."""
    items = _split_interests(meaningful(record.get("research_interests", "")))
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
        rank = 0 if strong else (1 if matches else 2)
        if not _is_topic_phrase(item):
            rank = 3  # a lab name, job title or role is never quoted as research
        scored.append((rank, position, item, list(matches)))
    scored.sort()
    chosen = [s for s in scored if s[0] < 2][:2] or [s for s in scored if s[0] < 3][:1]
    chosen.sort(key=lambda s: s[1])
    parts = [(_lower_first(_tidy_phrase(s[2])), s[3], s[0]) for s in chosen]
    parts = [p for p in parts if p[0]]
    if len(parts) == 2 and len(parts[0][0]) + len(parts[1][0]) > 150:
        parts = [best_part(parts)]
    return parts


def best_part(parts: list[tuple[str, list[str], int]]) -> tuple[str, list[str], int]:
    """The best-matching phrase (lowest rank; the professor's first-listed one on a tie)."""
    return min(parts, key=lambda p: p[2])


def join_focus(phrases: list[str]) -> str:
    if len(phrases) == 2:
        joiner = ", as well as " if (" and " in phrases[0] or " and " in phrases[1]) else " and "
        return phrases[0] + joiner + phrases[1]
    return phrases[0] if phrases else ""


def research_focus(record: dict, applicant_topics: set[str]) -> tuple[str, list[str]]:
    """The quoted research phrase(s) and the applicant topics they match (only from phrases actually quoted)."""
    parts = focus_parts(record, applicant_topics)
    topics: list[str] = []
    for _, phrase_topics, _ in parts:
        topics.extend(t for t in phrase_topics if t not in topics)
    return join_focus([p for p, _, _ in parts]), topics


def _lower_first(text: str) -> str:
    if not text:
        return text
    words = text.split()
    first = words[0]
    if first.isupper() or (len(first) > 1 and any(c.isupper() for c in first[1:])):
        return text  # acronym or brand such as "SNAP" or "mHealth"
    if len(words) > 1 and words[1][:1].isupper():
        return text  # proper noun such as "Head Start" or "Native American"
    if len(words) > 2 and words[1].lower() in {"is", "of", "for", "and", "as", "in", "the", "to"} and words[2][:1].isupper():
        return text  # a title-case name such as "Food is Medicine" or "Women of Color"
    return text[0].lower() + text[1:]


def _tidy_phrase(text: str) -> str:
    """Drop parenthetical lists, unclosed brackets, third-person asides ("which he founded") and stray spaces."""
    text = re.sub(r"\s*\([^)]*\)", "", text)
    text = re.sub(r"\s*[(\[][^)\]]*$", "", text)  # a bracket that is never closed
    text = re.sub(r",?\s*(?:which|that|where|whom?)\s+(?:he|she|they)\b.*$", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" ,;.")


_NOT_A_TOPIC_RE = re.compile(
    r"\b(?:research group|lab|laboratory|center|centre|institute)\s*$"  # a lab or group name
    r"|^(?:directs|leads|co-leads|heads|chairs|manages|coordinates|oversees|founded|serves|is|was)\b"  # a role, not research
    r"|\b(?:he|she|his)\b"  # written about the professor in the third person; wrong in a letter to them
    # a job title: "Interim Assistant Director, ...", "Head of ...", "Chair" (but not "Head Start obesity prevention")
    r"|^(?:(?:interim|acting|founding)\s+)?(?:(?:assistant|associate|deputy|executive)\s+)?"
    r"(?:director|chair|head|dean|coordinator)\b(?:\s+(?:of|for)\b|\s*,|\s*$)",
    re.IGNORECASE,
)


def _is_topic_phrase(phrase: str) -> bool:
    """False for lab names and job titles ("Food Policy and Environmental Research Group", "Interim Assistant Director")."""
    tidy = _tidy_phrase(phrase)
    return bool(tidy) and not _NOT_A_TOPIC_RE.search(tidy)


def strong_topics(research_text: str) -> set[str]:
    """Topics with specific (strong) keyword evidence in the professor's own research text."""
    return {k for k, v in match_topics(research_text or "").items() if v.is_strong}


def order_topics(topics: list[str], research_text: str) -> list[str]:
    """Strongly evidenced topics first, then the most specific; drop 'diabetes' when it only came from the
    word 'obesity' in child-obesity work."""
    topics = list(dict.fromkeys(topics))
    if "childhood_obesity" in topics and "diabetes_metabolic" in topics:
        if not re.search(r"diabet|glyc|glucose|insulin|metabolic|cardiometabolic", research_text or "", re.IGNORECASE):
            topics.remove("diabetes_metabolic")
    strong = strong_topics(research_text)
    return sorted(topics, key=lambda t: (0 if t in strong else 1, SPECIFICITY.index(t) if t in SPECIFICITY else 99))


def topic_words(key: str, research_text: str, table: dict[str, str]) -> str:
    """Label for a topic in an email. 'diabetes prevention' is used only when the professor's own research text
    mentions diabetes or glucose; obesity work is called 'obesity and metabolic health'."""
    if key == "diabetes_metabolic":
        text = research_text or ""
        if re.search(r"diabet|glyc|glucose|insulin|hba1c|blood sugar", text, re.IGNORECASE):
            return table[key]
        if re.search(r"obes|adipos|overweight|weight", text, re.IGNORECASE):
            return "obesity" if table is SUBJECT_TOPIC else "obesity and metabolic health"
        return "metabolic health"
    return table.get(key, "")


def _join_topics(keys: list[str], research_text: str = "") -> str:
    labels = [topic_words(k, research_text, SHORT_TOPIC) for k in keys if k in SHORT_TOPIC]
    if not labels:
        return "nutrition research"
    if len(labels) == 1:
        return labels[0]
    joiner = " as well as " if " and " in labels[0] or " and " in labels[1] else " and "
    return f"{labels[0]}{joiner}{labels[1]}"


def _publication(record: dict, today: date, applicant_topics: set[str] | None = None) -> tuple[str, str]:
    """(year, title) of the most recent recorded publication on one of the applicant's topics, or ('', '')."""
    for n in (1, 2):
        title = clean(record.get(f"relevant_publication_{n}")).rstrip(".")
        if title and applicant_topics is not None and not (set(match_topics(title)) & applicant_topics):
            continue  # a paper outside the applicant's interests is not mentioned
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
    if clean(record.get("last_contact_date")):
        return False, f"already contacted on {clean(record.get('last_contact_date'))} - only a follow-up is possible (followups --draft)"
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
    if not meaningful(record.get("research_interests", "")):
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
    parts = focus_parts(record, applicant_topics)
    research_text = meaningful(record.get("research_interests", ""))
    record_topics = [t for t in split_multi(record.get("matched_topics", "")) if t in applicant_topics]
    pub_topics = match_topics(" ".join(clean(record.get(f"relevant_publication_{n}")) for n in (1, 2)))
    pub_year, pub_title = _publication(record, today, applicant_topics)
    pub = bool(pub_title)
    paper = f'your {pub_year} paper, "{pub_title},"' if pub_year else f'your paper, "{pub_title},"'
    if not parts:
        warnings.append("No research interests to quote; the email will be generic. Add research_interests first.")
    if not pub:
        warnings.append("No recent publication is recorded for this professor.")
    personal = collapse_spaces(record.get("personal_note", ""))
    if personal and personal[-1] not in ".!?":
        personal += "."
    if not personal:
        warnings.append("Tip: after reading their recent work, add one sentence of your own in 'personal_note'.")

    v = _variant(record, 2)
    if cgpa:
        intro = (
            f"My name is {name}, and I recently completed a {degree_short} at {place}, with a CGPA of {cgpa}."
            if v == 0
            else f"I am {name}, a recent graduate of {place}, where I completed a {degree_short} with a CGPA of {cgpa}."
        )
    else:
        intro = f"My name is {name}, and I recently completed a {degree_short} at {place}."
    lead = "This connects with my own experience." if v == 0 else "My background has prepared me for this kind of work."

    university = clean_university_name(record.get("university", ""))
    program = clean_program_name(record.get("graduate_program", ""), university)
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
    cv = prefs.get("mention_cv_attached", True)
    closings = (
        "I have attached my CV for your reference and would be happy to share any additional information. "
        "Thank you very much for your time and consideration." if cv else "Thank you very much for your time and consideration.",
        "I have attached my CV. Thank you for your time and consideration." if cv else "Thank you for your time and consideration.",
    )
    signature = "\n".join(clean(line) for line in (profile.get("signature_lines") or [name]) if clean(line))

    def topics_for(used: list[tuple[str, list[str], int]]) -> list[str]:
        """Topics of the phrases actually quoted, so the subject and the interest sentence match the quote."""
        quoted: list[str] = []
        for _, phrase_topics, _ in used:
            quoted.extend(t for t in phrase_topics if t not in quoted)
        topics = order_topics(quoted or record_topics or list(match_topics(research_text)), research_text)
        if "ai_ml" in pub_topics and pub_topics["ai_ml"].is_strong and "ai_ml" not in topics:
            topics.append("ai_ml")  # their own recent paper uses data-science methods
        return topics

    def compose(n_parts: int, n_evidence: int, short_closing: bool):
        used = parts if n_parts >= len(parts) else ([best_part(parts)] if parts else [])
        topics = topics_for(used)
        focus = join_focus([phrase for phrase, _, _ in used]) or "nutrition"
        interest_phrase = _join_topics([t for t in topics if t != "ai_ml"][:2] or topics[:1], research_text)
        focus_text = f"{focus}," if ", as well as " in focus else focus
        if v == 0:
            interest = f"I am writing because your research on {focus_text} closely aligns with my interest in {interest_phrase}."
            if pub:
                interest += f" {paper[0].upper() + paper[1:]} is especially relevant to the questions I hope to study."
        else:
            interest = f"I am reaching out because your work on {focus_text} matches the research I hope to pursue in graduate school, particularly in {interest_phrase}."
            if pub:
                interest += f" I noticed {paper} which is closely related to the questions I hope to study."
        if personal:
            interest += " " + personal
        evidence = choose_evidence(profile, topics)[:n_evidence]
        background = lead + " " + _evidence_sentences(evidence) if evidence else ""
        paragraphs = [greeting, intro + " " + interest, background, ask, closings[1 if short_closing else 0], "Sincerely,\n" + signature]
        return paragraphs, topics, evidence

    def body_words(paras: list[str]) -> int:
        return sum(len(p.split()) for p in paras[1:-1] if p)  # greeting and signature not counted

    max_words = int(prefs.get("max_words", 220) or 220)
    # Shorten step by step until the body fits: one CV example, then one research phrase, then a shorter closing.
    for n_parts, n_evidence, short_closing in ((2, 2, False), (2, 1, False), (1, 1, False), (1, 1, True)):
        paragraphs, professor_topics, evidence = compose(n_parts, n_evidence, short_closing)
        words = body_words(paragraphs)
        if words <= max_words:
            break
    if words > max_words:
        warnings.append(f"The email body has {words} words (target {max_words}). Consider shortening it.")
    if not evidence:
        warnings.append("No matching experience was found in your profile for this professor's topics.")
    body = "\n\n".join(p for p in paragraphs if p)

    # The subject names a topic only when the professor's own research text gives specific (strong) evidence for it.
    strong = strong_topics(research_text)
    subject_topics = [t for t in professor_topics if t != "ai_ml" and t in strong][:1] or [t for t in professor_topics if t in strong][:1]
    topic_for_subject = (topic_words(subject_topics[0], research_text, SUBJECT_TOPIC) or "nutrition") if subject_topics else "nutrition"
    degree_for_subject = degree.replace(" or ", "/")
    subject = f"Prospective {degree_for_subject} student ({intake_short}): interest in your {topic_for_subject} research"
    if len(subject) > 95:
        subject = f"Prospective {degree_for_subject} student ({intake_short}): research inquiry"
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
