"""One-click pipeline: load -> (optional verify/discover) -> validate -> suppress -> dedupe -> score -> draft -> export -> review page.

It NEVER sends email. Sending is a separate, human-approved step (python -m src.cli approve / send).

Example (Windows, from the project folder):
    .venv\\Scripts\\python -m src.run_pipeline --intake "Spring 2027" --limit 30 --mode drafts
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import models as m
from .config import Settings, load_settings
from .dedupe import dedupe_records
from .drafting import apply_draft, build_draft, can_draft
from .errors import UserFacingError
from .export import export_all
from .profile import find_profile_source, import_profile, load_profile
from .review import write_review_page
from .scoring import apply_scores
from .storage import assign_missing_ids, load_records, read_any, save_records
from .suppression import SuppressionList
from .textutil import clean, find_dates
from .tracker import log_event, reconcile_with_log, refresh_follow_ups
from .validate import has_errors, issues_by_record, summarize_issues, validate_all


@dataclass
class PipelineReport:
    total: int = 0
    imported: int = 0
    merged: int = 0
    possible_duplicates: int = 0
    suppressed: int = 0
    verified_now: int = 0
    discovered: int = 0
    drafted: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    follow_ups_due: list[str] = field(default_factory=list)
    issues_summary: str = ""
    errors_by_record: dict = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)


def _intake_rank(record: dict, intake: str, today: date) -> int:
    """Lower is earlier in the queue: open intakes first, the requested intake before the other."""
    from .scoring import _intake_available

    spring = _intake_available(record.get("spring_2027_status", ""), today, "spring")
    fall = _intake_available(record.get("fall_2027_status", ""), today, "fall")
    wanted = intake.lower()
    if "spring" in wanted and spring:
        return 0
    if "fall" in wanted and fall:
        return 0
    if wanted in {"both", "any", "spring 2027 and fall 2027"} and (spring or fall):
        return 0
    if spring is None and fall is None:
        return 1
    return 2 if (spring or fall) else 3


def _deadline_key(record: dict, today: date):
    dates = [d for d in find_dates(" ".join(clean(record.get(f, "")) for f in ("spring_2027_status", "fall_2027_status", "application_deadline"))) if d >= today]
    return min(dates) if dates else date.max


def load_seed_programs(settings: Settings) -> list[dict]:
    path = settings.seed_dir / "programs.csv"
    if not path.exists():
        return []
    from .storage import read_csv_rows

    rows, _ = read_csv_rows(path)
    return rows


def run(
    settings: Settings,
    intake: str = "both",
    limit: int = 30,
    mode: str = "drafts",
    input_file: Path | None = None,
    verify_live: bool = False,
    verify_limit: int = 40,
    discover: bool = False,
    today: date | None = None,
    client=None,
    print_fn=print,
) -> PipelineReport:
    today = today or date.today()
    report = PipelineReport()
    if mode not in {"drafts", "report"}:
        raise UserFacingError(
            "The one-click pipeline never sends email. Use --mode drafts (default) or --mode report. "
            "To send, approve drafts and use: python -m src.cli send"
        )
    settings.ensure_folders()
    for warning in settings.warnings:
        report.messages.append("Settings: " + warning)

    # 1. profile
    if not settings.profile_path.exists():
        source = find_profile_source(settings.private_dir, settings.root)
        if source is None:
            raise UserFacingError(
                "No profile found. Put your CV/portfolio PDF in the 'private_profile' folder and run "
                "python -m src.cli import-profile"
            )
        import_profile(source, settings.profile_path, today)
        report.messages.append(f"Imported your profile from {source.name}. Please review private_profile/profile.json.")
    profile = load_profile(settings.profile_path)
    try:
        applicant_ielts = float((profile.get("english_test") or {}).get("overall"))
    except (TypeError, ValueError):
        applicant_ielts = None

    # 2. tracker (+ optional import)
    records = load_records(settings.tracker_path)
    if not records and not input_file:
        seed = settings.seed_dir / "professors_leads.csv"
        if seed.exists():
            input_file = seed
            report.messages.append(f"Started your tracker from the researched leads in {seed.relative_to(settings.root)}.")
    if input_file:
        from .sending import reset_approval_for_import

        new = read_any(Path(input_file))
        for r in new:
            if not clean(r.get("record_source")):
                r["record_source"] = Path(input_file).name
            reset_approval_for_import(r)
        records.extend(new)
        report.imported = len(new)
    assign_missing_ids(records)

    # 3. optional live steps (need internet on your PC)
    if verify_live or discover:
        from .http_client import PoliteClient, default_user_agent

        client = client or PoliteClient(default_user_agent(settings.contact_email), settings.request_delay_seconds, settings.cache_dir)
    if discover:
        from .discovery import openalex

        try:
            leads, messages = openalex.discover(client, settings.openalex_api_key, today)
            records.extend(leads)
            assign_missing_ids(records)
            report.discovered = len(leads)
            report.messages.extend(messages)
        except UserFacingError as exc:
            report.messages.append(f"Discovery skipped: {exc}")
    if verify_live:
        from .verify import verify_record

        try:
            applicant_ielts = float((profile.get("english_test") or {}).get("overall"))
        except (TypeError, ValueError):
            applicant_ielts = None
        from .checks import checked_under_earlier_rules

        todo = [r for r in records if checked_under_earlier_rules(r)]  # marked verified under the earlier rules: first
        todo += [r for r in records if clean(r.get("workflow_status")) in {m.DISCOVERED, m.NEEDS_VERIFICATION}]
        for r in todo[:verify_limit]:
            outcome = verify_record(r, client, today, evidence_dir=settings.evidence_dir, applicant_ielts=applicant_ielts,
                                    old_drafts_dir=settings.old_drafts_dir)
            if outcome.status == m.VER_VERIFIED:
                report.verified_now += 1
            print_fn(f"  verify {outcome.record_id}: {outcome.status} - {' '.join(outcome.messages)[:160]}")
            if outcome.email_refresh:
                print_fn(f"      {outcome.email_refresh}")
                log_event(settings, r, "email_rechecked", outcome.email_refresh)

    # 4. suppression, follow-ups
    suppression = SuppressionList.load(settings.suppression_path)
    report.suppressed = suppression.apply(records, today)
    for rid in reconcile_with_log(records, settings):
        report.messages.append(f"{rid}: the outreach log shows this email was sent; status restored to 'sent'.")
    report.follow_ups_due = refresh_follow_ups(records, today, settings)

    # 5. dedupe
    result = dedupe_records(records)
    records = result.records
    report.merged = sum(len(g.merged_ids) for g in result.merges)
    report.possible_duplicates = len(result.possible)

    # 6. score
    apply_scores(records, profile, today)

    # 7. validate
    issues = validate_all(records, today, suppression.email_set, applicant_ielts)
    report.issues_summary = summarize_issues(issues)
    grouped = issues_by_record(issues)
    report.errors_by_record = {rid: [i.message for i in items if i.severity == "error"] for rid, items in grouped.items()}

    # 8. drafts
    if mode == "drafts":
        candidates = [r for r in records if clean(r.get("workflow_status")) == m.VERIFIED]
        candidates.sort(key=lambda r: (_intake_rank(r, intake, today), -int(float(clean(r.get("fit_score")) or 0)), _deadline_key(r, today)))
        for r in candidates:
            if len(report.drafted) >= limit:
                break
            rid = clean(r.get("record_id"))
            ok, reason = can_draft(r, today, settings.min_fit_for_draft, suppression.is_suppressed(r))
            if ok and has_errors(issues, rid):
                ok, reason = False, "has validation errors: " + "; ".join(report.errors_by_record.get(rid, [])[:2])
            if not ok:
                report.skipped.append((rid, reason))
                continue
            draft = build_draft(r, profile, today)
            apply_draft(r, draft, today)
            report.drafted.append(rid)
            log_event(settings, r, "draft_created", f"subject={draft.subject}; evidence={','.join(draft.evidence_ids)}")
        not_ready = [r for r in records if clean(r.get("workflow_status")) in {m.DISCOVERED, m.NEEDS_VERIFICATION}]
        if not_ready:
            report.messages.append(
                f"{len(not_ready)} record(s) still need verification before drafting. On your PC run: python -m src.cli verify"
            )

    # 9. save + export
    report.total = len(records)
    save_records(settings.tracker_path, records, settings.backup_dir)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    csv_path, xlsx_path = export_all(records, settings.exports_dir, load_seed_programs(settings), stamp)
    report.files += [csv_path, xlsx_path]
    review_records = [r for r in records if clean(r.get("workflow_status")) in {m.DRAFT_READY, m.APPROVED}]
    review_records.sort(key=lambda r: -int(float(clean(r.get("fit_score")) or 0)))
    warnings_by_id = {rid: [i.message for i in items if i.severity == "warning"][:4] for rid, items in grouped.items()}
    review_path = write_review_page(
        review_records,
        settings.exports_dir / f"review_{stamp}.html",
        f"Drafts to review ({intake})",
        today,
        sender_account=clean(profile.get("email")),
        warnings_by_id=warnings_by_id,
    )
    latest = settings.exports_dir / "review_latest.html"
    latest.write_text(review_path.read_text(encoding="utf-8"), encoding="utf-8")
    report.files += [review_path, latest]
    run_report = write_run_report(report, settings, today, stamp, intake)
    report.files.append(run_report)
    return report


def write_run_report(report: PipelineReport, settings: Settings, today: date, stamp: str, intake: str) -> Path:
    lines = [
        f"# Pipeline run {stamp}",
        "",
        f"- Intake focus: {intake}",
        f"- Records in tracker: {report.total} (imported this run: {report.imported}, discovered: {report.discovered})",
        f"- Verified on official pages this run: {report.verified_now}",
        f"- Duplicates merged: {report.merged}; possible duplicates flagged for you: {report.possible_duplicates}",
        f"- Suppressed (opt-out/bounce/do-not-contact) records updated: {report.suppressed}",
        f"- Follow-ups now due: {len(report.follow_ups_due)} {', '.join(report.follow_ups_due)}",
        f"- New drafts: {len(report.drafted)} {', '.join(report.drafted)}",
        f"- Validation: {report.issues_summary}",
        "",
        "Nothing was sent. Check and edit the drafts in the editor (edit_drafts.bat), then approve them with 5_approve_drafts.bat.",
        "",
        "## Records needing manual review",
    ]
    for rid, errors in sorted(report.errors_by_record.items()):
        if errors:
            lines.append(f"- {rid}: " + "; ".join(errors))
    if report.skipped:
        lines += ["", "## Not drafted (and why)"]
        for rid, why in report.skipped[:200]:
            lines.append(f"- {rid}: {why}")
    if report.messages:
        lines += ["", "## Messages"] + [f"- {msg}" for msg in report.messages]
    path = settings.exports_dir / f"run_report_{stamp}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def print_summary(report: PipelineReport, print_fn=print) -> None:
    print_fn("")
    print_fn("=== Pipeline finished (no emails were sent) ===")
    print_fn(f"Records in tracker:      {report.total}")
    print_fn(f"Imported this run:       {report.imported}")
    if report.discovered:
        print_fn(f"Discovered (leads):      {report.discovered}")
    if report.verified_now:
        print_fn(f"Verified this run:       {report.verified_now}")
    print_fn(f"Duplicates merged:       {report.merged} (possible duplicates flagged: {report.possible_duplicates})")
    print_fn(f"New drafts:              {len(report.drafted)}")
    print_fn(f"Follow-ups due:          {len(report.follow_ups_due)}")
    print_fn(f"Validation:              {report.issues_summary}")
    for msg in report.messages:
        print_fn("Note: " + msg)
    print_fn("Files:")
    for path in report.files:
        print_fn(f"  {path}")
    print_fn("Next: check and edit each email in the editor (edit_drafts.bat; 4_run_pipeline.bat opens it for you), "
             "then approve them with 5_approve_drafts.bat.")


def _safe_console() -> None:
    """Never crash on names with unusual letters when the Windows console uses an old code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _safe_console()
    parser = argparse.ArgumentParser(
        prog="python -m src.run_pipeline",
        description="One-click run: validate, deduplicate, score and draft emails. Never sends email.",
    )
    parser.add_argument("--intake", default="both", help='"Spring 2027", "Fall 2027" or "both" (default: both)')
    parser.add_argument("--limit", type=int, default=30, help="maximum new drafts this run (default 30)")
    parser.add_argument("--mode", default="drafts", choices=["drafts", "report"], help="drafts (default) or report (no drafts)")
    parser.add_argument("--input", type=Path, help="CSV/XLSX/JSONL file of professor records to add first")
    parser.add_argument("--verify-live", action="store_true", help="open official pages to verify records (needs internet)")
    parser.add_argument("--verify-limit", type=int, default=40, help="maximum records to verify per run")
    parser.add_argument("--discover", action="store_true", help="find new leads with OpenAlex (needs OPENALEX_API_KEY)")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        report = run(settings, args.intake, args.limit, args.mode, args.input, args.verify_live, args.verify_limit, args.discover)
        print_summary(report)
        return 0
    except UserFacingError as exc:
        print(f"\nProblem: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
