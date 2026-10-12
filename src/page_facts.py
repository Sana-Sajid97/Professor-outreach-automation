"""Reading official page text: research claims, program facts and funding evidence.

Pure functions over page text, so every rule can be tested offline. Nothing here invents a
fact: each finding carries the sentence it came from, and anything not found is reported as
"not found" instead of being guessed.
"""

from __future__ import annotations

import re

from .textutil import clean, find_dates, find_month_days, strip_accents

BLOCK_TAGS = [
    "p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "dd", "dt", "tr", "br", "div", "section",
    "article", "blockquote", "ul", "ol", "table", "caption", "figcaption", "pre", "address",
]


# ------------------------------------------------------------------ page text
def page_blocks(html: str) -> list[str]:
    """The page's readable text as blocks (paragraphs, list items, headings, table cells).
    Menus and footers are left out, because their link lists ("Funding", "Programs") are not facts."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "form", "svg"]):
        tag.decompose()
    for tag in soup.find_all(attrs={"role": "navigation"}):
        tag.decompose()
    for tag in soup.find_all(BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    blocks = []
    for line in soup.get_text(" ").split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) >= 3:
            blocks.append(line)
    return blocks


def sentences(blocks: list[str]) -> list[str]:
    out = []
    for block in blocks:
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", block):
            part = part.strip()
            if len(part) >= 3:
                out.append(part)
    return out


def shorten(text: str, focus: str = "", width: int = 280) -> str:
    """A quote of at most `width` characters, centred on `focus` when the sentence is long."""
    text = clean(text)
    if len(text) <= width:
        return text
    pos = text.lower().find(focus.lower()) if focus else -1
    start = max(0, (pos - width // 3) if pos >= 0 else 0)
    cut = text[start:start + width]
    if start > 0:
        cut = "…" + cut[cut.find(" ") + 1:] if " " in cut else "…" + cut
    if start + width < len(text):
        cut = cut[: cut.rfind(" ")] + "…" if " " in cut else cut + "…"
    return cut


# ------------------------------------------------------------------ research claims
def research_items(raw: str) -> list[str]:
    """Split recorded research interests into phrases (on ';', '|' or new lines, never inside brackets).
    One very long entry is cut into its first comma-separated parts. Verify and the email writer both use
    this, so the phrases that are checked are exactly the phrases an email can quote."""
    items, depth, current = [], 0, []
    for ch in raw or "":
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
    if len(out) == 1 and len(out[0]) > 140:
        chunk = ""
        for part in out[0].split(", "):
            if len(chunk) + len(part) > 120 and chunk:
                break
            chunk = f"{chunk}, {part}" if chunk else part
        out = [chunk]
    return out


def same_phrase(a: str, b: str) -> bool:
    return " ".join(_words(a)) == " ".join(_words(b))


STOPWORDS = set(
    "a an and are as at be been being but by can for from has have in into is it its of on or that the their this "
    "to was were which with within without our your his her they them we you also such these those than then".split()
)
GENERIC = {
    "research", "researches", "researcher", "study", "studies", "studying", "focus", "focuses", "focused", "focusing",
    "include", "includes", "including", "interest", "interests", "interested", "area", "areas", "work", "works",
    "working", "role", "roles", "effect", "effects", "impact", "impacts", "use", "using", "used", "based", "among",
    "related", "relation", "relationship", "relationships", "approach", "approaches", "new", "novel", "various",
    "current", "topic", "topics", "aspect", "aspects", "issues", "via", "across", "particular", "especially",
}
_SUFFIXES = ("ational", "ations", "ation", "ities", "ity", "ically", "ical", "ness", "ments", "ment", "ings", "ing",
             "ies", "ied", "ers", "er", "ed", "es", "s", "al", "ic")


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            stem = word[: -len(suffix)]
            return stem + "y" if suffix in ("ies", "ied") else stem
    return word


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", strip_accents(text or "").lower())


def content_words(text: str) -> list[tuple[str, str]]:
    """(word, stem) pairs for the meaningful words of a phrase, in order, without repeats."""
    out, seen = [], set()
    for word in _words(text):
        if len(word) < 3 or word in STOPWORDS or word in GENERIC:
            continue
        stem = _stem(word)
        if stem not in seen:
            seen.add(stem)
            out.append((word, stem))
    return out


def stem_set(text: str) -> set[str]:
    return {_stem(w) for w in _words(text) if len(w) >= 3}


def _best_quote(sents: list[str], stems: set[str]) -> str:
    best, best_score = "", 0
    for sent in sents:
        score = len(stems & stem_set(sent))
        if score > best_score or (score == best_score and score and len(sent) < len(best)):
            best, best_score = sent, score
    return shorten(best) if best_score else ""


def research_support(phrases: list[str], blocks: list[str]) -> list[dict]:
    """For each recorded research phrase: is it supported by the official page text?

    supported   at least 60% of its meaningful words appear on the page (and at least two of them)
    partly      at least a third of them appear
    unsupported fewer than that: the email must not present it as this professor's research
    """
    page_stems = stem_set(" ".join(blocks))
    sents = sentences(blocks)
    results = []
    for phrase in phrases:
        words = content_words(phrase)
        if not words:
            continue
        matched = [(w, s) for w, s in words if s in page_stems]
        coverage = len(matched) / len(words)
        if coverage >= 0.6 and (len(matched) >= 2 or len(words) == 1):
            level = "supported"
        elif coverage >= 0.34 and matched:
            level = "partly"
        else:
            level = "unsupported"
        results.append({
            "phrase": phrase,
            "level": level,
            "coverage": round(coverage, 2),
            "missing": [w for w, s in words if s not in page_stems],
            "quote": _best_quote(sents, {s for _, s in matched}) if matched else "",
        })
    return results


_RESEARCH_HEADING_RE = re.compile(
    r"research (?:interests?|areas?|focus|program|summary)|areas? of (?:expertise|research|interest)|expertise|specialt(?:y|ies)|focus areas?",
    re.IGNORECASE,
)


def research_excerpt(html: str, limit: int = 600) -> str:
    """The text under a 'Research interests' (or similar) heading on the official page, if there is one."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer"]):
        tag.decompose()
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "dt", "th"]):
        title = heading.get_text(" ", strip=True)
        if len(title) > 60 or not _RESEARCH_HEADING_RE.search(title):
            continue
        parts = []
        for sib in heading.find_all_next(True, limit=40):
            if sib.name in ("h1", "h2", "h3", "h4") and sib is not heading:
                break
            if sib.name in ("p", "li", "dd", "td", "span", "div") and not sib.find(["p", "li", "div"]):
                text = re.sub(r"\s+", " ", sib.get_text(" ", strip=True))
                if text and text != title and text not in parts:
                    parts.append(text)
            if sum(len(p) for p in parts) > limit:
                break
        excerpt = "; ".join(parts)
        if excerpt:
            return shorten(excerpt, width=limit)
    return ""


