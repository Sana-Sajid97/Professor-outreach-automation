"""Command-line interface. Run `python -m src.cli --help` for the list of commands.

On Windows you can also double-click the numbered .bat files in the project folder,
or type `outreach <command>` (outreach.bat) in a Command Prompt opened in the folder.
"""

from __future__ import annotations

import argparse
import platform
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

from . import __version__
from . import models as m
from .config import Settings, load_settings
from .errors import UserFacingError

DATE_HELP = "date in YYYY-MM-DD (default: today)"


# ----------------------------------------------------------------------------- helpers
def _today(value: str | None) -> date:
    if not value:
        return date.today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise UserFacingError(f"Dates must look like 2026-10-15 (got '{value}').") from exc


def _ids(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.replace(";", ",").split(",") if v.strip()]


_STAMPS: dict[str, str | None] = {}  # tracker fingerprint when this command loaded it


def _load(settings: Settings):
    from .storage import file_stamp, load_records
    from .suppression import SuppressionList

    _STAMPS[str(settings.tracker_path)] = file_stamp(settings.tracker_path)
    records = load_records(settings.tracker_path)
    if not records:
        raise UserFacingError(
            "Your tracker is empty. Start it with:  python -m src.cli init   (uses the researched leads), "
            "or add records with:  python -m src.cli import --file your_file.csv"
        )
    # The suppression list always wins, whatever command runs next.
    SuppressionList.load(settings.suppression_path).apply(records, date.today())
    from .tracker import reconcile_with_log

    for rid in reconcile_with_log(records, settings):
        print(f"{rid}: the outreach log shows this email was sent, so its status was restored to 'sent'.")
    return records


def _save(settings: Settings, records, backup: bool = True) -> None:
    """Save the tracker, unless another window (such as the draft editor) changed it since this command loaded it."""
    from .storage import file_stamp, save_records

    key = str(settings.tracker_path)
    if key in _STAMPS and file_stamp(settings.tracker_path) != _STAMPS[key]:
        raise UserFacingError(
            "The tracker was changed by another window (probably the draft editor) while this command was running. "
            "To avoid overwriting those changes, this command did not save. Close the other window and run the command again."
        )
    save_records(settings.tracker_path, records, settings.backup_dir if backup else None)
    _STAMPS[key] = file_stamp(settings.tracker_path)


def _profile(settings: Settings) -> dict:
    from .profile import load_profile

    return load_profile(settings.profile_path)


def _get(records, rid: str) -> dict:
    from .tracker import find_record

    record = find_record(records, rid)
    if record is None:
        raise UserFacingError(f"No record with id {rid}. Run 'python -m src.cli list' to see ids.")
    return record


# ----------------------------------------------------------------------------- commands
def cmd_doctor(settings: Settings, args) -> int:
    ok = True
    print(f"Professor Outreach Assistant {__version__}")
    print(f"Python {platform.python_version()} on {platform.system()} {platform.release()}")
    if sys.version_info < (3, 10):
        print("PROBLEM: Python 3.10 or newer is required. Install the latest Python from python.org.")
        ok = False
    for module, purpose in (("openpyxl", "Excel export"), ("pypdf", "reading your CV PDF"), ("requests", "verifying pages"), ("bs4", "reading web pages")):
        try:
            __import__(module)
            print(f"  ok   {module:10s} ({purpose})")
        except ImportError:
            print(f"  MISSING {module} ({purpose}). Run: .venv\\Scripts\\python -m pip install -r requirements.txt")
            ok = False
    try:
        __import__("googleapiclient")
        print("  ok   google-api-python-client (optional Gmail drafts)")
    except ImportError:
        print("  info Gmail API packages not installed (optional; see docs/GMAIL_SETUP.md)")
    print(f"Project folder: {settings.root}")
    print(f"  profile:     {'found' if settings.profile_path.exists() else 'NOT imported yet (run import-profile)'}")
    print(f"  tracker:     {'found' if settings.tracker_path.exists() else 'not started yet (run init)'}")
    print(f"  .env file:   {'found' if (settings.root / '.env').exists() else 'not found (optional; copy .env.example to .env)'}")
    print(f"  email mode:  {settings.email_mode} (sending {'ENABLED' if settings.sending_enabled else 'disabled - drafts only'})")
    print(f"  daily limit: {settings.daily_send_limit}")
    print(f"  OpenAlex key: {'set' if settings.openalex_api_key else 'not set (optional discovery)'}")
    for w in settings.warnings:
        print("WARNING: " + w)
    print("Everything looks ready." if ok else "Please fix the problems above.")
    return 0 if ok else 1


