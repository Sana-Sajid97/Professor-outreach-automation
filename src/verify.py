"""Verify records against their OFFICIAL university pages (runs on your own PC).

For each record we open the official faculty profile page (politely, see
http_client.py) and check:
  - the professor's name appears on the page;
  - an institutional email for this person is published there.

Emails are only accepted when they are actually written on the official page
(including common anti-spam forms such as "name [at] uni [dot] edu" or
Cloudflare-protected addresses). Nothing is ever guessed from a pattern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import unquote

from . import models as m
from .textutil import (
    EMAIL_FIND_RE,
    clean,
    email_domain,
    email_local,
    is_generic_email,
    is_valid_email,
    join_multi,
    name_tokens,
    normalize_email,
    normalize_url,
    registrable_domain,
    split_multi,
    strip_accents,
    url_host,
)

OBFUSCATED_RE = re.compile(
    # "name [at] uni [dot] edu", "name(at)uni.edu", "name {at} uni.edu", and upper-case "NAME AT UNI DOT EDU".
    # A bare lower-case " at " is NOT accepted: ordinary sentences ("Smith at nutrition.uni.edu") would become fake emails.
    r"([A-Za-z0-9._%+-]+)\s*(?:\[\s*at\s*\]|\(\s*at\s*\)|\{\s*at\s*\}|<\s*at\s*>|\s+AT\s+)\s*"
    r"([A-Za-z0-9-]+(?:\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|\s+DOT\s+|\.)\s*[A-Za-z0-9-]+)+)",
)
DOT_RE = re.compile(r"\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|\s+DOT\s+|\.)\s*", re.IGNORECASE)
TITLE_RE = re.compile(
    r"\b((?:Distinguished |Regents'? |University |Endowed |Clinical |Research |Adjunct |Emerit(?:us|a) )?"
    r"(?:Assistant |Associate |Full )?Professor(?: Emerit(?:us|a))?)\b"
)


@dataclass
class PageCheck:
    url: str
    fetched: bool
    error: str = ""
    name_found: bool = False
    emails: list[tuple[str, str]] = field(default_factory=list)  # (email, how it was found)
    titles: list[str] = field(default_factory=list)
    emeritus: bool = False
    final_url: str = ""


@dataclass
class VerifyOutcome:
    record_id: str
    status: str  # verified | partially_verified | not_verified
    email: str = ""
    email_source_url: str = ""
    messages: list[str] = field(default_factory=list)


def decode_cloudflare(hex_string: str) -> str:
    try:
        data = bytes.fromhex(hex_string)
    except ValueError:
        return ""
    if len(data) < 2:
        return ""
    key = data[0]
    try:
        return bytes(b ^ key for b in data[1:]).decode("utf-8")
    except UnicodeDecodeError:
        return ""


def extract_emails(html: str) -> list[tuple[str, str]]:
    """All email addresses published on a page, with how each was found."""
    from bs4 import BeautifulSoup

    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(email: str, how: str) -> None:
        e = normalize_email(email)
        if is_valid_email(e) and e not in seen:
            seen.add(e)
            found.append((e, how))

    soup = BeautifulSoup(html or "", "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            for part in unquote(href[7:]).split("?")[0].split(","):
                add(part.strip(), "mailto link")
        elif "/cdn-cgi/l/email-protection#" in href:
            add(decode_cloudflare(href.split("#", 1)[1]), "Cloudflare-protected email")
    for tag in soup.find_all(attrs={"data-cfemail": True}):
        add(decode_cloudflare(tag["data-cfemail"]), "Cloudflare-protected email")
    for script in soup(["script", "style", "noscript"]):
        script.decompose()
    text = soup.get_text(" ")
    for match in EMAIL_FIND_RE.findall(text):
        add(match, "written on the page")
    for user, domain in OBFUSCATED_RE.findall(text):
        domain_clean = DOT_RE.sub(".", domain).strip(".").lower()
        if domain_clean.endswith((".edu", ".org", ".gov")) and "." in domain_clean:
            add(f"{user}@{domain_clean}", "written in anti-spam form (at/dot)")
    # JSON-LD and other raw markup (e.g. "email": "x@uni.edu")
    for match in re.findall(r'"email"\s*:\s*"(?:mailto:)?([^"]+@[^"]+)"', html or "", flags=re.IGNORECASE):
        add(match, "structured data on the page")
    return found


def page_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" "))


def name_on_page(text: str, professor_name: str) -> bool:
    tokens = [t for t in name_tokens(professor_name) if len(t) > 1]
    if not tokens:
        return False
    plain = strip_accents(text).lower()
    last = tokens[-1]
    first = tokens[0]
    return last in plain and (first in plain or len(tokens) == 1)


STRONG, SURNAME_ONLY, NO_MATCH = 3, 1, 0


def _surname_variants(tokens: list[str]) -> set[str]:
    last = tokens[-1]
    variants = {last.replace("-", "")}
    variants.update(part for part in last.split("-") if len(part) >= 3)
    if len(tokens) >= 3:  # "Paula Chandler Laney" may be written chandlerlaney
        variants.add(tokens[-2] + last.replace("-", ""))
    return {v for v in variants if v}


def email_matches_person(email: str, professor_name: str) -> int:
    """How well an email's local part fits this person's name.

    STRONG       first name + surname (jane.smith, smith_jane, janesmith) or initial(s) + surname
                 (jsmith, jqsmith, smithj, j.smith)
    SURNAME_ONLY just the surname (smith, smith2): accepted only on the professor's own profile page
    NO_MATCH     anything else, including addresses that CONTRADICT the name (john.smith for Jane Smith,
                 jkim for Hyun Kim, mgarcia for Lucia Garcia)
    """
    tokens = [re.sub(r"[^a-z-]", "", strip_accents(t).lower()) for t in name_tokens(professor_name)]
    tokens = [t for t in tokens if t.strip("-")]
    local = strip_accents(email_local(email)).lower()
    if len(tokens) < 2 or not local:
        return NO_MATCH
    first = tokens[0].replace("-", "")
    initials = {first[0]} | {t[0] for t in tokens[1:-1]}
    parts = [p for p in re.split(r"[._+\-]+|\d+", local) if p]
    joined = "".join(parts)
    if joined == tokens[-1].replace("-", ""):
        return SURNAME_ONLY  # the whole surname alone, e.g. perez-escamilla@ for Rafael Perez-Escamilla
    # Every surname variant is checked and the best answer wins, so the result never depends on checking order.
    results = [_match_for_surname(sn, first, initials, parts, joined) for sn in sorted(_surname_variants(tokens))]
    return max((r for r in results if r is not None), default=NO_MATCH)


def _match_for_surname(sn: str, first: str, initials: set[str], parts: list[str], joined: str) -> int | None:
    # first name and surname as separate parts, in either order
    if first in parts and sn in parts:
        return STRONG
    # first name and surname written together
    if joined in {first + sn, sn + first}:
        return STRONG
    # initial(s) + surname, or surname + initial(s): jsmith, jqsmith, smithj, j.smith
    m = re.fullmatch(rf"([a-z]{{1,2}}){re.escape(sn)}", joined) or re.fullmatch(rf"{re.escape(sn)}([a-z]{{1,2}})", joined)
    if m:
        return STRONG if m.group(1)[0] == first[0] and set(m.group(1)) <= initials | {first[0]} else NO_MATCH
    if sn in parts:
        others = [p for p in parts if p != sn]
        if not others:
            return SURNAME_ONLY
        # another full word that is not this person's first or middle name means a different person
        if all(len(o) == 1 and o in initials for o in others):
            return STRONG
        return NO_MATCH
    return None


def choose_email(emails: list[tuple[str, str]], professor_name: str, page_url: str, own_profile: bool = True) -> tuple[str, str, str]:
    """Pick this professor's email among those on the page. Returns (email, how, reason) or ('', '', reason)."""
    site = registrable_domain(url_host(page_url))
    scored = []
    for email, how in emails:
        if is_generic_email(email):
            continue
        if site and registrable_domain(email_domain(email)) != site:
            continue
        scored.append((email_matches_person(email, professor_name), email, how))
    if not scored:
        return "", "", "no institutional email for this person was found on the page"
    strong = [c for c in scored if c[0] == STRONG]
    if len(strong) == 1:
        return strong[0][1], strong[0][2], f"found on the official page ({strong[0][2]})"
    if len(strong) > 1:
        return "", "", "several emails on the page could belong to this person - check by hand"
    surname_only = [c for c in scored if c[0] == SURNAME_ONLY]
    if own_profile and len(surname_only) == 1:
        c = surname_only[0]
        return c[1], c[2], f"found on the professor's own profile page ({c[2]}); it shows only the surname, so double-check"
    return "", "", "emails on the page do not clearly belong to this person"