# Ordinary email wording around a claim ("... closely aligns with ...") is not part of the claim.
CLAIM_IGNORE = {
    "closely", "aligns", "align", "aligned", "matches", "match", "matching", "relevant", "especially", "particularly",
    "relates", "connects", "connected", "directly", "strongly", "fits", "fit", "inspired", "fascinated", "excited",
    "impressed", "noticed", "learned", "which", "very", "much", "really", "great", "deeply", "greatly", "highly",
    "well", "would", "could", "should", "will", "shall", "please", "thank", "thanks", "dear", "professor",
}


def unsupported_claim_words(body: str, page_text: str, extra_text: str = "") -> list[str]:
    """Words in the email's sentences about the professor ("your research/work/paper ...") that do not
    appear on the official page (or in the recorded paper titles). Used to flag edits that add claims."""
    known = stem_set(page_text) | stem_set(extra_text)
    missing = []
    for sentence in re.split(r"(?<=[.!?])\s+", body or ""):
        sentence = re.sub(r'"[^"]*"|“[^”]*”', " ", sentence)  # a paper title is checked separately
        for m in re.finditer(r"\byour (?:research|work|paper|study|studies|lab|group|project|article|program)\b", sentence, re.IGNORECASE):
            # From "your research ..." up to where the applicant talks about herself ("my interest", "I hope").
            about_them = re.split(r"\b(?:my|I|me)\b", sentence[m.end():], maxsplit=1)[0]
            for word, stem in content_words(about_them):
                if stem not in known and word not in CLAIM_IGNORE and word not in missing and not word.isdigit():
                    missing.append(word)
    return missing


