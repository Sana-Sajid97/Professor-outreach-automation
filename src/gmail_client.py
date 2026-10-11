"""Optional Gmail API integration (create drafts in your Gmail; sending only if you enable it).

Needs extra packages (pip install -r requirements-gmail.txt) and a Google Cloud OAuth
"Desktop app" client file saved as private_profile/credentials.json. See
docs/GMAIL_SETUP.md. Nothing here runs unless you choose a Gmail option yourself.
"""

from __future__ import annotations

import base64
import mimetypes
from email.message import EmailMessage
from pathlib import Path

from .errors import UserFacingError

# gmail.compose = create drafts and send them (narrowest scope that covers both).
SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


def build_raw_message(to: str, subject: str, body: str, sender: str = "", attachment: Path | None = None) -> str:
    """Return the base64url-encoded RFC 2822 message that the Gmail API expects."""
    msg = EmailMessage()
    msg["To"] = to
    if sender:
        msg["From"] = sender
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment:
        attachment = Path(attachment)
        if not attachment.exists():
            raise UserFacingError(f"CV attachment not found: {attachment}. Fix CV_ATTACHMENT in your .env file.")
        ctype, _ = mimetypes.guess_type(attachment.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(attachment.read_bytes(), maintype=maintype, subtype=subtype, filename=attachment.name)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def _require_libraries():
    try:
        from google.auth.exceptions import RefreshError  # noqa: F401
        from google.auth.transport.requests import Request  # noqa: F401
        from google.oauth2.credentials import Credentials  # noqa: F401
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401
    except ImportError as exc:
        raise UserFacingError(
            "Gmail features need extra packages. Run:  .venv\\Scripts\\python -m pip install -r requirements-gmail.txt"
        ) from exc


def get_service(client_file: Path, token_file: Path):
    """Sign in (opens your browser the first time) and return a Gmail API service."""
    _require_libraries()
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    client_file, token_file = Path(client_file), Path(token_file)
    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            token_file.unlink(missing_ok=True)  # expired or revoked: sign in again
            creds = None
    if not creds or not creds.valid:
        if not client_file.exists():
            raise UserFacingError(
                f"Gmail is not set up: {client_file} was not found. Follow docs/GMAIL_SETUP.md, or use the "
                "no-setup option instead (open the review page and click 'Open in Gmail')."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
        creds = flow.run_local_server(port=0, timeout_seconds=300)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def create_draft(service, raw: str) -> str:
    result = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    return result.get("id", "")


def send_raw(service, raw: str) -> str:
    result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    message_id = result.get("id", "")
    if not message_id:
        raise RuntimeError("Gmail did not return a message id; the email may not have been sent.")
    return message_id