def check_page(client, url: str, professor_name: str) -> PageCheck:
    result = client.get(url)
    if not result.ok:
        return PageCheck(url, False, error=result.error)
    text = page_text(result.text)
    check = PageCheck(url, True)
    check.final_url = clean(getattr(result, "final_url", "")) or url
    check.name_found = name_on_page(text, professor_name)
    check.emails = extract_emails(result.text)
    check.titles = sorted(set(TITLE_RE.findall(text)))[:5]
    check.emeritus = bool(re.search(r"\bemerit(?:us|a)\b", text, re.IGNORECASE)) and not re.search(
        r"professor(?!\s+emerit)", text, re.IGNORECASE
    )
    return check


def verify_record(record: dict, client, today: date) -> VerifyOutcome:
    """Check one record against its official pages and update it in place."""
    rid = clean(record.get("record_id"))
    name = clean(record.get("professor_name"))
    outcome = VerifyOutcome(rid, m.VER_NOT)
    urls = []
    for field_name in ("faculty_profile_url", "email_source_url", "lab_url"):
        url = clean(record.get(field_name))
        if url and url not in urls:
            urls.append(url)
    if not urls:
        outcome.messages.append("No official page URL to check. Add faculty_profile_url first.")
        record["next_action"] = "Find the professor's official university profile page and add its URL."
        return outcome

    profile_check = None
    found_email, found_url = "", ""
    for url in urls:
        if not url.lower().startswith(("http://", "https://")):
            continue
        check = check_page(client, url, name)
        if url == clean(record.get("faculty_profile_url")):
            profile_check = check
        if not check.fetched:
            outcome.messages.append(f"{url}: {check.error}")
            continue
        if not check.name_found:
            outcome.messages.append(f"{url}: the professor's name was not found on this page.")
            continue
        # "own profile" only when this is the profile URL and it did not redirect somewhere else (e.g. a directory)
        own_profile = url == clean(record.get("faculty_profile_url")) and normalize_url(check.final_url or url) == normalize_url(url)
        email, _how, reason = choose_email(check.emails, name, url, own_profile=own_profile)
        if email:
            found_email, found_url = email, url
            outcome.messages.append(f"Email {reason}: {email}")
            break
        outcome.messages.append(f"{url}: {reason}.")

    existing = normalize_email(record.get("institutional_email", ""))
    record["date_checked"] = today.isoformat()
    if profile_check and profile_check.fetched and profile_check.emeritus:
        outcome.messages.append("The profile mentions 'Emeritus': this person may be retired. Check before contacting.")
    if found_email:
        if existing and existing != found_email:
            outcome.status = m.VER_PARTIAL
            outcome.messages.append(
                f"CONFLICT: the tracker has {existing} but the official page shows {found_email}. Not changed; please check."
            )
            record["verification_status"] = m.VER_PARTIAL
            record["next_action"] = f"Email conflict: tracker {existing} vs official page {found_email}. Fix it by hand."
        else:
            record["institutional_email"] = found_email
            record["email_source_url"] = found_url
            record["email_verification"] = m.EMAIL_FOUND_ON_PAGE
            record["verification_status"] = m.VER_VERIFIED
            record["source_urls"] = join_multi(split_multi(record.get("source_urls", "")) + [found_url])
            outcome.status = m.VER_VERIFIED
            outcome.email, outcome.email_source_url = found_email, found_url
            if clean(record.get("workflow_status")) in {m.DISCOVERED, m.NEEDS_VERIFICATION}:
                record["workflow_status"] = m.VERIFIED
            record["next_action"] = "Verified. Run the pipeline to score and draft."
    else:
        name_seen = bool(profile_check and profile_check.fetched and profile_check.name_found)
        outcome.status = m.VER_PARTIAL if name_seen else m.VER_NOT
        record["verification_status"] = outcome.status
        if record.get("email_verification") != m.EMAIL_CONFIRMED_MANUALLY:
            record["email_verification"] = m.EMAIL_NOT_FOUND if name_seen else clean(record.get("email_verification"))
        if clean(record.get("workflow_status")) in {m.DISCOVERED, m.VERIFIED}:
            record["workflow_status"] = m.NEEDS_VERIFICATION
        record["next_action"] = (
            "Profile confirmed but no email found automatically (it may be hidden). Open the profile, find the email, "
            "then run: python -m src.cli confirm-email --id " + rid + ' --email "..." --source-url "..."'
            if name_seen
            else "Could not confirm the official profile automatically. Open the link and check by hand."
        )
    note = f"{today.isoformat()} verify: " + " ".join(outcome.messages)
    record["notes"] = f"{clean(record.get('notes'))} | {note}".strip(" |")[-2000:]
    return outcome


