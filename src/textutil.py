"""Small text helpers: normalising names, emails, URLs, domains and dates."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
EMAIL_FIND_RE = re.compile(
    r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}"
)
URL_FIND_RE = re.compile(r"https?://[^\s<>\"')\];,|]+", re.IGNORECASE)

NAME_TITLES = {
    "dr", "prof", "professor", "mr", "mrs", "ms", "miss", "mx", "phd", "rd", "rdn", "ld", "ldn",
    "mph", "msc", "md", "scd", "drph", "msph", "faand", "fasn", "ccrp", "cde", "cdces", "facn", "ibclc",
    "jr", "sr", "ii", "iii", "iv", "mba", "mpp", "mpa", "rn", "bsn", "msn", "dnp", "facsm", "edd",
}
GENERIC_LOCAL_PARTS = {
    "info", "admissions", "admission", "gradadmissions", "graduate", "grad", "gradschool", "webmaster",
    "contact", "office", "help", "support", "communications", "news", "media", "alumni", "giving", "hr",
    "jobs", "careers", "noreply", "no-reply", "privacy", "accessibility", "web", "marketing", "registrar",
    "advising", "studentservices", "nutrition", "dean", "deansoffice", "frontdesk", "reception", "events",
    "gradprogram", "gradinfo", "graduateprogram", "graduatestudies", "department", "dept", "mail",
}
# Two-label public suffixes where the registrable domain has three labels.
_SECOND_LEVEL_SUFFIXES = {"ac", "co", "com", "edu", "gov", "net", "org", "or", "ne", "go"}


def clean(value) -> str:
    if value is None:
        return ""
    return str(value).replace("​", "").replace("﻿", "").strip()


def collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", clean(text)).strip()


def is_blank_or_unknown(value: str) -> bool:
    """True for empty values and explicit 'unknown' markers such as 'Not verified'."""
    v = collapse_spaces(value).lower().strip(" .-")
    return v in {"", "not verified", "unknown", "n/a", "na", "none", "tbd", "not found", "not stated", "?"}


_PLACEHOLDER_START_RE = re.compile(
    r"^(?:not verified|not captured|not found|not listed|not available|not stated|not known|unknown|n/?a\b|none\b|tbd\b)",
    re.IGNORECASE,
)


def is_placeholder(value: str) -> bool:
    """True for empty values and research notes that stand in for a missing fact,
    e.g. 'Not verified (advisor on a 2023 thesis)' or 'Not captured in search results'."""
    return is_blank_or_unknown(value) or bool(_PLACEHOLDER_START_RE.match(collapse_spaces(value)))


def meaningful(value: str) -> str:
    """The value, or '' when it is only a placeholder such as 'Not verified ...'."""
    return "" if is_placeholder(value) else clean(value)


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def split_multi(value: str) -> list[str]:
    """Split a multi-value cell ("a; b | c" or one per line) into a clean list."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        items = [clean(v) for v in value]
    else:
        items = re.split(r"\s*(?:;|\n|\|)\s*", clean(value))
    seen, out = set(), []
    for item in items:
        item = item.strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out


def join_multi(items) -> str:
    return "; ".join(split_multi(list(items)))


def find_urls(text: str) -> list[str]:
    return [u.rstrip(".") for u in URL_FIND_RE.findall(text or "")]


# ---------------- emails ----------------
def normalize_email(email: str) -> str:
    e = clean(email).strip("<>()[]{}\"' ").rstrip(".,;:")
    if e.lower().startswith("mailto:"):
        e = e[7:]
    e = e.split("?", 1)[0]
    return e.strip().lower()


def is_valid_email(email: str) -> bool:
    e = normalize_email(email)
    return bool(e) and len(e) <= 254 and bool(EMAIL_RE.match(e)) and ".." not in e


def email_domain(email: str) -> str:
    e = normalize_email(email)
    return e.rsplit("@", 1)[1] if "@" in e else ""


def email_local(email: str) -> str:
    e = normalize_email(email)
    return e.rsplit("@", 1)[0] if "@" in e else ""


def is_generic_email(email: str) -> bool:
    local = re.sub(r"[^a-z0-9-]", "", email_local(email))
    return local in GENERIC_LOCAL_PARTS


# ---------------- URLs and domains ----------------
def url_host(url: str) -> str:
    try:
        host = urlsplit(clean(url)).hostname or ""
    except ValueError:
        return ""
    return host.lower().rstrip(".")


def is_valid_url(url: str) -> bool:
    u = clean(url)
    if not u or " " in u:
        return False
    try:
        parts = urlsplit(u)
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and bool(parts.hostname) and "." in (parts.hostname or "")


