"""Snapshots of official pages, kept as evidence of what a page said when it was checked.

Saved as plain text in workspace/evidence/ (private; never uploaded to GitHub), one file per
web address. The editor uses them to re-check your own edits against the official page
without visiting the site again.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from .textutil import normalize_url

MAX_CHARS = 200_000


def snapshot_path(evidence_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:24]
    return Path(evidence_dir) / f"{digest}.txt"


def save_snapshot(evidence_dir: Path | None, url: str, text: str, fetched_on: date) -> Path | None:
    if not evidence_dir or not url or not text:
        return None
    path = snapshot_path(evidence_dir, url)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"URL: {url}\nChecked: {fetched_on.isoformat()}\n\n{text[:MAX_CHARS]}", encoding="utf-8")
    except OSError:
        return None
    return path


def load_snapshot(evidence_dir: Path | None, url: str) -> tuple[str, str] | None:
    """(page text, date checked) or None."""
    if not evidence_dir or not url:
        return None
    path = snapshot_path(evidence_dir, url)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    header, _, body = raw.partition("\n\n")
    checked = ""
    for line in header.splitlines():
        if line.startswith("Checked: "):
            checked = line[len("Checked: "):].strip()
    return body, checked
