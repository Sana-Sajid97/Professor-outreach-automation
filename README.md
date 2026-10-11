# Professor Outreach Assistant (US graduate nutrition, 2027)

A beginner-friendly tool, built for Sana Sajid, that helps find **assistantship-funded** MS/PhD positions in nutrition at US universities. It researches and verifies professors, explains how well each one fits, drafts personalised emails, and tracks every contact. **You stay in control: it never sends an email without your explicit approval.**

> **Goal (updated Oct 2026):** a fully funded position through a research, graduate or teaching assistantship, for **Spring 2027 or Fall 2027**, at **any US university in any state**. External scholarships are out of scope.

## What's inside
| | |
|---|---|
| `data/seed/professors_leads.csv` | **186 researched professor leads** (48 states plus DC), with official profile links, research interests, recent papers, and program and funding facts. All are marked **needs_verification**. |
| `data/seed/programs.csv` | **167 nutrition graduate programs**: Spring/Fall 2027 deadlines, IELTS minimums, assistantship and funding evidence, with source links |
| `docs/STRATEGY_2027.md` | **Start here.** Which programs fully fund international students, deadlines in order, and what to do this week |
| `docs/PROFILE_REVIEW.md` | A candid review of Sana's profile from a professor's point of view, with a prioritised improvement plan |
| `MORNING_QUEUE.md` | Decisions that need a human (privacy, GitHub access, English test, and more) |
| `src/` | The software (Python) |

## Quick start (Windows)
1. Install Python from python.org (tick **Add python.exe to PATH**).
2. Double-click **`1_setup_windows.bat`**.
3. Put your CV/portfolio PDF in **`private_profile\`**, then double-click **`2_import_profile.bat`**.
4. Double-click **`3_verify_professors.bat`**. It checks professors on their official university pages.
5. Double-click **`4_run_pipeline.bat`**. It scores and drafts, then opens the review page. **It never sends.**
6. Double-click **`5_approve_drafts.bat`**. Type `yes` for each email you approve, then send each one from Gmail yourself using the **Open in Gmail** button.
7. Record what you sent: `outreach mark-sent --ids R0012,R0015`.

Full guides:
- [docs/WINDOWS_SETUP.md](docs/WINDOWS_SETUP.md): setup and troubleshooting
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md): the daily workflow
- [docs/EMAIL_GUIDE.md](docs/EMAIL_GUIDE.md): how drafts are written and best practice
- [docs/CREDENTIALS_AND_LIMITS.md](docs/CREDENTIALS_AND_LIMITS.md): what needs keys, and the honest status of each feature
- [docs/GMAIL_SETUP.md](docs/GMAIL_SETUP.md): optional Gmail drafts

The one-click command (also available on macOS/Linux):
```
python -m src.run_pipeline --intake "Spring 2027" --limit 30 --mode drafts
```

## What works today (tested)
- Reading the CV/portfolio PDF into a private `profile.json`. It extracts name, degree, CGPA, IELTS, skills and experience sentences, and never adds achievements.
- The tracker (CSV, opens in Excel), with backups, dated CSV/XLSX exports and an HTML review page.
- Validation of names, URLs, institutional emails, official (.edu) domains, stale dates, placeholders, IELTS requirements, and "do not contact" department policies.
- Duplicate detection by institutional email, profile URL, and name + university, keeping outreach history.
- A transparent **0–10 fit score**, where every point is explained (topic 0–3, background 0–2, program 0–2, funding 0–2, recent paper 0–1). It is a prioritisation aid, **not an admission probability**.
- Personalised drafts built **only** from the record's own fields (research interests and publications, each with a source link to confirm on the official profile) and your own CV sentences. Nothing else is added. At most one polite follow-up, which must be approved like any email.
- Statuses: discovered, needs_verification, verified, draft_ready, approved, sent, follow_up_due, replied, closed, not_a_fit, bounced, opted_out, do_not_contact. Opt-outs and bounces are **suppressed forever**.
- Safe sending: approval of the exact text, a daily limit (default 30), and Gmail API sending **off by default**. Send buttons appear only on the outbox page, only for approved emails that pass every check.
- No double sends: every send is written to the outreach log at once. An email with the same address and subject is never sent twice, and if the tracker could not be saved after a send, the next run restores the record to `sent` from the log.
- Safe editing without Excel: `outreach set --id R0012 --field research_interests --value "..."` and `outreach note --id R0012 --text "..."`. If the tracker was re-saved in Excel, readable dates (21/10/2026) are repaired on load, and ambiguous ones are flagged.
- **165 automated tests** (`python -m pytest`), including regression tests for every issue found in an independent code review and checks of the drafts written for all 186 researched leads.

## What needs your PC or credentials (not tested live yet)
- `verify` (official-page checks), `discover` (OpenAlex; needs a free API key) and `check-funding` (NIH RePORTER) need internet on your PC. The cloud environment where this was built blocks outside websites, so they were tested only with sample data.
- Gmail drafts/sending need a one-time Google setup ([docs/GMAIL_SETUP.md](docs/GMAIL_SETUP.md)). They have not been tested with a real account; test on yourself first.
- There is **no automatic web search** in the tool. The leads came from a one-time research run (see `data/research/README.md`). Add more with `discover` or by importing your own spreadsheet.

## Privacy
- `private_profile/` (CV, profile, Gmail token), `workspace/` (tracker, outreach log) and `exports/` are **never** uploaded to GitHub (see `.gitignore`).
- **This repository is currently public and contains the portfolio PDF, including a phone number and transcript.** Making the repository private, or removing the PDF, is recommended (see `MORNING_QUEUE.md`).

## Original project files
`CLAUDE.md`, `prompt.md`, `ONE_CLICK_SPEC.md`, `WORKFLOW.md`, `SAFETY_AND_PRIVACY.md` and `professors_template.csv` are the original specification and are followed by the code. The tracker uses the template's columns, plus a few extra columns at the end (publication years, matched topics, score breakdown, email verification method, personal note, follow-up date and count, approval fingerprint, duplicate flag and record source).
