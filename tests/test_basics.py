"""Text helpers, statuses, storage and configuration."""

from __future__ import annotations

from datetime import date

import pytest

from src import models as m
from src.config import load_dotenv, load_settings
from src.errors import TransitionError
from src.storage import assign_missing_ids, load_records, read_any, save_records
from src.textutil import (
    find_dates,
    is_generic_email,
    is_valid_email,
    last_name,
    name_key,
    normalize_email,
    normalize_url,
    registrable_domain,
    split_multi,
)

from .conftest import make_record


@pytest.mark.parametrize(
    "name,key,last",
    [
        ("Rafael Pérez-Escamilla, PhD", "rafael perez-escamilla", "Pérez-Escamilla"),
        ("Leung, Cindy", "cindy leung", "Leung"),
        ("Cindy W. Leung, ScD, MPH", "cindy leung", "Leung"),
        ("Jiantao Ma", "jiantao ma", "Ma"),
        ("Dr. Anh Do", "anh do", "Do"),
        ("Ludwig van Beethoven", "ludwig beethoven", "van Beethoven"),
    ],
)
def test_names(name, key, last):
    assert name_key(name) == key
    assert last_name(name) == last


def test_email_helpers():
    assert normalize_email("mailto:Jane.Doe@UGA.edu?subject=hi") == "jane.doe@uga.edu"
    assert is_valid_email("rafael.perez-escamilla@yale.edu")
    assert not is_valid_email("not an email")
    assert not is_valid_email("a@b")
    assert is_generic_email("gradadmissions@uga.edu")
    assert not is_generic_email("jdoe@uga.edu")


def test_urls_and_domains():
    assert registrable_domain("nutrition.cals.cornell.edu") == "cornell.edu"
    assert registrable_domain("www.uaar.edu.pk") == "uaar.edu.pk"
    assert normalize_url("http://www.Example.edu/People/Jane/index.html?utm_source=x&id=3#top") == "https://example.edu/people/jane?id=3"
    assert normalize_url("https://example.edu/a/") == normalize_url("https://www.example.edu/a")


def test_dates_and_lists():
    text = "intl deadline 2026-11-01; Fall: Dec 1, 2026 and 15 January 2027, 02/15/2027"
    assert find_dates(text) == [date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 15), date(2027, 2, 15)]
    assert split_multi("a; b | c\nA") == ["a", "b", "c"]


def test_transitions():
    m.check_transition(m.VERIFIED, m.DRAFT_READY)
    m.check_transition(m.SENT, m.OPTED_OUT)  # suppression is always allowed
    with pytest.raises(TransitionError):
        m.check_transition(m.DISCOVERED, m.SENT)
    with pytest.raises(TransitionError):
        m.check_transition(m.OPTED_OUT, m.VERIFIED)
    with pytest.raises(TransitionError):
        m.check_transition(m.VERIFIED, "nonsense")


def test_csv_roundtrip_keeps_multiline_cells_and_unicode(tmp_path):
    path = tmp_path / "tracker.csv"
    rec = make_record(email_draft="Dear Dr. X,\n\nLine two with accents: Pérez.\n\nThanks", custom_column="kept")
    save_records(path, [rec], backup_dir=tmp_path / "backups")
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM so Excel shows accents
    loaded = load_records(path)
    assert loaded[0]["email_draft"] == rec["email_draft"]
    assert loaded[0]["custom_column"] == "kept"
    save_records(path, loaded, backup_dir=tmp_path / "backups")
    assert list((tmp_path / "backups").glob("tracker_*.csv"))


def test_read_cp1252_csv_from_excel(tmp_path):
    path = tmp_path / "excel.csv"
    path.write_bytes("record_id,professor_name,university\nR0001,Jos\xe9 Garc\xeda,Test University\n".encode("cp1252"))
    rows = read_any(path)
    assert rows[0]["professor_name"] == "José García"
    assert rows[0]["workflow_status"] == m.DISCOVERED


def test_xlsx_import(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["record_id", "professor_name", "university", "fit_score"])
    ws.append(["R0009", "Alex Example", "Test University", 7])
    path = tmp_path / "in.xlsx"
    wb.save(path)
    rows = read_any(path)
    assert rows[0]["professor_name"] == "Alex Example"
    assert rows[0]["fit_score"] == "7"


def test_assign_ids_unique():
    records = [make_record(record_id=""), make_record(record_id="R0005"), make_record(record_id="R0005")]
    assign_missing_ids(records)
    ids = [r["record_id"] for r in records]
    assert len(set(ids)) == 3


def test_settings_defaults_and_guards(tmp_path):
    (tmp_path / ".env").write_text("EMAIL_MODE=send_enabled\nREQUIRE_HUMAN_APPROVAL=false\nDAILY_SEND_LIMIT=300\n# comment\n", encoding="utf-8")
    s = load_settings(root=tmp_path, environ={})
    assert s.sending_enabled
    assert s.daily_send_limit == 300
    assert any("ignored" in w for w in s.warnings)  # approval can never be turned off
    assert any("high" in w for w in s.warnings)
    assert load_dotenv(tmp_path / "missing.env") == {}
    s2 = load_settings(root=tmp_path, environ={"EMAIL_MODE": "weird"})
    assert s2.email_mode == "drafts_only"
