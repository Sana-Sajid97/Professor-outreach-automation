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
4. Double-click **`choose_cv.bat`** and pick the CV that is attached to every email (a 2-page PDF is best), or drag the PDF onto `choose_cv.bat`. It is checked straight away.
5. Double-click **`3_verify_professors.bat`**. For each professor it checks, on official pages: the profile, the email, the research the email will describe, the papers it may mention, the program page (degree, Spring/Fall 2027, deadlines, IELTS) and assistantship funding. Professors verified with the earlier version are checked again first, and their emails are rewritten from the checked facts (the old text is kept in `workspace\old_drafts\`).
6. Double-click **`4_run_pipeline.bat`**. It scores and drafts, then opens the **email editor** in your browser: read every email with its checks and evidence, edit the recipient, subject or text, and press **Save**. **It never sends.**
7. Press **I'm done editing** at the top of the editor, then double-click **`5_approve_drafts.bat`**. Type `yes` for each email you approve (emails with failed checks need `approve anyway`), then send each one from Gmail yourself with your CV attached.
8. Record what you sent: `outreach mark-sent --ids R0012,R0015`.

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
- **Verification you can see**: every professor gets separate checks (profile, email, research, paper, program page, funding), each with its official link, date and a quote from the page, and a status: passed, confirmed by you, needs a look, failed, or not checked yet. A professor counts as **verified only when the profile, email and research checks pass** (automatically, or confirmed by you with the official link); a profile that exists, or a draft that was generated, is never enough. Program facts that cannot be found on the official page are flagged, not assumed, and funding is graded **confirmed** (an official page guarantees funding or a professor is recruiting a funded student), **possible** (general statements or an active grant) or **not verified**.
- Personalised drafts built **only** from what the checks support: the email describes only research phrases found on the official page, and mentions a paper only when Crossref or PubMed confirms the paper and that the professor is an author (or you confirmed these yourself). Your own CV sentences describe you. At most one polite follow-up, which must be approved like any email.
- **An email editor** (`edit_drafts.bat`, also opened by the pipeline): change the recipient, subject and text in your browser; saved to your tracker and kept, and the review page (`exports\review_latest.html`) is updated to match. Changing the recipient needs the official page where you saw it; editing an approved email cancels its approval; new claims about the professor are compared with the saved official page and flagged.
- **CV checks**: the CV must be a readable PDF containing your name; long files, big files and informal file names are flagged. Approval records which CV file you approved, sending stops if it changed, and Gmail drafts are read back to confirm the CV is attached.
- Statuses: discovered, needs_verification, verified, draft_ready, approved, sent, follow_up_due, replied, closed, not_a_fit, bounced, opted_out, do_not_contact. Opt-outs and bounces are **suppressed forever**.
- Safe sending: approval of the exact text, a daily limit (default 30), and Gmail API sending **off by default**. Send buttons appear only on the outbox page, only for approved emails that pass every check.
- No double sends: every send is written to the outreach log at once. An email with the same address and subject is never sent twice, and if the tracker could not be saved after a send, the next run restores the record to `sent` from the log.
- Safe editing without Excel: `outreach set --id R0012 --field research_interests --value "..."` and `outreach note --id R0012 --text "..."`. If the tracker was re-saved in Excel, readable dates (21/10/2026) are repaired on load, and ambiguous ones are flagged.
- **211 automated tests** (`python -m pytest`), including the editor running as a real local server, the CV checks, every verification check on sample pages, regression tests for every issue found in an independent code review, and checks of the drafts written for all 186 researched leads.

## What needs your PC or credentials (not tested live yet)
- `verify` (official pages, plus the free Crossref and PubMed APIs for papers), `discover` (OpenAlex; needs a free API key) and `check-funding` (NIH RePORTER) need internet on your PC. The cloud environment where this was built blocks outside websites, so they were tested only with sample pages and sample API answers. Reading program and funding facts from real university pages is heuristic: always read the quoted evidence before relying on it.
- Gmail drafts/sending need a one-time Google setup ([docs/GMAIL_SETUP.md](docs/GMAIL_SETUP.md)). They have not been tested with a real account; test on yourself first.
- There is **no automatic web search** in the tool. The leads came from a one-time research run (see `data/research/README.md`). Add more with `discover` or by importing your own spreadsheet.

## Privacy
- `private_profile/` (CV, profile, Gmail token), `workspace/` (tracker, outreach log) and `exports/` are **never** uploaded to GitHub (see `.gitignore`).

## Original project files
`CLAUDE.md`, `prompt.md`, `ONE_CLICK_SPEC.md`, `WORKFLOW.md`, `SAFETY_AND_PRIVACY.md` and `professors_template.csv` are the original specification and are followed by the code. The tracker uses the template's columns, plus a few extra columns at the end (publication years, matched topics, score breakdown, email verification method, personal note, follow-up date and count, approval fingerprint, duplicate flag and record source).
