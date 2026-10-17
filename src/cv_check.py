"""The CV that goes with every email: the right file, readable, sensible, and the same file you approved.

Set it once:   double-click choose_cv.bat (or: outreach cv --set "C:\\Users\\You\\Documents\\Sana_Sajid_CV.pdf")
Check it:      outreach cv
The file is copied into private_profile\\cv\\ (private; never uploaded) and CV_ATTACHMENT in .env points to it.

Every check is shown before approving and before sending. Approval records the CV's fingerprint; if the CV
file changes afterwards, sending stops until you confirm the new file.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .errors import UserFacingError
from .textutil import name_tokens, normalize_email, strip_accents

MAX_BYTES = 10 * 1024 * 1024  # too big for many university mail servers
WARN_BYTES = 2 * 1024 * 1024
WARN_PAGES = 4


@dataclass
class CVReport:
    path: Path | None
    exists: bool = False
    is_pdf: bool = False
    pages: int | None = None
    size_bytes: int = 0
    fingerprint: str = ""
    name_found: bool | None = None
    email_found: bool | None = None
    problems: list[str] = field(default_factory=list)  # any of these stops attaching or sending
    warnings: list[str] = field(default_factory=list)

    @property
    def ok_to_attach(self) -> bool:
        return self.exists and self.is_pdf and not self.problems

    @property
    def filename(self) -> str:
        return self.path.name if self.path else ""

    def summary(self) -> str:
        if not self.path:
            return "No CV is set up yet."
        if not self.exists:
            return f"CV not found: {self.path}"
        size = f"{self.size_bytes / 1024:.0f} KB" if self.size_bytes < 1024 * 1024 else f"{self.size_bytes / 1024 / 1024:.1f} MB"
        pages = f"{self.pages} page{'s' if self.pages != 1 else ''}, " if self.pages else ""
        return f"{self.filename} ({pages}{size}, fingerprint {self.fingerprint})"


def cv_path(settings) -> Path | None:
    raw = (settings.cv_attachment or "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else Path(settings.root) / path


def file_fingerprint(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(text or "").lower())


def inspect_cv(settings, profile: dict | None = None) -> CVReport:
    profile = profile or {}
    path = cv_path(settings)
    report = CVReport(path)
    if path is None:
        report.problems.append("No CV is set up yet. Double-click choose_cv.bat and pick your CV (PDF).")
        return report
    if not path.exists():
        report.problems.append(f"The CV file was not found at {path}. Choose it again: double-click choose_cv.bat.")
        return report
    report.exists = True
    data = path.read_bytes()
    report.size_bytes = len(data)
    report.fingerprint = hashlib.sha256(data).hexdigest()[:16]
    report.is_pdf = data[:5] == b"%PDF-"
    if not report.is_pdf:
        report.problems.append("The CV must be a PDF file (professors cannot always open Word files correctly).")
        return report
    text = ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if reader.is_encrypted:
            report.problems.append("The PDF is password-protected. Professors cannot open it: save it again without a password.")
            return report
        report.pages = len(reader.pages)
        text = " ".join((page.extract_text() or "") for page in reader.pages[:3])
    except Exception as exc:  # damaged or unusual PDF
        report.problems.append(f"The PDF could not be read ({exc.__class__.__name__}). Export it again from Word or Google Docs.")
        return report
    plain = _plain(text)
    tokens = [t for t in name_tokens(profile.get("name", "")) if len(t) > 1]
    if tokens:
        report.name_found = tokens[0] in plain and tokens[-1] in plain
        if not report.name_found:
            report.problems.append(f"This PDF does not contain your name ({profile.get('name')}). Is it the right file?")
    email = normalize_email(profile.get("email", ""))
    if email:
        report.email_found = email in plain.replace(" ", "")
        if not report.email_found:
            report.warnings.append(f"Your email address ({email}) is not in the CV. Professors reply to the address on the CV too.")
    if not text.strip():
        report.warnings.append("No text could be read from the PDF (it may be a scanned image). Professors' search tools cannot read it either.")
    if report.pages and report.pages > WARN_PAGES:
        report.warnings.append(f"The CV has {report.pages} pages. US professors expect about 2 pages; a long portfolio may not be read.")
    if report.size_bytes > MAX_BYTES:
        report.problems.append(f"The file is {report.size_bytes / 1024 / 1024:.1f} MB: too large to email. Keep it under 2 MB.")
    elif report.size_bytes > WARN_BYTES:
        report.warnings.append(f"The file is {report.size_bytes / 1024 / 1024:.1f} MB. Under 2 MB is safer for university mail servers.")
    if re.search(r"\(\d+\)|\bcopy\b|portfolio|untitled|\bfinal\b|\bnew\b|draft", path.stem, re.IGNORECASE):
        report.warnings.append(f"The file name '{path.name}' looks informal. The professor sees it: rename it like 'Sana_Sajid_CV.pdf'.")
    return report


def choose_pdf(start_dir: Path | None = None, input_fn=input, dialog=None) -> str:
    """Pick the CV in the normal "Open" window. Without a window (no desktop, or no tkinter), ask for the path.
    Returns '' when nothing was chosen."""
    picked = (dialog or _open_file_window)(start_dir)
    if picked is None:
        picked = input_fn("Type or paste the full path of your CV PDF (or drag the file into this window), then press Enter: ")
    return (picked or "").strip().strip('"')


def _open_file_window(start_dir: Path | None) -> str | None:
    """The standard file chooser; None when it cannot be shown."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None
    try:
        root = tk.Tk()
    except tk.TclError:  # no screen to show a window on
        return None
    try:
        root.withdraw()
        root.attributes("-topmost", True)  # in front of the black window
        start = str(start_dir) if start_dir and Path(start_dir).exists() else None
        return filedialog.askopenfilename(parent=root, title="Choose your CV (PDF) - it is attached to every email",
                                          initialdir=start, filetypes=[("PDF files", "*.pdf")]) or ""
    finally:
        root.destroy()


def set_cv(settings, source: str | Path) -> Path:
    """Copy the CV into private_profile/cv/ and point CV_ATTACHMENT in .env at the copy."""
    source = Path(str(source).strip().strip('"'))
    if not source.exists():
        raise UserFacingError(f"File not found: {source}")
    if source.suffix.lower() != ".pdf":
        raise UserFacingError("Please choose the PDF version of your CV.")
    dest_dir = Path(settings.private_dir) / "cv"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.name
    if source.resolve() != dest.resolve():
        shutil.copy2(source, dest)
    relative = dest.relative_to(settings.root).as_posix() if dest.is_relative_to(settings.root) else str(dest)
    env = Path(settings.root) / ".env"
    lines = env.read_text(encoding="utf-8-sig").splitlines() if env.exists() else []
    new_line = f'CV_ATTACHMENT="{relative}"'
    for i, line in enumerate(lines):
        if line.strip().startswith("CV_ATTACHMENT="):
            lines[i] = new_line
            break
    else:
        lines.append(new_line)
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    settings.cv_attachment = relative
    return dest