def cmd_import_profile(settings: Settings, args) -> int:
    from .profile import find_profile_source, import_profile, summarize_profile

    source = Path(args.file) if args.file else find_profile_source(settings.private_dir, settings.root)
    if source is None:
        raise UserFacingError("No CV/portfolio PDF found. Put it in the 'private_profile' folder or use --file.")
    settings.ensure_folders()
    if settings.profile_path.exists() and not args.force:
        raise UserFacingError(
            "private_profile/profile.json already exists (it may contain your edits). Use --force to re-import and overwrite it."
        )
    profile = import_profile(source, settings.profile_path, date.today())
    print(f"Imported profile from: {source}")
    print(summarize_profile(profile))
    print(f"\nSaved to {settings.profile_path}. Open it in Notepad to check and edit. It is private (not uploaded to GitHub).")
    if source.parent.resolve() == settings.root.resolve():
        print("NOTE: your PDF is in the main project folder. Move it into 'private_profile' so it is never uploaded to GitHub.")
    return 0


def cmd_init(settings: Settings, args) -> int:
    from .storage import assign_missing_ids, read_any, save_records

    settings.ensure_folders()
    if settings.tracker_path.exists() and not args.force:
        raise UserFacingError("Your tracker already exists. Use 'import' to add more records, or --force to start over (a backup is kept).")
    source = Path(args.source) if args.source else (settings.sample_dir / "sample_professors.csv" if args.sample else settings.seed_dir / "professors_leads.csv")
    if not source.exists():
        raise UserFacingError(f"Starting file not found: {source}")
    from .sending import reset_approval_for_import

    records = read_any(source)
    for r in records:
        if not r.get("record_source"):
            r["record_source"] = "sample" if args.sample else source.name
        reset_approval_for_import(r)
    assign_missing_ids(records)
    save_records(settings.tracker_path, records, settings.backup_dir)
    print(f"Tracker created with {len(records)} record(s) from {source.name}: {settings.tracker_path}")
    return 0


def cmd_import(settings: Settings, args) -> int:
    from .dedupe import dedupe_records
    from .storage import assign_missing_ids, load_records, read_any

    settings.ensure_folders()
    records = load_records(settings.tracker_path)
    from .sending import reset_approval_for_import

    new = read_any(Path(args.file))
    for r in new:
        if not r.get("record_source"):
            r["record_source"] = Path(args.file).name
        reset_approval_for_import(r)
    before = len(records)
    records.extend(new)
    assign_missing_ids(records)
    result = dedupe_records(records)
    _save(settings, result.records)
    merged = sum(len(g.merged_ids) for g in result.merges)
    print(f"Added {len(new)} record(s); {merged} duplicate(s) merged. Tracker now has {len(result.records)} (was {before}).")
    return 0


def cmd_list(settings: Settings, args) -> int:
    records = _load(settings)
    if args.status:
        records = [r for r in records if r.get("workflow_status") == args.status]
    records.sort(key=lambda r: -float(r.get("fit_score") or 0))
    for r in records[: args.limit]:
        print(f"{r.get('record_id'):6s} fit {r.get('fit_score') or '-':>2s}  {r.get('workflow_status'):18s} {r.get('professor_name')[:28]:28s} {r.get('university')[:40]}")
    print(f"({len(records)} shown of matching records)")
    return 0


def cmd_status(settings: Settings, args) -> int:
    from .tracker import refresh_follow_ups, status_counts

    records = _load(settings)
    today = date.today()
    due = refresh_follow_ups(records, today, settings)
    if due:
        _save(settings, records)
    counts = status_counts(records)
    print("Records by status:")
    for status, count in counts.items():
        if count:
            print(f"  {status:20s} {count}")
    if due:
        print(f"Follow-ups due now: {', '.join(due)}  ->  python -m src.cli followups --draft")
    upcoming = sorted((r.get("follow_up_date"), r.get("record_id"), r.get("professor_name")) for r in records if r.get("follow_up_date") and r.get("workflow_status") == m.SENT)
    for when, rid, name in upcoming[:10]:
        print(f"  follow-up {when}: {rid} {name}")
    return 0


def cmd_verify(settings: Settings, args) -> int:
    from .textutil import clean
    from .http_client import PoliteClient, default_user_agent
    from .verify import verify_record

    records = _load(settings)
    wanted = {i.upper() for i in _ids(args.ids)}
    todo = [r for r in records if (r.get("record_id", "").upper() in wanted) if wanted] or [
        r for r in records if r.get("workflow_status") in {m.DISCOVERED, m.NEEDS_VERIFICATION} and not wanted
    ]
    todo = todo[: args.limit]
    if not todo:
        print("Nothing to verify.")
        return 0
    from .checks import load_checks, summary_text

    client = PoliteClient(default_user_agent(settings.contact_email), settings.request_delay_seconds, settings.cache_dir)
    applicant_ielts = _applicant_ielts(settings)
    print(f"Checking {len(todo)} record(s) on official pages (about {settings.request_delay_seconds:.0f}s between requests per site).")
    print("Each record: profile, email, research, papers, program page and funding.")
    counts = {m.VER_VERIFIED: 0, m.VER_PARTIAL: 0, m.VER_NOT: 0}
    try:
        for r in todo:
            outcome = verify_record(r, client, date.today(), evidence_dir=settings.evidence_dir, applicant_ielts=applicant_ielts)
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            print(f"  {outcome.record_id} {clean(r.get('professor_name'))}: {outcome.status}")
            print(f"      {summary_text(load_checks(r))}")
    finally:
        _save(settings, records)
    print(f"Verified (profile, email and research all checked): {counts[m.VER_VERIFIED]}; "
          f"partly: {counts[m.VER_PARTIAL]}; not confirmed: {counts[m.VER_NOT]}.")
    print("For the others, the next_action column says exactly what is missing. The editor page shows every check with its evidence.")
    return 0