def confirm_email_manually(record: dict, email: str, source_url: str, today: date) -> None:
    """The user saw the email on the official page with their own eyes."""
    from .errors import UserFacingError
    from .textutil import is_official_academic_host, is_valid_url

    email = normalize_email(email)
    if not is_valid_email(email):
        raise UserFacingError(f"'{email}' is not a valid email address.")
    if not is_valid_url(source_url):
        raise UserFacingError("Please give the official page URL where you saw this email (--source-url).")
    if not is_official_academic_host(url_host(source_url)):
        raise UserFacingError("The source page should be on the university's official (.edu) website.")
    record["institutional_email"] = email
    record["email_source_url"] = source_url
    record["email_verification"] = m.EMAIL_CONFIRMED_MANUALLY
    record["verification_status"] = m.VER_VERIFIED
    record["date_checked"] = today.isoformat()
    record["source_urls"] = join_multi(split_multi(record.get("source_urls", "")) + [source_url])
    if clean(record.get("workflow_status")) in {m.DISCOVERED, m.NEEDS_VERIFICATION}:
        record["workflow_status"] = m.VERIFIED
    record["next_action"] = "Verified manually. Run the pipeline to score and draft."
    record["notes"] = f"{clean(record.get('notes'))} | {today.isoformat()}: email confirmed manually from {source_url}".strip(" |")
