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


def parse_date(text: str) -> date | None:
    dates = find_dates(text)
    return dates[0] if dates else None


def parse_iso(text: str) -> date | None:
    try:
        return datetime.strptime(clean(text)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def short_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(clean(part).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]
