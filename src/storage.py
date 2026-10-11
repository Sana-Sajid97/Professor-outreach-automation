"""Reading and writing the tracker (CSV is the source of truth; XLSX/JSONL can be imported).

Design choices for non-programmers on Windows:
- CSV files are written as UTF-8 *with* a BOM so Excel shows accented names correctly.
- Files saved from Excel in the old Windows encoding (cp1252) can still be read.
- Every save first makes a timestamped backup, then replaces the file atomically.
- If Excel has the file open (Windows locks it) the user gets a clear message.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .errors import UserFacingError
from .models import ALL_FIELDS, normalize_record

MAX_BACKUPS = 30


def read_text_any_encoding(path: Path) -> str:
    data = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")  # pragma: no cover - latin-1 never fails


def read_csv_rows(path: Path) -> tuple[list[dict], list[str]]:
    """Return (rows, header) from a CSV file."""
    path = Path(path)
    if not path.exists():
        raise UserFacingError(f"File not found: {path}")
    text = read_text_any_encoding(path)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t") if sample.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    header = [h.strip().lstrip("﻿") for h in (reader.fieldnames or [])]
    rows = []
    for row in reader:
        clean_row = {(k or "").strip().lstrip("﻿"): v for k, v in row.items() if k is not None}
        if any((v or "").strip() for v in clean_row.values()):
            rows.append(clean_row)
    return rows, header


def read_xlsx_rows(path: Path, sheet: str | None = None) -> tuple[list[dict], list[str]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency is in requirements.txt
        raise UserFacingError("Reading Excel files needs openpyxl. Run: pip install -r requirements.txt") from exc
    wb = load_workbook(Path(path), read_only=True, data_only=True)
    ws = None
    if sheet and sheet in wb.sheetnames:
        ws = wb[sheet]
    else:
        # Prefer a sheet that has a record_id/professor_name header.
        for candidate in wb.worksheets:
            first = next(candidate.iter_rows(min_row=1, max_row=1, values_only=True), ())
            names = {str(c).strip() for c in first if c is not None}
            if "professor_name" in names:
                ws = candidate
                break
        ws = ws or wb.worksheets[0]
    rows_iter = ws.iter_rows(values_only=True)
    header_row = next(rows_iter, ())
    header = [str(h).strip() if h is not None else "" for h in header_row]
    rows = []
    for values in rows_iter:
        row = {header[i]: values[i] for i in range(min(len(header), len(values))) if header[i]}
        if any(v not in (None, "") for v in row.values()):
            rows.append(row)
    wb.close()
    return rows, header


def read_jsonl_rows(path: Path) -> tuple[list[dict], list[str]]:
    rows, header = [], []
    for n, line in enumerate(read_text_any_encoding(Path(path)).splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise UserFacingError(f"{path}: line {n} is not valid JSON ({exc.msg}).") from exc
        if isinstance(obj, dict):
            rows.append(obj)
            for key in obj:
                if key not in header:
                    header.append(key)
    return rows, header


def read_any(path: Path) -> list[dict]:
    """Read records from .csv, .xlsx or .jsonl into normalised record dicts."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        rows, _ = read_xlsx_rows(path)
    elif suffix in {".jsonl", ".ndjson"}:
        rows, _ = read_jsonl_rows(path)
    elif suffix == ".json":
        data = json.loads(read_text_any_encoding(path))
        rows = data if isinstance(data, list) else data.get("records", [])
    else:
        rows, _ = read_csv_rows(path)
    return [normalize_record(r) for r in rows]


def load_records(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return read_any(path)


def ordered_columns(records: list[dict]) -> list[str]:
    columns = list(ALL_FIELDS)
    for record in records:
        for key in record:
            if key not in columns:
                columns.append(key)  # keep any custom columns the user added
    return columns


def backup_file(path: Path, backup_dir: Path) -> Path | None:
    path = Path(path)
    if not path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = backup_dir / f"{path.stem}_{stamp}{path.suffix}"
    shutil.copy2(path, target)
    backups = sorted(backup_dir.glob(f"{path.stem}_*{path.suffix}"))
    for old in backups[:-MAX_BACKUPS]:
        try:
            old.unlink()
        except OSError:
            pass
    return target


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    """Write rows atomically as Excel-friendly UTF-8 CSV."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({c: ("" if row.get(c) is None else row.get(c)) for c in columns})
        try:
            os.replace(tmp_name, path)
        except PermissionError as exc:
            raise UserFacingError(
                f"Could not save {path.name} because another program (usually Excel) has it open. "
                "Close the file and run the command again."
            ) from exc
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def save_records(path: Path, records: list[dict], backup_dir: Path | None = None) -> None:
    path = Path(path)
    if backup_dir is not None:
        backup_file(path, backup_dir)
    write_csv(path, records, ordered_columns(records))


def next_record_id(records: list[dict]) -> str:
    highest = 0
    for record in records:
        rid = str(record.get("record_id", ""))
        digits = "".join(ch for ch in rid if ch.isdigit())
        if rid.upper().startswith("R") and digits:
            highest = max(highest, int(digits))
    return f"R{highest + 1:04d}"


def assign_missing_ids(records: list[dict]) -> int:
    """Give every record without a record_id a new unique one. Returns how many were assigned."""
    assigned = 0
    seen = set()
    for record in records:
        rid = record.get("record_id", "").strip()
        if not rid or rid in seen:
            record["record_id"] = next_record_id(records)
            assigned += 1
        seen.add(record["record_id"])
    return assigned


def append_csv_row(path: Path, row: dict, columns: list[str]) -> None:
    """Append one row (used for audit logs). Creates the file with a header if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    try:
        with open(path, "a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            if new_file:
                writer.writeheader()
            writer.writerow({c: row.get(c, "") for c in columns})
    except PermissionError as exc:
        raise UserFacingError(
            f"Could not write to {path.name} because another program has it open. Close it and try again."
        ) from exc