def _applicant_ielts(settings: Settings) -> float | None:
    if not settings.profile_path.exists():
        return None
    try:
        return float((_profile(settings).get("english_test") or {}).get("overall"))
    except (TypeError, ValueError):
        return None


def cmd_confirm(settings: Settings, args) -> int:
    """You checked something yourself on an official page: record it as 'confirmed by you'."""
    from .checks import confirm_check, load_checks, summary_text

    records = _load(settings)
    record = _get(records, args.id)
    confirm_check(record, args.check, args.source_url, date.today(), args.note or "")
    from .tracker import log_event

    log_event(settings, record, "check_confirmed", f"{args.check}: {args.source_url}")
    _save(settings, records)
    print(f"{args.id}: {args.check} marked as checked by you.")
    print(f"  {summary_text(load_checks(record))}")
    print(f"  Status: {record.get('verification_status')}. Next: {record.get('next_action', '')[:200]}")
    return 0


def cmd_confirm_email(settings: Settings, args) -> int:
    from .verify import confirm_email_manually

    records = _load(settings)
    record = _get(records, args.id)
    confirm_email_manually(record, args.email, args.source_url, date.today())
    _save(settings, records)
    print(f"{args.id}: email confirmed as {record['institutional_email']} (source: {args.source_url}).")
    return 0


EDITABLE_FIELDS = [
    "research_interests", "title", "department_or_school", "university", "state", "faculty_profile_url", "lab_url",
    "relevant_publication_1", "publication_1_url", "publication_1_year", "relevant_publication_2", "publication_2_url",
    "publication_2_year", "graduate_program", "program_url", "spring_2027_status", "fall_2027_status",
    "recruiting_evidence", "funding_or_assistantship_evidence", "application_deadline", "eligibility_notes", "personal_note",
]
REVERIFY_FIELDS = {"faculty_profile_url", "university"}
REDRAFT_FIELDS = {"research_interests", "relevant_publication_1", "relevant_publication_2", "publication_1_year", "publication_2_year", "personal_note", "title"}


def cmd_set(settings: Settings, args) -> int:
    """Change one field of one record safely (instead of editing tracker.csv in Excel)."""
    from .textutil import is_valid_url
    from .tracker import log_event, set_status

    if args.field not in EDITABLE_FIELDS:
        raise UserFacingError(
            f"'{args.field}' cannot be changed with this command. Fields you can change: {', '.join(EDITABLE_FIELDS)}. "
            "(Emails: use confirm-email. Statuses: use mark-sent, not-a-fit, close and so on.)"
        )
    value = (args.value or "").strip()
    if value and args.field.endswith("_url") and not is_valid_url(value):
        raise UserFacingError(f"'{value}' is not a full web address (it should start with https://).")
    if value and args.field.endswith("_year") and not (value.isdigit() and len(value) == 4):
        raise UserFacingError("A year must be four digits, for example 2025.")
    records = _load(settings)
    record = _get(records, args.id)
    old = record.get(args.field, "")
    record[args.field] = value
    log_event(settings, record, "field_set", f"{args.field}: '{old[:80]}' -> '{value[:80]}'")
    print(f"{args.id}: {args.field} updated.")
    status = record.get("workflow_status", "")
    if args.field in REVERIFY_FIELDS and status in {m.VERIFIED, m.DRAFT_READY, m.APPROVED} and value != old:
        set_status(record, m.NEEDS_VERIFICATION, date.today(), settings, note=f"{args.field} changed; verify again")
        record["verification_status"] = m.VER_PARTIAL if record.get("verification_status") == m.VER_VERIFIED else record.get("verification_status", "")
        record["approval_hash"] = ""
        print("  This changes who/where the person is, so the record needs verifying again (python -m src.cli verify).")
    elif args.field in REDRAFT_FIELDS and status in {m.DRAFT_READY, m.APPROVED}:
        print(f"  The current draft does not include this change yet. Rewrite it with:  python -m src.cli draft --ids {args.id} --force")
    _save(settings, records)
    return 0