def registrable_domain(host: str) -> str:
    """'nutrition.cals.cornell.edu' -> 'cornell.edu'; 'uaar.edu.pk' -> 'uaar.edu.pk'."""
    host = (host or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    labels = [label for label in host.split(".") if label]
    if len(labels) <= 2:
        return ".".join(labels)
    if len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def same_institution_domain(a_host: str, b_host: str) -> bool:
    return bool(a_host) and bool(b_host) and registrable_domain(a_host) == registrable_domain(b_host)


def is_official_academic_host(host: str) -> bool:
    """US universities almost always use .edu; anything else needs a human check."""
    host = (host or "").lower()
    return host.endswith(".edu") or host == "edu"


_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}


def normalize_url(url: str) -> str:
    """Canonical form used only for duplicate detection (not for display)."""
    u = clean(url)
    if not u:
        return ""
    if "://" not in u:
        u = "https://" + u
    try:
        parts = urlsplit(u)
    except ValueError:
        return u.lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+", "/", parts.path or "/")
    path = re.sub(r"/(index|default)\.(html?|php|aspx?)$", "/", path, flags=re.IGNORECASE)
    path = path.rstrip("/") or "/"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _TRACKING_PARAMS))
    return urlunsplit(("https", host, path.lower(), query, ""))


# ---------------- names ----------------
def name_tokens(name: str) -> list[str]:
    """Lower-case name words without titles, degrees or punctuation.

    Handles "First Last, PhD, RD" and "Last, First" orders.
    """
    text = strip_accents(clean(name)).lower()
    text = re.sub(r"\(.*?\)", " ", text)  # nicknames in parentheses
    if "," in text:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        head = parts[0]
        rest_are_degrees = all(
            all(w.strip(".") in NAME_TITLES for w in p.split()) for p in parts[1:]
        )
        if len(head.split()) >= 2 or rest_are_degrees:
            text = head  # "First Last, PhD, RD"
        elif len(parts) >= 2:
            text = parts[1] + " " + head  # "Last, First"
    tokens = []
    for raw in text.split():
        token = raw.strip(".'\"`")
        if not token or token.replace(".", "") in NAME_TITLES:
            continue
        token = re.sub(r"[^a-z0-9-]", "", token)
        if token:
            tokens.append(token)
    return tokens


def normalize_name(name: str) -> str:
    return " ".join(name_tokens(name))


def name_key(name: str) -> str:
    """First + last name only (ignores middle names and initials)."""
    tokens = [t for t in name_tokens(name) if len(t.replace("-", "")) > 1]
    if not tokens:
        return ""
    if len(tokens) == 1:
        return tokens[0]
    return f"{tokens[0]} {tokens[-1]}"


def last_name(name: str) -> str:
    """Display form of the surname, e.g. 'Pérez-Escamilla' from 'Rafael Pérez-Escamilla, PhD'."""
    text = re.sub(r"\(.*?\)", " ", clean(name))
    if "," in text:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        head = parts[0]
        rest_are_degrees = all(
            all(strip_accents(w).lower().strip(".") in NAME_TITLES for w in p.split()) for p in parts[1:]
        )
        if len(head.split()) >= 2 or rest_are_degrees:
            text = head
        else:
            return head  # "Last, First"
    words = [w.strip(".,") for w in text.split() if w.strip(".,")]
    words = [w for w in words if strip_accents(w).lower().replace(".", "") not in NAME_TITLES]
    if not words:
        return clean(name)
    particles = {"van", "von", "de", "del", "della", "da", "di", "du", "dos", "das", "la", "le", "bin", "al", "el"}
    surname = [words[-1]]
    i = len(words) - 2
    while i > 0 and words[i].lower() in particles:
        surname.insert(0, words[i])
        i -= 1
    return " ".join(surname)


def first_name(name: str) -> str:
    tokens = name_tokens(name)
    return tokens[0] if tokens else ""


def normalize_university(name: str) -> str:
    text = strip_accents(clean(name)).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"\buniv\.?\b", "university", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    words = [w for w in text.split() if w not in {"the", "at", "of", "in"}]
    return " ".join(words)


# ---------------- dates ----------------
_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
            ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
            ("oct", "october"), ("nov", "november"), ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_ISO_RE = re.compile(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b")
_US_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b")
_MDY_RE = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b")
_DMY_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(20\d\d)\b")


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str) -> list[date]:
    """All full dates (with a year) found in free text, in order of appearance."""
    text = clean(text)
    found: list[tuple[int, date]] = []
    for m in _ISO_RE.finditer(text):
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            found.append((m.start(), d))
    for m in _US_RE.finditer(text):
        d = _safe_date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if d:
            found.append((m.start(), d))
    for m in _MDY_RE.finditer(text):
        month = _MONTHS.get(m.group(1).lower())
        if month:
            d = _safe_date(int(m.group(3)), month, int(m.group(2)))
            if d:
                found.append((m.start(), d))
    for m in _DMY_RE.finditer(text):
        month = _MONTHS.get(m.group(2).lower())
        if month:
            d = _safe_date(int(m.group(3)), month, int(m.group(1)))
            if d:
                found.append((m.start(), d))
    found.sort(key=lambda pair: pair[0])
    out: list[date] = []
    for _, d in found:
        if d not in out:
            out.append(d)
    return out


