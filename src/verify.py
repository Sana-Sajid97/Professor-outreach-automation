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
    registrable_domain,
    split_multi,
    strip_accents,
    url_host,
)

OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9._%+-]+)\s*(?:\[\s*at\s*\]|\(\s*at\s*\)|\{\s*at\s*\}|<\s*at\s*>|\s+at\s+|\s*@\s*)\s*"
    r"([A-Za-z0-9-]+(?:\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|\s+dot\s+|\.)\s*[A-Za-z0-9-]+)+)",
    re.IGNORECASE,
)
DOT_RE = re.compile(r"\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|\s+dot\s+|\.)\s*", re.IGNORECASE)
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
            for part in href[7:].split("?")[0].split(","):
                add(part, "mailto link")
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


def email_matches_person(email: str, professor_name: str) -> int:
    """Higher = the email's local part looks more like this person's name (0 = no sign)."""
    local = re.sub(r"[^a-z]", "", strip_accents(email_local(email)).lower())
    tokens = [re.sub(r"[^a-z]", "", t) for t in name_tokens(professor_name)]
    tokens = [t for t in tokens if t]
    if not tokens or not local:
        return 0
    first, last = tokens[0], tokens[-1]
    score = 0
    last_parts = [p for p in re.split(r"-", strip_accents(name_tokens(professor_name)[-1]).lower()) if p] if name_tokens(professor_name) else []
    if last in local or any(len(p) >= 3 and p in local for p in last_parts):
        score += 3
    if first in local:
        score += 2
    elif local.startswith(first[:1]) and (last in local or any(len(p) >= 3 and p in local for p in last_parts)):
        score += 1
    return score


def choose_email(emails: list[tuple[str, str]], professor_name: str, page_url: str) -> tuple[str, str, str]:
    """Pick this professor's email among those on the page. Returns (email, how, reason) or ('', '', reason)."""
    site = registrable_domain(url_host(page_url))
    candidates = []
    for email, how in emails:
        if is_generic_email(email):
            continue
        if site and registrable_domain(email_domain(email)) != site:
            continue
        candidates.append((email_matches_person(email, professor_name), email, how))
    if not candidates:
        return "", "", "no institutional email for this person was found on the page"
    candidates.sort(key=lambda c: -c[0])
    best_score, best, how = candidates[0]
    if best_score >= 3 or (best_score >= 2 and len(candidates) == 1):
        return best, how, f"found on the official page ({how})"
    if len(candidates) == 1 and best_score >= 1:
        return best, how, f"found on the official page ({how}); it does not fully match the name, so double-check"
    return "", "", "emails on the page do not clearly belong to this person"


def check_page(client, url: str, professor_name: str) -> PageCheck:
    result = client.get(url)
    if not result.ok:
        return PageCheck(url, False, error=result.error)
    text = page_text(result.text)
    check = PageCheck(url, True)
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
    found_email, found_how, found_url = "", "", ""
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
        email, how, reason = choose_email(check.emails, name, url)
        if email:
            found_email, found_how, found_url = email, how, url
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
