"""A polite web client: robots.txt, per-site rate limits, retries with back-off, and a cache.

It never tries to get around CAPTCHAs, logins, paywalls or blocks. If a site says
no (robots.txt, 401/403, repeated 429), the page is skipped and the record is left
for a human to check by hand.

Notes from Python's own robotparser (verified for this project):
- it reports Crawl-delay but never waits, so this client does the waiting itself;
- fractional delays such as "2.5" are ignored by robotparser, so we parse them ourselves;
- robots.txt is fetched with our own User-Agent and a timeout, then passed to parse().
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlsplit

DEFAULT_TIMEOUT = 20
MAX_RETRIES = 3
CACHE_TTL_SECONDS = 7 * 24 * 3600


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: int = 0
    text: str = ""
    error: str = ""
    from_cache: bool = False
    blocked_by_robots: bool = False
    final_url: str = ""


class PoliteClient:
    def __init__(
        self,
        user_agent: str,
        delay_seconds: float = 2.0,
        cache_dir: Path | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        session=None,
        sleep=time.sleep,
        clock=time.monotonic,
        cache_ttl: int = CACHE_TTL_SECONDS,
    ):
        self.user_agent = user_agent
        self.delay = max(1.0, float(delay_seconds))
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._sleep = sleep
        self._clock = clock
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, tuple[robotparser.RobotFileParser | None, float, bool]] = {}
        self._blocked_hosts: set[str] = set()
        if session is None:
            import requests

            session = requests.Session()
        self.session = session

    # ------------------------------------------------------------------ helpers
    def _headers(self) -> dict:
        return {"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.5"}

    def _wait_turn(self, host: str, extra_delay: float = 0.0) -> None:
        delay = max(self.delay, extra_delay)
        last = self._last_hit.get(host)
        now = self._clock()
        if last is not None and now - last < delay:
            self._sleep(delay - (now - last))
        self._last_hit[host] = self._clock()

    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, url: str) -> FetchResult | None:
        path = self._cache_path(url)
        if not path or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if time.time() - data.get("saved_at", 0) > self.cache_ttl:
            return None
        return FetchResult(url, True, data.get("status", 200), data.get("text", ""), from_cache=True, final_url=data.get("final_url", url))

    def _write_cache(self, result: FetchResult) -> None:
        path = self._cache_path(result.url)
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"saved_at": time.time(), "status": result.status, "text": result.text, "final_url": result.final_url}),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ------------------------------------------------------------------ robots.txt
    def _robots_for(self, url: str) -> tuple[robotparser.RobotFileParser | None, float, bool]:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base in self._robots:
            return self._robots[base]
        rp = robotparser.RobotFileParser()
        crawl_delay = 0.0
        disallow_all = False
        try:
            self._wait_turn(parts.netloc)
            resp = self.session.get(base + "/robots.txt", headers=self._headers(), timeout=self.timeout)
            status = getattr(resp, "status_code", 0)
            if status in (401, 403):
                disallow_all = True  # conservative: the site restricts automated access
            elif status == 429 or status >= 500:
                disallow_all = True  # RFC 9309: unreachable robots.txt -> assume disallow; try again later
            elif 200 <= status < 300:
                text = resp.text or ""
                rp.parse(text.splitlines())
                crawl_delay = _parse_crawl_delay(text, self.user_agent)
            else:
                rp = None  # 404 and other 4xx: no robots.txt, everything allowed
        except Exception:
            rp = None
        entry = (rp, crawl_delay, disallow_all)
        self._robots[base] = entry
        return entry

    def allowed(self, url: str) -> bool:
        rp, _, disallow_all = self._robots_for(url)
        if disallow_all:
            return False
        if rp is None:
            return True
        return rp.can_fetch(self.user_agent, url)

    # ------------------------------------------------------------------ main entry point
    def get(self, url: str, use_cache: bool = True) -> FetchResult:
        parts = urlsplit(url)
        host = parts.netloc.lower()
        if parts.scheme not in {"http", "https"} or not host:
            return FetchResult(url, False, error="Not a valid web address.")
        if use_cache:
            cached = self._read_cache(url)
            if cached:
                return cached
        if host in self._blocked_hosts:
            return FetchResult(url, False, error="This site asked us to slow down or blocked automated access; skipped for now.")
        if not self.allowed(url):
            return FetchResult(url, False, error="The site's robots.txt does not allow automated access to this page. Check it by hand.", blocked_by_robots=True)
        _, crawl_delay, _ = self._robots_for(url)
        last_error = ""
        for attempt in range(MAX_RETRIES):
            self._wait_turn(host, crawl_delay)
            try:
                resp = self.session.get(url, headers=self._headers(), timeout=self.timeout, allow_redirects=True)
            except Exception as exc:  # network errors, timeouts
                last_error = f"Network problem: {exc.__class__.__name__}"
                self._sleep(_backoff(attempt))
                continue
            status = getattr(resp, "status_code", 0)
            if status == 200:
                result = FetchResult(url, True, status, resp.text or "", final_url=str(getattr(resp, "url", url) or url))
                self._write_cache(result)
                return result
            if status in (429, 503):
                retry_after = _retry_after(getattr(resp, "headers", {}) or {})
                last_error = f"The site is busy or rate-limiting (HTTP {status})."
                if attempt == MAX_RETRIES - 1:
                    self._blocked_hosts.add(host)
                    break
                self._sleep(retry_after if retry_after is not None else _backoff(attempt))
                continue
            if status in (401, 403):
                return FetchResult(url, False, status, error="Access denied (login, CAPTCHA or block). Not bypassed - check by hand.")
            if status == 404:
                return FetchResult(url, False, status, error="Page not found (404). The person may have moved or the URL changed.")
            if 500 <= status < 600:
                last_error = f"Server error (HTTP {status})."
                self._sleep(_backoff(attempt))
                continue
            return FetchResult(url, False, status, error=f"Unexpected response (HTTP {status}).")
        return FetchResult(url, False, error=last_error or "Could not fetch the page.")

    def get_json(self, url: str, params: dict | None = None, method: str = "GET", json_body: dict | None = None) -> tuple[int, dict | None, str]:
        """For official APIs (OpenAlex, NIH RePORTER). Polite delay + retries; no robots check needed for APIs."""
        host = urlsplit(url).netloc.lower()
        last_error = ""
        for attempt in range(MAX_RETRIES):
            self._wait_turn(host)
            try:
                if method == "POST":
                    resp = self.session.post(url, json=json_body, params=params, headers=self._headers(), timeout=self.timeout)
                else:
                    resp = self.session.get(url, params=params, headers=self._headers(), timeout=self.timeout)
            except Exception as exc:
                last_error = f"Network problem: {exc.__class__.__name__}"
                self._sleep(_backoff(attempt))
                continue
            status = getattr(resp, "status_code", 0)
            if status == 200:
                try:
                    return status, resp.json(), ""
                except ValueError:
                    return status, None, "The API returned something that is not JSON."
            if status in (403, 429, 503) and attempt < MAX_RETRIES - 1:
                retry_after = _retry_after(getattr(resp, "headers", {}) or {})
                self._sleep(retry_after if retry_after is not None else _backoff(attempt))
                last_error = f"Rate limited (HTTP {status})."
                continue
            if 500 <= status < 600 and attempt < MAX_RETRIES - 1:
                self._sleep(_backoff(attempt))
                last_error = f"Server error (HTTP {status})."
                continue
            body = ""
            try:
                body = (resp.text or "")[:300]
            except Exception:
                pass
            return status, None, f"HTTP {status}: {body}"
        return 0, None, last_error or "Request failed."


def _backoff(attempt: int) -> float:
    return min(60.0, (2 ** (attempt + 1)) + random.uniform(0, 1))


def _retry_after(headers) -> float | None:
    value = None
    try:
        value = headers.get("Retry-After") or headers.get("retry-after")
    except AttributeError:
        return None
    if value is None:
        return None
    try:
        return min(300.0, max(0.0, float(value)))
    except ValueError:
        return None


def _parse_crawl_delay(robots_text: str, user_agent: str) -> float:
    """Crawl-delay for our agent (or '*'), including fractional values."""
    agent_token = user_agent.split("/")[0].lower()
    current: list[str] = []
    delays: dict[str, float] = {}
    for raw in robots_text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            current = [value.lower()]
        elif key == "crawl-delay" and current:
            try:
                for agent in current:
                    delays[agent] = float(value)
            except ValueError:
                continue
    for agent, delay in delays.items():
        if agent != "*" and agent and agent in agent_token:
            return min(delay, 120.0)
    return min(delays.get("*", 0.0), 120.0)


def default_user_agent(contact_email: str = "") -> str:
    contact = f"; contact: {contact_email}" if contact_email else ""
    return f"ProfessorOutreachAssistant/1.0 (personal graduate-admissions research{contact})"