# ------------------------------------------------------------------ program facts
_DEGREE_RE = re.compile(
    r"\b(Ph\.?\s?D\.?|Doctor of Philosophy|M\.S\.|MS|M\.Sc\.|MSc|Master of Science|Master's|Masters|M\.P\.H\.|MPH)"
    r"(?:\s+(?:degree\s+)?(?:program\s+)?(?:in|of)\s+((?:[A-Z][\w&'/-]*)(?:\s+(?:and|&|of|in|[A-Z][\w&'/-]*)){0,6}))?"
)
_TERM_CONTEXT = r"admi|appl|deadline|entry|enter|start|begin|semester|term|intake|cohort|matriculat|enrol"
_NO_SPRING = re.compile(
    r"\b(?:no|not)\b[^.]{0,40}\bspring\b|\bspring\b[^.]{0,40}\b(?:not (?:offered|available|accepted|considered)|no longer)"
    r"|\bfall (?:semester |term )?only\b|\bonly (?:in|for) (?:the )?fall\b|\badmits? (?:students )?(?:only )?(?:once a year|in the fall only)",
    re.IGNORECASE,
)
_NO_FALL = re.compile(
    r"\b(?:no|not)\b[^.]{0,40}\b(?:fall|autumn)\b|\b(?:fall|autumn)\b[^.]{0,40}\bnot (?:offered|available|accepted)|\bspring (?:semester |term )?only\b",
    re.IGNORECASE,
)
_DEADLINE_CONTEXT = re.compile(
    r"deadline|apply by|\bdue\b(?! to\b)|priority|full consideration|applications? (?:are |must be |will be )?(?:received|submitted|reviewed|accepted)|closes?\b",
    re.IGNORECASE,
)
_IELTS_NUMBER = r"([4-9](?:\.[05])?)"


def _degree_names(blocks: list[str]) -> list[str]:
    names = []
    for block in blocks:  # block by block, so a name never runs into the next paragraph
        for m in _DEGREE_RE.finditer(block):
            name = m.group(1) + (f" in {m.group(2)}" if m.group(2) else "")
            name = re.sub(r"\s+", " ", name).strip()
            if name not in names:
                names.append(name)
    return names[:6]


def _intake(sents: list[str], term: str, record_says_open: bool | None) -> dict:
    term_re = re.compile(r"\bspring\b" if term == "spring" else r"\b(?:fall|autumn)\b", re.IGNORECASE)
    negative = _NO_SPRING if term == "spring" else _NO_FALL
    hits = [s for s in sents if term_re.search(s) and re.search(_TERM_CONTEXT, s, re.IGNORECASE)]
    label = "Spring" if term == "spring" else "Fall"
    for s in hits + [s for s in sents if negative.search(s)]:
        if negative.search(s):
            if record_says_open:
                return {"status": "failed", "detail": f"Conflict: the official page says there is no {label} entry, but the record says it is open.", "quote": shorten(s, term)}
            return {"status": "warning", "detail": f"Official page: no {label} entry.", "quote": shorten(s, term)}
    if hits:
        best = next((s for s in hits if "2027" in s), hits[0])
        detail = f"{label} entry is mentioned on the official page" + (" (for 2027)." if "2027" in best else ". Check that it applies to 2027.")
        return {"status": "passed", "detail": detail, "quote": shorten(best, term)}
    return {"status": "warning", "detail": f"{label} entry is not mentioned on this page.", "quote": ""}


def _deadlines(sents: list[str]) -> dict:
    found = []
    for s in sents:
        if not _DEADLINE_CONTEXT.search(s):
            continue
        texts = [d.strftime("%d %b %Y").lstrip("0") for d in find_dates(s)]
        texts += [f"{day} {('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split())[month - 1]} (no year given)" for month, day in find_month_days(s)]
        for t in texts:
            if all(t != f["date"] for f in found):
                found.append({"date": t, "quote": shorten(s)})
    if found:
        return {"status": "passed", "detail": f"{len(found)} deadline date(s) on the official page: " + ", ".join(f["date"] for f in found[:6]) + ".", "found": found[:8]}
    return {"status": "warning", "detail": "No deadline dates found on this page.", "found": []}


def _ielts(sents: list[str], applicant_ielts: float | None) -> dict:
    for s in sents:
        if not re.search(r"\bIELTS\b", s):
            continue
        window = s[s.upper().find("IELTS"):][:160]
        m = re.search(r"(?:overall|minimum|at least|total|band score of|score of)\D{0,25}?" + _IELTS_NUMBER, window, re.IGNORECASE) or re.search(
            _IELTS_NUMBER + r"\s*(?:overall|or higher|or above|or better|minimum)", window, re.IGNORECASE
        ) or re.search(r"(?<![\d.])" + _IELTS_NUMBER + r"(?![\d.])", window)
        if not m:
            continue
        required = float(m.group(1))
        quote = shorten(s, "IELTS")
        if applicant_ielts is None:
            return {"status": "passed", "detail": f"Official page: IELTS {required:.1f} minimum.", "required": required, "quote": quote}
        if required <= applicant_ielts:
            return {"status": "passed", "detail": f"Official page: IELTS {required:.1f} minimum; you have {applicant_ielts:.1f}.", "required": required, "quote": quote}
        return {"status": "failed", "detail": f"Official page: IELTS {required:.1f} minimum, but you have {applicant_ielts:.1f}.", "required": required, "quote": quote}
    return {"status": "warning", "detail": "The IELTS requirement is not stated on this page (check the Graduate School's English page).", "quote": ""}


