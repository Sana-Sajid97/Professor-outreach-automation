"""Verify records against their OFFICIAL university pages (runs on your own PC).

For each professor, every check is recorded separately (see checks.py), with the official link,
the date and a quote:
  profile      the official profile page opens and names the professor
  email        an institutional email for this person is published on an official page
  research     the research the email would describe appears on the official profile/lab page
  publication  a mentioned paper exists (Crossref/PubMed), has the recorded title and lists the professor
  program      the official program page: degree, Spring/Fall entry, deadlines, IELTS, requirements
  funding      assistantship/stipend statements on the official pages, graded confirmed/possible/not verified

A record is VERIFIED only when the profile, email and research checks pass. Emails are only accepted
when they are actually written on the official page (including anti-spam forms such as
"name [at] uni [dot] edu" or Cloudflare-protected addresses). Nothing is ever guessed from a pattern.
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
    html: str = field(default="", repr=False)
    status_code: int = 0


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
        return PageCheck(url, False, error=result.error, status_code=getattr(result, "status", 0) or 0)
    text = page_text(result.text)
    check = PageCheck(url, True, html=result.text or "")
    check.final_url = clean(getattr(result, "final_url", "")) or url
    check.name_found = name_on_page(text, professor_name)
    check.emails = extract_emails(result.text)
    check.titles = sorted(set(TITLE_RE.findall(text)))[:5]
    check.emeritus = bool(re.search(r"\bemerit(?:us|a)\b", text, re.IGNORECASE)) and not re.search(
        r"professor(?!\s+emerit)", text, re.IGNORECASE
    )
    return check


def _keep_confirmed(record: dict, name: str, status: str, today: date, url: str = "", detail: str = "", **extra) -> None:
    """Record an automatic result, but never overwrite something you confirmed yourself
    (unless the automatic check now passes too). The automatic result is kept alongside for transparency."""
    from . import checks as ck

    current = ck.get_check(ck.load_checks(record), name)
    if current.get("status") == ck.CONFIRMED and status != ck.PASSED:
        current = dict(current, auto_result=f"{status}: {detail}"[:300])
        all_checks = ck.load_checks(record)
        all_checks[name] = current
        ck.save_checks(record, all_checks)
        return
    ck.set_check(record, name, status, today, url=url, detail=detail, **extra)


def _fetch_failure(check: PageCheck) -> tuple[str, str]:
    """(status, detail) for a page that could not be opened."""
    from . import checks as ck

    if check.status_code in (404, 410):
        return ck.FAILED, f"The page was not found ({check.status_code}). The person or program may have moved."
    return ck.NOT_CHECKED, f"Could not open the page automatically ({check.error}). Check it by hand, then confirm it."


def next_steps(record: dict, all_checks: dict) -> str:
    """What to do next, in plain words, for the required checks that have not passed."""
    from . import checks as ck

    rid = clean(record.get("record_id"))
    steps = []
    if ck.status_of(all_checks, "profile") not in ck.OK_STATUSES:
        steps.append("open the official profile and, if it is the right person, confirm it: "
                     f"python -m src.cli confirm --id {rid} --check profile --source-url \"<profile link>\"")
    if ck.status_of(all_checks, "email") not in ck.OK_STATUSES:
        steps.append("find the email on the official page, then: "
                     f"python -m src.cli confirm-email --id {rid} --email \"...\" --source-url \"<page link>\"")
    if ck.status_of(all_checks, "research") not in ck.OK_STATUSES:
        steps.append("compare research_interests with the official profile; correct them (outreach set ... --field research_interests) "
                     f"and verify again, or confirm: python -m src.cli confirm --id {rid} --check research --source-url \"<profile link>\"")
    return "Still needed before a draft: " + " | ".join(steps) + " (the editor page has buttons for these too)."


def verify_record(record: dict, client, today: date, evidence_dir=None, applicant_ielts: float | None = None) -> VerifyOutcome:
    """Run every check for one record against its official pages and update it in place."""
    from . import checks as ck
    from .evidence import save_snapshot
    from .page_facts import funding_evidence, funding_level, page_blocks, program_facts, research_excerpt, research_items, research_support
    from .publications import check_publication
    from .scoring import _intake_available
    from .textutil import meaningful

    rid = clean(record.get("record_id"))
    name = clean(record.get("professor_name"))
    outcome = VerifyOutcome(rid, m.VER_NOT)
    profile_url = clean(record.get("faculty_profile_url"))
    urls = []
    for field_name in ("faculty_profile_url", "email_source_url", "lab_url"):
        url = clean(record.get(field_name))
        if url and url not in urls and url.lower().startswith(("http://", "https://")):
            urls.append(url)
    record["date_checked"] = today.isoformat()
    if not urls:
        outcome.messages.append("No official page URL to check. Add faculty_profile_url first.")
        ck.set_check(record, "profile", ck.NOT_CHECKED, today, detail="No official profile link recorded yet.")
        record["next_action"] = "Find the professor's official university profile page and add its URL (outreach set ... --field faculty_profile_url)."
        outcome.status = ck.apply_derived_status(record)
        return outcome

    # ---- 1. open the official pages (profile, the page where the email was found, lab)
    pages: dict[str, PageCheck] = {}
    profile_check = None
    found_email, found_url = "", ""
    for url in urls:
        check = check_page(client, url, name)
        pages[url] = check
        if url == profile_url:
            profile_check = check
        if not check.fetched:
            outcome.messages.append(f"{url}: {check.error}")
            continue
        save_snapshot(evidence_dir, url, "\n".join(page_blocks(check.html)), today)
        if not check.name_found:
            outcome.messages.append(f"{url}: the professor's name was not found on this page.")
            continue
        if found_email:
            continue
        # "own profile" only when this is the profile URL and it did not redirect somewhere else (e.g. a directory)
        own_profile = url == profile_url and normalize_url(check.final_url or url) == normalize_url(url)
        email, _how, reason = choose_email(check.emails, name, url, own_profile=own_profile)
        if email:
            found_email, found_url = email, url
            outcome.messages.append(f"Email {reason}: {email}")
        else:
            outcome.messages.append(f"{url}: {reason}.")
    good_pages = [c for c in pages.values() if c.fetched and c.name_found]

    # ---- 2. profile
    if not profile_url:
        _keep_confirmed(record, "profile", ck.NOT_CHECKED, today, detail="No official profile link recorded (only other pages were checked).")
    elif profile_check is None or not profile_check.fetched:
        status, detail = _fetch_failure(profile_check) if profile_check else (ck.NOT_CHECKED, "Not opened.")
        _keep_confirmed(record, "profile", status, today, url=profile_url, detail=detail)
    elif not profile_check.name_found:
        _keep_confirmed(record, "profile", ck.FAILED, today, url=profile_url,
                        detail=f"The page does not mention {name}. It may be the wrong page, or the person has left.")
    elif profile_check.emeritus:
        _keep_confirmed(record, "profile", ck.WARNING, today, url=profile_url,
                        detail="The page names the professor but says 'Emeritus': they may be retired and not taking students.")
        outcome.messages.append("The profile mentions 'Emeritus': this person may be retired. Check before contacting.")
    else:
        title = f" ({profile_check.titles[0]})" if profile_check.titles else ""
        _keep_confirmed(record, "profile", ck.PASSED, today, url=profile_url, detail=f"The official page names {name}{title}.")

    # ---- 3. email
    existing = normalize_email(record.get("institutional_email", ""))
    if found_email:
        if existing and existing != found_email:
            outcome.messages.append(f"CONFLICT: the tracker has {existing} but the official page shows {found_email}. Not changed; please check.")
            ck.set_check(record, "email", ck.FAILED, today, url=found_url,
                         detail=f"Conflict: the tracker has {existing}, but the official page shows {found_email}.")
            record["next_action"] = f"Email conflict: tracker {existing} vs official page {found_email}. Fix it by hand."
        else:
            record["institutional_email"] = found_email
            record["email_source_url"] = found_url
            record["email_verification"] = m.EMAIL_FOUND_ON_PAGE
            record["source_urls"] = join_multi(split_multi(record.get("source_urls", "")) + [found_url])
            ck.set_check(record, "email", ck.PASSED, today, url=found_url, detail=f"{found_email} is published on the official page.")
            outcome.email, outcome.email_source_url = found_email, found_url
    elif record.get("email_verification") == m.EMAIL_CONFIRMED_MANUALLY and existing:
        pass  # you confirmed it yourself earlier; keep that
    elif good_pages:
        record["email_verification"] = m.EMAIL_NOT_FOUND
        ck.set_check(record, "email", ck.WARNING, today, url=good_pages[0].url,
                     detail="No email for this person was found on the official pages (it may be hidden). Find it yourself and confirm it.")
    else:
        ck.set_check(record, "email", ck.NOT_CHECKED, today, detail="The official pages could not be opened.")

    # ---- 4. research described in the email
    phrases = research_items(meaningful(record.get("research_interests", "")))
    research_blocks = [b for c in good_pages for b in page_blocks(c.html)]
    if not phrases:
        _keep_confirmed(record, "research", ck.NOT_CHECKED, today, url=profile_url,
                        detail="No research interests recorded. Copy them from the official profile (outreach set ... --field research_interests).")
    elif not research_blocks:
        _keep_confirmed(record, "research", ck.NOT_CHECKED, today, url=profile_url, detail="The official pages could not be opened, so the research was not checked.")
    else:
        results = research_support(phrases, research_blocks)
        supported = [r["phrase"] for r in results if r["level"] == "supported"]
        partly = [r["phrase"] for r in results if r["level"] == "partly"]
        unsupported = [r["phrase"] for r in results if r["level"] == "unsupported"]
        quotes = {r["phrase"]: r["quote"] for r in results if r["quote"]}
        excerpt = research_excerpt(profile_check.html) if profile_check and profile_check.fetched else ""
        left_out = partly + unsupported
        if supported:
            status = ck.PASSED
            detail = f"{len(supported)} of {len(results)} recorded research phrase(s) appear on the official page."
            if left_out:
                detail += " Not found there, so left out of the email: " + "; ".join(f"'{p}'" for p in left_out[:4]) + "."
        elif partly:
            status = ck.WARNING
            detail = "The recorded research only partly matches the official page: " + "; ".join(f"'{p}'" for p in partly[:4]) + ". Check the page and correct research_interests."
        else:
            status = ck.FAILED
            detail = "None of the recorded research phrases appear on the official page. The recorded interests may be wrong or out of date."
        _keep_confirmed(record, "research", status, today, url=profile_url or good_pages[0].url, detail=detail,
                        supported=supported, partly=partly, unsupported=unsupported, quotes=quotes, excerpt=excerpt)

    # ---- 5. papers the email could mention
    items = []
    for n in (1, 2):
        title = clean(record.get(f"relevant_publication_{n}"))
        if title:
            result = check_publication(client, title, record.get(f"publication_{n}_url", ""), name)
            items.append(dict(result, n=n, title=title))
    if items:
        statuses = [i["status"] for i in items]
        if ck.PASSED in statuses:
            pub_status = ck.PASSED
        elif statuses and all(st == ck.FAILED for st in statuses):
            pub_status = ck.FAILED
        elif ck.WARNING in statuses:
            pub_status = ck.WARNING
        else:
            pub_status = ck.NOT_CHECKED
        good = [i for i in items if i["status"] == ck.PASSED]
        pub_detail = ("Checked: " + "; ".join(f"paper {i['n']}: {i['detail']}" for i in items))[:600]
        if good and len(good) < len(items):
            pub_detail = "Only checked papers are mentioned in emails. " + pub_detail
        _keep_confirmed(record, "publication", pub_status, today, url=good[0]["url"] if good else items[0]["url"], detail=pub_detail, items=items)

    # ---- 6. program page: degree, intake, deadlines, IELTS, requirements
    program_url = clean(record.get("program_url"))
    program_blocks: list[str] = []
    if program_url:
        program_check = check_page(client, program_url, name)
        if program_check.fetched:
            program_blocks = page_blocks(program_check.html)
            save_snapshot(evidence_dir, program_url, "\n".join(program_blocks), today)
            from .drafting import clean_program_name

            facts = program_facts(
                program_blocks, applicant_ielts, clean_program_name(record.get("graduate_program", "")),
                spring_open=_intake_available(record.get("spring_2027_status", ""), today, "spring"),
                fall_open=_intake_available(record.get("fall_2027_status", ""), today, "fall"),
            )
            _keep_confirmed(record, "program", facts["status"], today, url=program_url, detail=facts["detail"], items=facts["items"])
        else:
            status, detail = _fetch_failure(program_check)
            _keep_confirmed(record, "program", status, today, url=program_url, detail=detail)
    else:
        _keep_confirmed(record, "program", ck.NOT_CHECKED, today, detail="No official program page recorded.")

    # ---- 7. funding: statements on the official pages (+ an active NIH grant if one was found)
    evidence = []
    for c in good_pages:
        evidence += funding_evidence(page_blocks(c.html), c.url)
    if program_blocks:
        evidence += funding_evidence(program_blocks, program_url)
    nih = re.search(r"NIH RePORTER: Active NIH project[^|]*", record.get("funding_or_assistantship_evidence", "") or "")
    if nih:
        project = re.search(r"https://reporter\.nih\.gov/project-details/\d+", nih.group(0))
        evidence.append({"url": project.group(0) if project else "https://reporter.nih.gov/", "kind": "active_grant", "quote": nih.group(0).strip()[:280]})
    if evidence or good_pages or program_blocks:
        from .page_facts import KIND_WORDS

        level = funding_level(evidence)
        best = evidence[0] if evidence else None
        detail = {
            ck.FUNDING_CONFIRMED: f"{KIND_WORDS[best['kind']]}." if best else "",
            ck.FUNDING_POSSIBLE: "Only general statements or grant evidence: ask the professor about an assistantship.",
            ck.FUNDING_NOT_AVAILABLE: "An official page says funding is not available for some students. Read the quote.",
            ck.FUNDING_NOT_VERIFIED: "No assistantship or stipend statement found on the official pages checked.",
        }[level]
        _keep_confirmed(record, "funding", level, today, url=best["url"] if best else "", detail=detail, evidence=evidence[:10])
    else:
        _keep_confirmed(record, "funding", ck.NOT_CHECKED, today, detail="The official pages could not be opened.")

    # ---- 8. overall: verified only when profile, email AND research have passed
    outcome.status = ck.apply_derived_status(record)
    all_checks = ck.load_checks(record)
    if outcome.status == m.VER_VERIFIED:
        if not record.get("next_action", "").startswith("Email conflict"):
            record["next_action"] = "Verified (profile, email and research checked). Run the pipeline to draft."
    elif not record.get("next_action", "").startswith("Email conflict"):
        record["next_action"] = next_steps(record, all_checks)
    outcome.messages.append(ck.summary_text(all_checks))
    note = f"{today.isoformat()} verify: " + " ".join(outcome.messages)
    record["notes"] = f"{clean(record.get('notes'))} | {note}".strip(" |")[-2000:]
    return outcome


def recheck_research_offline(record: dict, today: date, evidence_dir) -> str:
    """Compare research_interests with the SAVED copy of the official profile/lab page (no new website visit).
    Used right after you correct the research interests. Returns the new research check status."""
    from . import checks as ck
    from .evidence import load_snapshot
    from .page_facts import research_items, research_support
    from .textutil import meaningful

    blocks, url = [], ""
    for field_name in ("faculty_profile_url", "lab_url", "email_source_url"):
        snap = load_snapshot(evidence_dir, clean(record.get(field_name)))
        if snap:
            blocks += snap[0].splitlines()
            url = url or clean(record.get(field_name))
    phrases = research_items(meaningful(record.get("research_interests", "")))
    if not phrases or not blocks:
        detail = "No research interests recorded." if not phrases else "No saved copy of the official page yet: run verify for this professor."
        ck.set_check(record, "research", ck.NOT_CHECKED, today, detail=detail)
        ck.apply_derived_status(record)
        return ck.NOT_CHECKED
    results = research_support(phrases, blocks)
    supported = [r["phrase"] for r in results if r["level"] == "supported"]
    partly = [r["phrase"] for r in results if r["level"] == "partly"]
    unsupported = [r["phrase"] for r in results if r["level"] == "unsupported"]
    if supported:
        status, detail = ck.PASSED, f"{len(supported)} of {len(results)} research phrase(s) appear on the saved official page."
    elif partly:
        status, detail = ck.WARNING, "The research only partly matches the saved official page."
    else:
        status, detail = ck.FAILED, "None of these research phrases appear on the saved official page."
    ck.set_check(record, "research", status, today, url=url, detail=detail + " (checked against the copy saved by verify)",
                 supported=supported, partly=partly, unsupported=unsupported,
                 quotes={r["phrase"]: r["quote"] for r in results if r["quote"]})
    ck.apply_derived_status(record)
    return status


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
    from . import checks as ck

    record["institutional_email"] = email
    record["email_source_url"] = source_url
    record["email_verification"] = m.EMAIL_CONFIRMED_MANUALLY
    record["date_checked"] = today.isoformat()
    record["source_urls"] = join_multi(split_multi(record.get("source_urls", "")) + [source_url])
    ck.set_check(record, "email", ck.CONFIRMED, today, url=source_url, detail=f"{email}: checked by you on the official page on {today.isoformat()}.")
    if ck.apply_derived_status(record) == m.VER_VERIFIED:
        record["next_action"] = "Verified. Run the pipeline to score and draft."
    else:
        record["next_action"] = "Email confirmed. " + next_steps(record, ck.load_checks(record))
    record["notes"] = f"{clean(record.get('notes'))} | {today.isoformat()}: email confirmed manually from {source_url}".strip(" |")