def cmd_note(settings: Settings, args) -> int:
    from .tracker import log_event

    records = _load(settings)
    record = _get(records, args.id)
    text = " ".join((args.text or "").split())
    if not text:
        raise UserFacingError("The note is empty.")
    record["notes"] = f"{record.get('notes', '').strip()} | {date.today().isoformat()}: {text}".strip(" |")
    log_event(settings, record, "note_added", text[:200])
    _save(settings, records)
    print(f"{args.id}: note added.")
    return 0


def cmd_validate(settings: Settings, args) -> int:
    from .suppression import SuppressionList
    from .validate import summarize_issues, validate_all

    records = _load(settings)
    profile = _profile(settings) if settings.profile_path.exists() else {}
    try:
        ielts = float((profile.get("english_test") or {}).get("overall"))
    except (TypeError, ValueError):
        ielts = None
    issues = validate_all(records, date.today(), SuppressionList.load(settings.suppression_path).email_set, ielts)
    for issue in issues:
        if issue.severity == "error" or args.all:
            print(f"[{issue.severity.upper():7s}] {issue.record_id:6s} {issue.field}: {issue.message}")
    print(summarize_issues(issues) + ("" if args.all else "  (use --all to also list warnings)"))
    return 0


def cmd_dedupe(settings: Settings, args) -> int:
    from .dedupe import dedupe_records

    records = _load(settings)
    result = dedupe_records(records)
    for group in result.merges:
        print(f"Merged {', '.join(group.merged_ids)} into {group.kept_id} (same {', '.join(group.reasons)})" + (f" CHECK: {'; '.join(group.conflicts)}" if group.conflicts else ""))
    for a, b, why in result.possible:
        print(f"Possible duplicate (not merged): {a} / {b}: {why}")
    if args.dry_run:
        print("Dry run: nothing saved.")
    else:
        _save(settings, result.records)
        print(f"Saved. {len(records)} -> {len(result.records)} records.")
    return 0


def cmd_score(settings: Settings, args) -> int:
    from .scoring import apply_scores

    records = _load(settings)
    apply_scores(records, _profile(settings), date.today())
    _save(settings, records)
    for r in sorted(records, key=lambda r: -float(r.get("fit_score") or 0))[:15]:
        print(f"{r.get('record_id'):6s} {r.get('fit_score'):>2s}/10  {r.get('professor_name')[:30]:30s} {r.get('university')[:35]}")
    print("Scores are a prioritisation aid only - not an admission probability. See the fit_score_breakdown column.")
    return 0


def cmd_draft(settings: Settings, args) -> int:
    from .drafting import apply_draft, build_draft, can_draft
    from .suppression import SuppressionList
    from .tracker import log_event

    records = _load(settings)
    profile = _profile(settings)
    suppression = SuppressionList.load(settings.suppression_path)
    wanted = {i.upper() for i in _ids(args.ids)}
    made = 0
    for r in sorted(records, key=lambda r: -float(r.get("fit_score") or 0)):
        if made >= args.limit:
            break
        if wanted and r.get("record_id", "").upper() not in wanted:
            continue
        ok, reason = can_draft(r, date.today(), settings.min_fit_for_draft, suppression.is_suppressed(r), force=args.force,
                               discard_edits=args.discard_edits)
        if not ok:
            if wanted:
                print(f"{r.get('record_id')}: not drafted - {reason}")
            continue
        draft = build_draft(r, profile, date.today())
        apply_draft(r, draft, date.today())
        log_event(settings, r, "draft_created", f"subject={draft.subject}")
        made += 1
        print(f"{r.get('record_id')}: drafted '{draft.subject}'" + (f"  [{'; '.join(draft.warnings)}]" if draft.warnings else ""))
    _save(settings, records)
    print(f"{made} draft(s) written. Review them with:  python -m src.cli review")
    return 0


def cmd_review(settings: Settings, args) -> int:
    from .review import write_review_page

    from .sending import send_problem
    from .suppression import SuppressionList

    records = _load(settings)
    suppression = SuppressionList.load(settings.suppression_path)
    chosen = [r for r in records if r.get("workflow_status") in {m.DRAFT_READY, m.APPROVED} and r.get("email_draft")]
    chosen.sort(key=lambda r: -float(r.get("fit_score") or 0))
    profile = _profile(settings) if settings.profile_path.exists() else {}
    sendable = {r.get("record_id") for r in chosen if r.get("workflow_status") == m.APPROVED and not send_problem(r, suppression)}
    path = write_review_page(chosen, settings.exports_dir / "review_latest.html", "Drafts to review", date.today(), profile.get("email", ""), sendable_ids=sendable)
    print(f"Review page with {len(chosen)} email(s): {path}")
    print("Open it in your browser. Nothing is sent from that page.")
    return 0


def _editor_must_be_closed(settings: Settings) -> None:
    from .review_server import editor_is_open

    if editor_is_open(settings):
        raise UserFacingError(
            "The email editor is still open. Save your changes there, close its window, then run this again "
            "(so that what you do here and your edits cannot overwrite each other)."
        )