_MONTH_DAY_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!,?\s*(?:20\d\d|'\d\d))",
    re.IGNORECASE,
)


def find_month_days(text: str) -> list[tuple[int, int]]:
    """(month, day) pairs written WITHOUT a year, e.g. 'December 1' or 'Feb 15th' (standing deadlines)."""
    out = []
    for m in _MONTH_DAY_RE.finditer(clean(text)):
        month = _MONTHS.get(m.group(1).lower())
        day = int(m.group(2))
        if month and 1 <= day <= 31 and (month, day) not in out:
            out.append((month, day))
    return out


def parse_date(text: str) -> date | None:
    dates = find_dates(text)
    return dates[0] if dates else None


_NUMERIC_DMY_RE = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?:[ T].*)?$")
_NUMERIC_YMD_RE = re.compile(r"^(20\d\d)[/.](\d{1,2})[/.](\d{1,2})(?:[ T].*)?$")
_EXCEL_DMONY_RE = re.compile(r"^(\d{1,2})[-\s]([A-Za-z]{3,9})[-\s](\d{4}|\d{2})(?:[ T].*)?$")  # 21-Oct-2026 / 21-Oct-26


def _year(text: str) -> int:
    return int(text) + 2000 if len(text) == 2 else int(text)


def _day_month_order(first: int, second: int, day_first: bool | None) -> tuple[int, int] | None:
    """(month, day) for a numeric date like 21/10 or 10/21, or None when it cannot be known."""
    if first > 12 and second <= 12:
        return second, first
    if second > 12 and first <= 12:
        return first, second
    if first == second:
        return first, second
    if day_first is True:
        return second, first
    if day_first is False:
        return first, second
    return None  # e.g. 05/06/2026: May 6 or 5 June? Never guess.


def parse_iso(text: str, day_first: bool | None = None) -> date | None:
    """Read a date written by this tool (YYYY-MM-DD), and also the forms Excel writes when it re-saves a CSV
    (21/10/2026, 10/21/26, 21-Oct-2026). An ambiguous date such as 05/06/2026 is only read when day_first is known."""
    value = clean(text)
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        pass
    m = _NUMERIC_YMD_RE.match(value)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _NUMERIC_DMY_RE.match(value)
    if m:
        order = _day_month_order(int(m.group(1)), int(m.group(2)), day_first)
        return _safe_date(_year(m.group(3)), order[0], order[1]) if order else None
    m = _EXCEL_DMONY_RE.match(value)
    if m and _MONTHS.get(m.group(2).lower()):
        return _safe_date(_year(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    dates = find_dates(value)
    return dates[0] if len(dates) == 1 else None


TRACKER_DATE_FIELDS = ("date_checked", "last_contact_date", "follow_up_date", "approved_on")


def detect_day_first(values: list[str]) -> bool | None:
    """Look at numeric dates such as 21/10/2026 to learn whether a file writes the day or the month first."""
    day_first = month_first = 0
    for value in values:
        m = _NUMERIC_DMY_RE.match(clean(value))
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            day_first += 1
        elif b > 12 >= a:
            month_first += 1
    if day_first and not month_first:
        return True
    if month_first and not day_first:
        return False
    return None


def normalize_tracker_dates(records: list[dict]) -> list[tuple[str, str, str]]:
    """Rewrite the tracker's date columns as YYYY-MM-DD (undoing an Excel re-save).
    Returns (record_id, field, value) for dates that could not be read safely; those are left unchanged."""
    values = [clean(r.get(f)) for r in records for f in TRACKER_DATE_FIELDS if clean(r.get(f))]
    day_first = detect_day_first(values)
    unreadable = []
    for record in records:
        for field_name in TRACKER_DATE_FIELDS:
            value = clean(record.get(field_name))
            if not value or re.fullmatch(r"20\d\d-\d\d-\d\d", value):
                continue
            parsed = parse_iso(value, day_first)
            if parsed:
                record[field_name] = parsed.isoformat()
            else:
                unreadable.append((clean(record.get("record_id")), field_name, value))
    return unreadable


def short_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(clean(part).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]