def _requirements(sents: list[str]) -> dict:
    items = []

    def add(text: str, quote: str) -> None:
        if all(text != i["item"] for i in items):
            items.append({"item": text, "quote": shorten(quote)})

    for s in sents:
        low = s.lower()
        if re.search(r"\bGRE\b", s):
            if re.search(r"not required|optional|waived|not accepted|no longer required|not considered", low):
                add("GRE not required", s)
            elif "required" in low:
                add("GRE required", s)
        m = re.search(r"\b(two|three|four|2|3|4)\s+(?:letters? of (?:recommendation|reference)|recommendation letters|references)", low)
        if m:
            add(f"{m.group(1)} letters of recommendation", s)
        if re.search(r"statement of purpose|personal statement|statement of (?:interest|intent)", low):
            add("Statement of purpose", s)
        if re.search(r"\b(?:wes|ece)\b|credential evaluation|course-by-course", low):
            add("Credential evaluation (WES/ECE)", s)
        if re.search(r"writing sample", low):
            add("Writing sample", s)
        fee = re.search(r"application fee[^.$]{0,30}\$\s?(\d{2,3})", low)
        if fee:
            add(f"Application fee ${fee.group(1)}", s)
        toefl = re.search(r"\btoefl\b[^.]{0,60}?(\d{2,3})", low)
        if toefl and 60 <= int(toefl.group(1)) <= 120:
            add(f"TOEFL iBT {toefl.group(1)}", s)
    if items:
        return {"status": "passed", "detail": "; ".join(i["item"] for i in items[:8]) + ".", "found": items[:10]}
    return {"status": "warning", "detail": "No admission requirements found on this page.", "found": []}


def program_facts(blocks: list[str], applicant_ielts: float | None = None, program_name: str = "",
                  spring_open: bool | None = None, fall_open: bool | None = None) -> dict:
    """Facts from an official program page, each with its quote, and an overall status."""
    sents = sentences(blocks)
    text = " ".join(blocks)
    degrees = _degree_names(blocks)
    field_words = [w for w, _ in content_words(re.sub(r"\b(?:ph\.?d|m\.?s|master'?s?|doctor|philosophy|science|degree|program)\b", " ", program_name, flags=re.IGNORECASE))]
    page_stems = stem_set(text)
    field_ok = bool(field_words) and all(_stem(w) in page_stems for w in field_words)
    if degrees and (field_ok or not field_words):
        degree = {"status": "passed", "detail": "Degree(s) named on the official page: " + "; ".join(degrees[:4]) + "."}
    elif degrees:
        degree = {"status": "warning", "detail": f"The page names {'; '.join(degrees[:3])}, but not '{program_name}'. Check this is the right program page."}
    else:
        degree = {"status": "warning", "detail": "No degree name (PhD/MS) found on this page."}
    items = {
        "degree": degree,
        "spring": _intake(sents, "spring", spring_open),
        "fall": _intake(sents, "fall", fall_open),
        "deadlines": _deadlines(sents),
        "ielts": _ielts(sents, applicant_ielts),
        "requirements": _requirements(sents),
    }
    statuses = {k: v["status"] for k, v in items.items()}
    if "failed" in statuses.values():
        failed = [items[k]["detail"] for k, v in statuses.items() if v == "failed"]
        status, detail = "failed", " ".join(failed)
    elif statuses["degree"] == "passed" and (statuses["deadlines"] == "passed" or "passed" in (statuses["spring"], statuses["fall"])):
        status, detail = "passed", "Program page checked: degree and intake or deadline information found."
    else:
        status, detail = "warning", "Program page checked, but some facts were not found on it (see each item)."
    return {"status": status, "detail": detail, "items": items}