def cmd_approve(settings: Settings, args) -> int:
    from .sending import approve
    from .suppression import SuppressionList

    _editor_must_be_closed(settings)
    records = _load(settings)
    try:
        n = approve(records, settings, SuppressionList.load(settings.suppression_path), date.today(), _ids(args.ids))
    finally:
        _save(settings, records)
    print(f"{n} email(s) approved. Next:  python -m src.cli send   (or --method gmail-drafts)")
    return 0


def cmd_send(settings: Settings, args) -> int:
    from .sending import send
    from .suppression import SuppressionList

    _editor_must_be_closed(settings)
    records = _load(settings)
    try:
        report = send(
            records, settings, SuppressionList.load(settings.suppression_path), date.today(), args.method, args.limit,
            _ids(args.ids), save_fn=lambda: _save(settings, records, backup=False),  # quick save after each email
        )
    except BaseException:
        try:
            _save(settings, records)
        except Exception:
            pass  # keep the original error message; the outreach log still records every email sent
        raise
    _save(settings, records)
    if report.sent:
        print(f"Sent (confirmed by Gmail): {', '.join(report.sent)}")
    if report.drafted:
        print(f"Gmail drafts created: {', '.join(report.drafted)}. Send them from Gmail, then run mark-sent.")
    for rid, why in report.skipped:
        print(f"  skipped {rid}: {why}")
    for rid, why in report.failed:
        print(f"  FAILED {rid}: {why} (not marked as sent)")
    return 0 if not report.failed else 1


def cmd_mark_sent(settings: Settings, args) -> int:
    from .sending import mark_sent

    from .suppression import SuppressionList

    _editor_must_be_closed(settings)
    records = _load(settings)
    n = mark_sent(records, _ids(args.ids), settings, date.today(), sent_on=_today(args.date) if args.date else None,
                  suppression=SuppressionList.load(settings.suppression_path))
    _save(settings, records)
    print(f"{n} email(s) recorded as sent. Follow-up reminders were scheduled.")
    return 0


def _simple_status(settings: Settings, args, new_status: str, note: str = "") -> int:
    from .suppression import SuppressionList
    from .tracker import log_event, set_status

    records = _load(settings)
    record = _get(records, args.id)
    set_status(record, new_status, date.today(), settings, note or getattr(args, "note", "") or "")
    if new_status in m.SUPPRESSED_STATUSES:
        suppression = SuppressionList.load(settings.suppression_path)
        suppression.add(record, new_status, date.today(), getattr(args, "note", "") or "")
        suppression.save(settings.suppression_path)
    log_event(settings, record, new_status, getattr(args, "note", "") or "")
    _save(settings, records)
    print(f"{args.id}: status is now '{new_status}'.")
    return 0


def cmd_suppress_email(settings: Settings, args) -> int:
    from .suppression import SuppressionList

    suppression = SuppressionList.load(settings.suppression_path)
    suppression.add({"institutional_email": args.email, "professor_name": args.name or "", "university": args.university or ""}, args.reason, date.today(), args.note or "")
    suppression.save(settings.suppression_path)
    if settings.tracker_path.exists():
        from .storage import load_records

        records = load_records(settings.tracker_path)
        if suppression.apply(records, date.today()):
            _save(settings, records)
    print(f"{args.email} added to the suppression list ({args.reason}). They will never be emailed.")
    return 0


def cmd_followups(settings: Settings, args) -> int:
    from .drafting import build_follow_up
    from .tracker import log_event, refresh_follow_ups

    records = _load(settings)
    today = date.today()
    refresh_follow_ups(records, today, settings)
    due = [r for r in records if r.get("workflow_status") == m.FOLLOW_UP_DUE]
    if not due:
        print("No follow-ups are due.")
        _save(settings, records)
        return 0
    profile = _profile(settings)
    from .tracker import set_status

    for r in due:
        print(f"{r.get('record_id')}: {r.get('professor_name')} ({r.get('university')}) - first email {r.get('last_contact_date')}")
        if args.draft:
            draft = build_follow_up(r, profile, today)
            r["email_subject"], r["email_draft"] = draft.subject, draft.body
            set_status(r, m.DRAFT_READY, today, settings)  # follow-ups need approval like any email
            r["approval_hash"] = ""
            r["next_action"] = "Follow-up drafted: review and approve it (5_approve_drafts.bat), then send it from the outbox."
            log_event(settings, r, "follow_up_drafted", draft.subject)
    _save(settings, records)
    if args.draft:
        print("Follow-up drafts written. Approve them (5_approve_drafts.bat), send them from the outbox, then run mark-sent.")
    else:
        print("Add --draft to write polite follow-up drafts for these.")
    return 0


