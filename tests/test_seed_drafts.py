"""Every researched lead in data/seed must produce a clean draft (checked with the fictional test profile).

This guards the wording against research notes leaking into emails ("Not verified ...", "probably ...",
"the MS is self-funded ..."), lab names quoted as research, third-person phrases, and over-long bodies.
"""

from __future__ import annotations

import re

import pytest

from src.drafting import build_draft
from src.storage import load_records

from .conftest import ROOT

SEED = ROOT / "data" / "seed" / "professors_leads.csv"
FORBIDDEN = [
    r"\bnot verified\b", r"\bnot captured\b", r"\bnot confirmed\b", r"\bprobably\b", r"\bself-funded\b",
    r"search (?:summary|result)", r"\b(?:he|she|his)\b", r"\bResearch Group\b", r"\bI read\b", r"\[|\{\{", r"\(\s*$",
]


@pytest.mark.skipif(not SEED.exists(), reason="no seed data")
def test_every_seed_lead_gets_a_clean_draft(profile, today):
    records = [r for r in load_records(SEED) if r.get("workflow_status") != "not_a_fit"]
    assert len(records) > 100
    problems = []
    for rec in records:
        draft = build_draft(dict(rec), profile, today)
        paragraphs = draft.body.split("\n\n")
        words = sum(len(p.split()) for p in paragraphs[1:-1])
        if words > 220:
            problems.append((rec["record_id"], f"{words} words"))
        professor_facing = paragraphs[1] + " " + next((p for p in paragraphs if p.startswith("I am planning to apply")), "")
        professor_facing = re.sub(r'"[^"]*"', '""', professor_facing)  # paper titles are quoted as published
        for pattern in FORBIDDEN:
            if re.search(pattern, professor_facing, re.IGNORECASE if pattern.islower() else 0):
                problems.append((rec["record_id"], pattern))
        if len(draft.subject) > 95 or "  " in draft.subject:
            problems.append((rec["record_id"], "subject"))
    assert problems == []