# ------------------------------------------------------------------ funding evidence
_FUNDING_WORD = re.compile(
    r"assistantships?|research assistant|teaching assistant|graduate assistant|\bGRAs?\b|\bGTAs?\b|stipends?|"
    r"tuition (?:waiver|remission)|fully[- ]funded|full funding|funding|financial support|financial aid|fellowships?|"
    r"self[- ]funded|\bunfunded\b|\bnot funded\b|\bfunded (?:ph\.?d|doctoral|graduate|positions?|students?|assistantships?)",
    re.IGNORECASE,
)
_NO_FUNDING = re.compile(
    r"\b(?:no|not)\b[^.]{0,40}\b(?:funding|assistantships?|financial support|stipends?)\b|self[- ]funded|\bunfunded\b|\bnot funded\b"
    r"|do(?:es)? not (?:offer|provide|guarantee) (?:any )?(?:funding|assistantships?|financial support)",
    re.IGNORECASE,
)
_HEDGE = re.compile(r"\b(?:may|might|can|could|some|limited|competitive|possible|possibly|subject to|not guaranteed|if available|depending)\b", re.IGNORECASE)
_GUARANTEE = re.compile(
    r"\b(?:ph\.?d\.?|doctoral|graduate|admitted|accepted|incoming|all|every)\b[^.]{0,60}\bstudents?\b[^.]{0,60}"
    r"\b(?:receive|receives|are offered|are provided|are guaranteed|are supported|will receive|get|are funded|is funded)\b[^.]{0,80}"
    r"\b(?:assistantships?|stipends?|funding|support|tuition)"
    r"|\bguaranteed\s+(?:funding|support|assistantships?|stipends?)"
    r"|(?:assistantships?|stipends?)[^.]{0,60}\b(?:include|includes|with|plus)\b[^.]{0,30}tuition (?:waiver|remission)",
    re.IGNORECASE,
)
_FULLY_FUNDED = re.compile(r"\bfully[- ]funded\b|\bfull funding\b", re.IGNORECASE)
_STUDENT_WORDS = re.compile(r"\bstudents?\b|ph\.?d|doctoral|graduate|positions?|assistantships?", re.IGNORECASE)
_POSITION = re.compile(
    r"\b(?:recruiting|seeking|looking for|hiring|accepting)\b[^.]{0,60}\b(?:ph\.?d\.?|doctoral|graduate|m\.?s\.?|master'?s)\b[^.]{0,40}\b(?:students?|candidates?|positions?)\b"
    r"|\b(?:funded|open)\b[^.]{0,20}\b(?:ph\.?d\.?|doctoral|graduate|m\.?s\.?)\b[^.]{0,20}\b(?:positions?|assistantships?|openings?)\b",
    re.IGNORECASE,
)
_POSITION_FUNDED = re.compile(r"funded|funding|assistantships?|stipends?|support", re.IGNORECASE)
KIND_ORDER = {"open_position": 0, "program_guarantee": 1, "active_grant": 2, "general": 3, "no_funding": 4}
KIND_WORDS = {
    "open_position": "A professor or lab says they are recruiting a funded student",
    "program_guarantee": "The program says admitted students receive funding",
    "active_grant": "Active research grant (funds may exist; not a position offer)",
    "general": "Assistantships or funding mentioned in general",
    "no_funding": "The page says funding is not available for some students",
}


def funding_evidence(blocks: list[str], url: str) -> list[dict]:
    """Funding sentences from one official page, each classified. The quote is the evidence."""
    out = []
    for s in sentences(blocks):
        if not _FUNDING_WORD.search(s):
            continue
        if _NO_FUNDING.search(s) and not re.search(r"not guaranteed", s, re.IGNORECASE):
            kind = "no_funding"
        elif _POSITION.search(s) and _POSITION_FUNDED.search(s) and not _HEDGE.search(s):
            kind = "open_position"
        elif (_GUARANTEE.search(s) or (_FULLY_FUNDED.search(s) and _STUDENT_WORDS.search(s))) and not _HEDGE.search(s):
            kind = "program_guarantee"
        else:
            kind = "general"
        stipend = re.search(r"\$\s?\d{1,3}(?:,\d{3})+(?:\.\d+)?", s)
        out.append({"url": url, "kind": kind, "quote": shorten(s, stipend.group(0) if stipend else _FUNDING_WORD.search(s).group(0))})
    out.sort(key=lambda e: KIND_ORDER[e["kind"]])
    return out[:8]


def funding_level(evidence: list[dict]) -> str:
    kinds = {e["kind"] for e in evidence}
    if kinds & {"open_position", "program_guarantee"}:
        return "confirmed"
    if kinds & {"general", "active_grant"}:
        return "possible"
    if "no_funding" in kinds:
        return "not_available"
    return "not_verified"