def cmd_export(settings: Settings, args) -> int:
    from .export import export_all
    from .run_pipeline import load_seed_programs

    records = _load(settings)
    csv_path, xlsx_path = export_all(records, settings.exports_dir, load_seed_programs(settings))
    print(f"Exported:\n  {csv_path}\n  {xlsx_path}")
    return 0


def cmd_programs(settings: Settings, args) -> int:
    from .run_pipeline import load_seed_programs
    from .textutil import find_dates

    programs = load_seed_programs(settings)
    if not programs:
        raise UserFacingError("data/seed/programs.csv not found.")
    today = date.today()
    rows = []
    for p in programs:
        text = f"{p.get('spring_2027_deadline', '')} {p.get('fall_2027_deadline', '')} {p.get('assistantship_deadline', '')}"
        checked = p.get("date_checked", "")
        upcoming = [d for d in find_dates(text) if d >= today and d.isoformat() != checked]  # ignore "checked on <date>" notes
        rows.append((min(upcoming) if upcoming else date.max, p))
    rows.sort(key=lambda t: t[0])
    for when, p in rows[: args.limit]:
        label = when.isoformat() if when != date.max else "date not verified"
        print(f"{label:18s} {p.get('university', '')[:34]:34s} {p.get('program_name', '')[:40]:40s} IELTS {p.get('ielts_min_overall', '?')}")
    print("Always confirm deadlines on the official program page before applying.")
    return 0


def cmd_discover(settings: Settings, args) -> int:
    from .discovery import openalex
    from .http_client import PoliteClient, default_user_agent
    from .storage import assign_missing_ids, load_records

    client = PoliteClient(default_user_agent(settings.contact_email), settings.request_delay_seconds, settings.cache_dir)
    leads, messages = openalex.discover(client, settings.openalex_api_key, date.today(), per_topic=args.per_topic)
    for msg in messages:
        print(msg)
    records = load_records(settings.tracker_path)
    records.extend(leads)
    assign_missing_ids(records)
    from .dedupe import dedupe_records

    result = dedupe_records(records)
    _save(settings, result.records)
    print(f"{len(leads)} lead(s) added as 'discovered'. Each needs an official profile URL and verification before outreach.")
    return 0


def cmd_check_funding(settings: Settings, args) -> int:
    from .discovery import nih_reporter
    from .http_client import PoliteClient, default_user_agent
    from .textutil import clean

    records = _load(settings)
    client = PoliteClient(default_user_agent(settings.contact_email), max(1.0, settings.request_delay_seconds), settings.cache_dir)
    wanted = {i.upper() for i in _ids(args.ids)}
    todo = [r for r in records if (not wanted or r.get("record_id", "").upper() in wanted) and r.get("workflow_status") not in m.SUPPRESSED_STATUSES]
    found = 0
    for r in todo[: args.limit]:
        evidence, message = nih_reporter.check_record(client, r, date.today())
        print(f"  {r.get('record_id')}: {message}")
        if evidence and evidence not in clean(r.get("funding_or_assistantship_evidence")):
            current = clean(r.get("funding_or_assistantship_evidence"))
            r["funding_or_assistantship_evidence"] = evidence if current.lower().startswith("not verified") or not current else f"{current} | {evidence}"
            _add_grant_evidence(r, evidence, date.today())
            found += 1
    _save(settings, records)
    print(f"Added NIH funding evidence to {found} record(s). Re-run the pipeline to update fit scores.")
    return 0


def _add_grant_evidence(record: dict, evidence_text: str, today: date) -> None:
    """An active NIH grant is 'possible' funding evidence (money may exist; it is not a position offer)."""
    import re

    from .checks import CONFIRMED, get_check, load_checks, set_check
    from .page_facts import funding_level

    entry = get_check(load_checks(record), "funding")
    if entry.get("status") == CONFIRMED:
        return
    project = re.search(r"https://reporter\.nih\.gov/project-details/\d+", evidence_text)
    grant = {"url": project.group(0) if project else "https://reporter.nih.gov/", "kind": "active_grant", "quote": evidence_text[:280]}
    evidence = [e for e in entry.get("evidence") or [] if e.get("kind") != "active_grant"] + [grant]
    level = funding_level(evidence)
    detail = entry.get("detail") if level == entry.get("status") else "Active NIH grant found: funds may exist, but it is not a position offer. Ask the professor."
    set_check(record, "funding", level, today, url=entry.get("url") or grant["url"], detail=detail, evidence=evidence)


def cmd_edit(settings: Settings, args) -> int:
    """Open the email editor in your browser (runs only on this computer; nothing is sent from it)."""
    from .review_server import serve

    return serve(settings, open_browser=not args.no_browser, port=args.port)


