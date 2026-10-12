"""Check a paper before the email mentions it: does the link point to this paper, and is the
professor really an author?

Uses two free, official scholarly APIs (no key needed):
  - Crossref  https://api.crossref.org/works/{doi}          for DOI links (doi.org/10.xxxx/...)
  - PubMed    https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi  for PubMed links
Both ask for gentle use; the polite client spaces requests out. Other links (journal pages)
are not checked automatically: open them yourself.
NOTE: like the page checks, this could not be run against the live APIs from the cloud build
environment. It was tested with sample answers shaped like the APIs' documented responses.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from .textutil import clean, last_name, strip_accents

CROSSREF = "https://api.crossref.org/works/"
PUBMED_SUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>?#]+)", re.IGNORECASE)
PMID_RE = re.compile(r"(?:pubmed\.ncbi\.nlm\.nih\.gov/|ncbi\.nlm\.nih\.gov/pubmed/)(\d{4,9})", re.IGNORECASE)


def _norm_words(text: str) -> list[str]:
    text = re.sub(r"<[^>]+>", " ", text or "")  # Crossref titles can contain <i> tags
    return re.findall(r"[a-z0-9]+", strip_accents(text).lower())


def title_similarity(a: str, b: str) -> float:
    wa, wb = set(_norm_words(a)), set(_norm_words(b))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _compact(text: str) -> str:
    return re.sub(r"[^a-z]", "", strip_accents(text or "").lower())


def _author_listed(professor_name: str, family_names: list[str]) -> bool:
    surname = _compact(last_name(professor_name))
    parts = {p for p in re.split(r"[\s-]+", strip_accents(last_name(professor_name)).lower()) if len(p) >= 3}
    for family in family_names:
        fam = _compact(family)
        if fam and (fam == surname or fam in {_compact(p) for p in parts}):
            return True
    return False


def _result(status: str, detail: str, url: str, found_title: str = "", year: str = "") -> dict:
    out = {"status": status, "detail": detail, "url": url}
    if found_title:
        out["found_title"] = found_title
    if year:
        out["year"] = year
    return out


def _judge(recorded_title: str, found_title: str, authors_ok: bool, url: str, year: str, source: str) -> dict:
    sim = title_similarity(recorded_title, found_title)
    if sim < 0.5:
        return _result("failed", f"{source}: this link is a different paper (“{found_title[:120]}”).", url, found_title, year)
    if not authors_ok:
        return _result("failed", f"{source}: the professor is not listed as an author of this paper.", url, found_title, year)
    if sim < 0.75:
        return _result("warning", f"{source}: the title is similar but not the same (“{found_title[:120]}”). Check it.", url, found_title, year)
    return _result("passed", f"{source}: the paper exists, the title matches and the professor is an author" + (f" ({year})." if year else "."), url, found_title, year)


def check_publication(client, title: str, url: str, professor_name: str) -> dict:
    """Result dict with status passed / warning / failed / not_checked, detail and url."""
    title, url = clean(title), clean(url)
    get_json = getattr(client, "get_json", None)
    doi = DOI_RE.search(url) or DOI_RE.search(title)
    pmid = PMID_RE.search(url)
    if not (doi or pmid):
        return _result("not_checked", "No DOI or PubMed link to check automatically. Open the link and check it yourself.", url)
    if get_json is None:
        return _result("not_checked", "Paper not checked (no internet client).", url)
    if doi:
        doi_text = doi.group(1).rstrip(".,;)")
        status, data, error = get_json(CROSSREF + quote(doi_text, safe="/"))
        if status == 404:
            return _result("failed", f"Crossref: the DOI {doi_text} does not exist.", url)
        if status != 200 or not data:
            return _result("not_checked", f"Crossref could not be reached ({error or status}). Try again later.", url)
        msg = data.get("message") or {}
        found = clean((msg.get("title") or [""])[0])
        families = [clean(a.get("family")) for a in msg.get("author") or [] if a.get("family")]
        parts = ((msg.get("issued") or {}).get("date-parts") or [[None]])[0]
        year = str(parts[0]) if parts and parts[0] else ""
        return _judge(title, found, _author_listed(professor_name, families), url, year, "Crossref")
    pid = pmid.group(1)
    status, data, error = get_json(PUBMED_SUMMARY, params={"db": "pubmed", "id": pid, "retmode": "json"})
    if status != 200 or not data:
        return _result("not_checked", f"PubMed could not be reached ({error or status}). Try again later.", url)
    item = (data.get("result") or {}).get(pid) or {}
    if not item or item.get("error"):
        return _result("failed", f"PubMed: no paper with id {pid}.", url)
    found = clean(item.get("title")).rstrip(".")
    # PubMed author names look like "Smith J" or "Perez-Escamilla R": the surname is everything but the initials.
    families = [re.sub(r"\s+[A-Z]{1,3}$", "", clean(a.get("name"))) for a in item.get("authors") or []]
    year = clean(item.get("pubdate"))[:4]
    return _judge(title, found, _author_listed(professor_name, families), url, year, "PubMed")
