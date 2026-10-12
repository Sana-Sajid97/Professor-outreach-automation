"""Settings and folder locations.

Settings come from environment variables or a local, Git-ignored `.env` file.
Nothing secret is ever stored in the code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> dict[str, str]:
    """Read KEY=VALUE lines from a .env file (comments and blank lines are ignored)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.lower().startswith("export "):
            key = key[7:].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        values[key] = value
    return values


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_float(value: str | None, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    """All tunable settings, with safe defaults."""

    root: Path = ROOT
    email_mode: str = "drafts_only"  # drafts_only | send_enabled
    default_intake: str = "Spring 2027"
    secondary_intake: str = "Fall 2027"
    daily_send_limit: int = 30
    follow_up_days: int = 10
    max_follow_ups: int = 1
    min_fit_for_draft: int = 4
    request_delay_seconds: float = 2.0
    contact_email: str = ""  # identifies you to websites/APIs (polite User-Agent)
    openalex_api_key: str = ""
    ncbi_api_key: str = ""
    cv_attachment: str = ""  # path to the CV PDF attached to Gmail drafts
    gmail_client_file: str = ""
    gmail_token_file: str = ""
    warnings: list[str] = field(default_factory=list)

    # ---------- folders ----------
    @property
    def private_dir(self) -> Path:
        return self.root / "private_profile"

    @property
    def profile_path(self) -> Path:
        return self.private_dir / "profile.json"

    @property
    def workspace_dir(self) -> Path:
        return self.root / "workspace"

    @property
    def tracker_path(self) -> Path:
        return self.workspace_dir / "tracker.csv"

    @property
    def evidence_dir(self) -> Path:
        """Snapshots of the official pages as they were when checked (private; never uploaded)."""
        return self.workspace_dir / "evidence"

    @property
    def old_drafts_dir(self) -> Path:
        """Emails set aside when a new check means they must be written again (kept so no text is ever lost)."""
        return self.workspace_dir / "old_drafts"

    @property
    def suppression_path(self) -> Path:
        return self.workspace_dir / "suppression_list.csv"

    @property
    def outreach_log_path(self) -> Path:
        return self.workspace_dir / "outreach_log.csv"

    @property
    def cache_dir(self) -> Path:
        return self.workspace_dir / "cache"

    @property
    def backup_dir(self) -> Path:
        return self.workspace_dir / "backups"

    @property
    def log_dir(self) -> Path:
        return self.workspace_dir / "logs"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    @property
    def seed_dir(self) -> Path:
        return self.root / "data" / "seed"

    @property
    def sample_dir(self) -> Path:
        return self.root / "data" / "sample"

    @property
    def gmail_client_path(self) -> Path:
        return Path(self.gmail_client_file) if self.gmail_client_file else self.private_dir / "credentials.json"

    @property
    def gmail_token_path(self) -> Path:
        return Path(self.gmail_token_file) if self.gmail_token_file else self.private_dir / "token.json"

    @property
    def sending_enabled(self) -> bool:
        return self.email_mode == "send_enabled"

    def ensure_folders(self) -> None:
        for folder in (self.private_dir, self.workspace_dir, self.exports_dir):
            folder.mkdir(parents=True, exist_ok=True)


def load_settings(root: Path | None = None, environ: dict[str, str] | None = None) -> Settings:
    """Build Settings from `.env` (if present) and environment variables.

    Environment variables win over `.env` values.
    """
    env = os.environ if environ is None else environ
    root = Path(root) if root else Path(env.get("OUTREACH_ROOT") or ROOT)
    values = load_dotenv(root / ".env")
    for key, value in env.items():
        values[key] = value

    s = Settings(root=root)
    mode = values.get("EMAIL_MODE", "drafts_only").strip().lower() or "drafts_only"
    if mode not in {"drafts_only", "send_enabled"}:
        s.warnings.append(f"EMAIL_MODE={mode!r} is not recognised; using drafts_only.")
        mode = "drafts_only"
    s.email_mode = mode
    if not _as_bool(values.get("REQUIRE_HUMAN_APPROVAL"), True):
        s.warnings.append(
            "REQUIRE_HUMAN_APPROVAL=false is ignored: every email always needs your explicit approval."
        )
    s.default_intake = values.get("DEFAULT_INTAKE_PRIORITY", s.default_intake) or s.default_intake
    s.secondary_intake = values.get("SECONDARY_INTAKE", s.secondary_intake) or s.secondary_intake
    s.daily_send_limit = max(1, _as_int(values.get("DAILY_SEND_LIMIT"), s.daily_send_limit))
    if s.daily_send_limit > 50:
        s.warnings.append(
            f"DAILY_SEND_LIMIT={s.daily_send_limit} is high. Personalised academic emails work best in "
            "small batches; large volumes from a personal account risk spam flags."
        )
    s.follow_up_days = max(3, _as_int(values.get("FOLLOW_UP_DAYS"), s.follow_up_days))
    s.max_follow_ups = max(0, min(1, _as_int(values.get("MAX_FOLLOW_UPS"), s.max_follow_ups)))  # 0 or 1
    s.min_fit_for_draft = max(0, min(10, _as_int(values.get("MIN_FIT_FOR_DRAFT"), s.min_fit_for_draft)))
    s.request_delay_seconds = max(1.0, _as_float(values.get("REQUEST_DELAY_SECONDS"), s.request_delay_seconds))
    s.contact_email = values.get("CONTACT_EMAIL", "").strip()
    s.openalex_api_key = values.get("OPENALEX_API_KEY", "").strip()
    s.ncbi_api_key = values.get("NCBI_API_KEY", "").strip()
    s.cv_attachment = values.get("CV_ATTACHMENT", "").strip()
    s.gmail_client_file = values.get("GMAIL_OAUTH_CLIENT_FILE", "").strip()
    s.gmail_token_file = values.get("GMAIL_TOKEN_FILE", "").strip()
    return s