def cmd_cv(settings: Settings, args) -> int:
    """Set the CV that is attached to every email, and check it."""
    from .cv_check import inspect_cv, set_cv

    if args.set:
        dest = set_cv(settings, args.set)
        print(f"CV set: {dest}")
    profile = _profile(settings) if settings.profile_path.exists() else {}
    report = inspect_cv(settings, profile)
    print(f"CV: {report.summary()}")
    for problem in report.problems:
        print(f"  PROBLEM: {problem}")
    for warning in report.warnings:
        print(f"  check:   {warning}")
    if report.ok_to_attach:
        print("  This file will be attached. Open it once to be sure it is the version you want professors to see.")
    return 0 if report.ok_to_attach else 1


def cmd_preview(settings: Settings, args) -> int:
    """Preview emails for top UNVERIFIED leads without changing anything (nothing can be sent from it)."""
    from .drafting import build_draft
    from .review import write_review_page
    from .scoring import apply_scores
    from .suppression import SuppressionList
    from .validate import contact_discouraged

    records = _load(settings)
    profile = _profile(settings)
    today = date.today()
    apply_scores(records, profile, today)
    suppression = SuppressionList.load(settings.suppression_path)
    pool = [
        r for r in records
        if r.get("workflow_status") in {m.DISCOVERED, m.NEEDS_VERIFICATION, m.VERIFIED}
        and not suppression.is_suppressed(r) and not contact_discouraged(r)
    ]
    pool.sort(key=lambda r: -float(r.get("fit_score") or 0))
    previews = []
    warnings: dict[str, list[str]] = {}
    for r in pool[: args.limit]:
        copy = dict(r)
        draft = build_draft(copy, profile, today)
        copy["email_subject"] = "[PREVIEW - VERIFY FIRST] " + draft.subject
        copy["email_draft"] = draft.body
        copy["workflow_status"] = "preview_only"
        previews.append(copy)
        important = [w for w in draft.warnings if not w.startswith(("Tip:", "No recent publication"))]
        if important:
            warnings[copy.get("record_id", "")] = important
    path = write_review_page(previews, settings.exports_dir / "preview_latest.html", "PREVIEW ONLY - not verified, do not send", today,
                             warnings_by_id=warnings)
    print(f"Preview of {len(previews)} email(s): {path}")
    print("These professors are NOT verified yet. Nothing was saved and nothing can be sent from the preview.")
    print("Next: python -m src.cli verify   (on your own PC), then run the pipeline to create real drafts.")
    return 0


# ----------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m src.cli", description="Professor outreach assistant (drafts only by default; never sends without your approval).")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", metavar="command")

    def add(name, func, help_text):
        sp = sub.add_parser(name, help=help_text, description=help_text)
        sp.set_defaults(func=func)
        return sp

    add("doctor", cmd_doctor, "check that everything is installed and set up")
    sp = add("import-profile", cmd_import_profile, "read your CV/portfolio PDF into private_profile/profile.json")
    sp.add_argument("--file", help="path to your CV PDF (default: first PDF in private_profile/)")
    sp.add_argument("--force", action="store_true", help="overwrite an existing profile.json")
    sp = add("init", cmd_init, "start your tracker from the researched leads (or the sample data)")
    sp.add_argument("--sample", action="store_true", help="use fictional sample data for practice")
    sp.add_argument("--source", help="start from this CSV/XLSX instead")
    sp.add_argument("--force", action="store_true", help="replace an existing tracker (a backup is kept)")
    sp = add("import", cmd_import, "add records from a CSV, XLSX or JSONL file (duplicates are merged)")
    sp.add_argument("--file", required=True)
    sp = add("list", cmd_list, "list records (highest fit first)")
    sp.add_argument("--status", choices=m.WORKFLOW_STATUSES)
    sp.add_argument("--limit", type=int, default=40)
    add("status", cmd_status, "counts by status and upcoming follow-ups")
    sp = add("verify", cmd_verify, "check records on their official university pages (needs internet)")
    sp.add_argument("--ids", help="comma-separated record ids (default: all that need verification)")
    sp.add_argument("--limit", type=int, default=40)
    sp = add("confirm", cmd_confirm, "record a check you did yourself on an official page (profile, research, publication, program, funding)")
    sp.add_argument("--id", required=True)
    sp.add_argument("--check", required=True, choices=["profile", "research", "publication", "program", "funding"])
    sp.add_argument("--source-url", required=True, help="the official page where you checked it")
    sp.add_argument("--note", default="", help="optional: what you saw, e.g. 'research list matches'")
    sp = add("confirm-email", cmd_confirm_email, "record an email you saw yourself on the official page")
    sp.add_argument("--id", required=True)
    sp.add_argument("--email", required=True)
    sp.add_argument("--source-url", required=True, help="the official page where the email is shown")
    sp = add("set", cmd_set, "change one field of one record (safer than editing tracker.csv in Excel)")
    sp.add_argument("--id", required=True)
    sp.add_argument("--field", required=True, help="e.g. research_interests, title, faculty_profile_url, personal_note")
    sp.add_argument("--value", required=True, help='the new text in quotes, or "" to clear it')
    sp = add("note", cmd_note, "add a dated note to a record")
    sp.add_argument("--id", required=True)
    sp.add_argument("--text", required=True)
    sp = add("validate", cmd_validate, "check all records for missing or suspicious data")
    sp.add_argument("--all", action="store_true", help="also show warnings")
    sp = add("dedupe", cmd_dedupe, "find and merge duplicate records")
    sp.add_argument("--dry-run", action="store_true")
    add("score", cmd_score, "recalculate fit scores with explanations")
    sp = add("draft", cmd_draft, "write email drafts for verified records")
    sp.add_argument("--ids")
    sp.add_argument("--limit", type=int, default=30)
    sp.add_argument("--force", action="store_true", help="rewrite existing drafts (clears approval)")
    sp.add_argument("--discard-edits", action="store_true", help="also rewrite emails you edited by hand (your edits are lost)")
    add("review", cmd_review, "make the HTML review page (exports/review_latest.html)")
    sp = add("edit", cmd_edit, "open the email editor in your browser: change recipient, subject and text, saved to your tracker")
    sp.add_argument("--port", type=int, default=0, help=argparse.SUPPRESS)
    sp.add_argument("--no-browser", action="store_true", help="do not open the browser (print the link instead)")
    sp = add("cv", cmd_cv, "check the CV attached to your emails (use --set to choose the file)")
    sp.add_argument("--set", metavar="PDF", help="path to your CV PDF; it is copied into private_profile\\cv")
    sp = add("preview", cmd_preview, "preview emails for the best UNVERIFIED leads (read-only; nothing is saved or sent)")
    sp.add_argument("--limit", type=int, default=20)
    sp = add("approve", cmd_approve, "read each draft and approve it by typing 'yes'")
    sp.add_argument("--ids")
    sp = add("send", cmd_send, "send approved emails (manual outbox by default; never automatic)")
    sp.add_argument("--method", default="manual", choices=["manual", "gmail-drafts", "gmail-api"])
    sp.add_argument("--limit", type=int)
    sp.add_argument("--ids")
    sp = add("mark-sent", cmd_mark_sent, "record emails you sent yourself")
    sp.add_argument("--ids", required=True)
    sp.add_argument("--date", help=DATE_HELP)
    for name, status, text in (
        ("mark-replied", m.REPLIED, "record that a professor replied"),
        ("mark-bounced", m.BOUNCED, "record a bounced email (adds to suppression list)"),
        ("opt-out", m.OPTED_OUT, "the professor asked not to be contacted (adds to suppression list)"),
        ("do-not-contact", m.DO_NOT_CONTACT, "never contact this person (adds to suppression list)"),
        ("close", m.CLOSED, "close a record (no further action)"),
        ("not-a-fit", m.NOT_A_FIT, "mark a record as not a fit"),
    ):
        sp = add(name, lambda s, a, _st=status: _simple_status(s, a, _st), text)
        sp.add_argument("--id", required=True)
        sp.add_argument("--note", default="")
    sp = add("suppress-email", cmd_suppress_email, "add any email address to the suppression list")
    sp.add_argument("--email", required=True)
    sp.add_argument("--reason", default=m.DO_NOT_CONTACT, choices=sorted([m.OPTED_OUT, m.BOUNCED, m.DO_NOT_CONTACT]))
    sp.add_argument("--name")
    sp.add_argument("--university")
    sp.add_argument("--note")
    sp = add("followups", cmd_followups, "list follow-ups that are due (add --draft to write them)")
    sp.add_argument("--draft", action="store_true")
    add("export", cmd_export, "export the tracker to dated CSV and Excel files")
    sp = add("programs", cmd_programs, "list researched programs by next deadline")
    sp.add_argument("--limit", type=int, default=60)
    sp = add("discover", cmd_discover, "find new leads from recent papers with OpenAlex (needs OPENALEX_API_KEY)")
    sp.add_argument("--per-topic", type=int, default=50)
    sp = add("check-funding", cmd_check_funding, "look for active NIH grants for professors (funding evidence)")
    sp.add_argument("--ids")
    sp.add_argument("--limit", type=int, default=30)
    return p


def _safe_console() -> None:
    """Never crash on names with unusual letters when the Windows console uses an old code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _safe_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    settings = load_settings()
    _STAMPS.clear()
    try:
        return int(args.func(settings, args) or 0)
    except UserFacingError as exc:
        print(f"\nProblem: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped. Your tracker was saved where possible.")
        return 130
    except Exception:  # unexpected bug: save details for troubleshooting, show a short message
        try:
            settings.log_dir.mkdir(parents=True, exist_ok=True)
            log = settings.log_dir / f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            log.write_text(traceback.format_exc(), encoding="utf-8")
            where = f" Details were saved to {log}."
        except OSError:
            where = ""
        print(f"\nSomething went wrong (this is a bug, not your fault).{where} Your tracker backups are in workspace/backups.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
