# User guide: from researched leads to replies

```
 researched leads ──► verify on official pages ──► score & draft ──► YOU review ──► YOU approve ──► YOU send ──► track replies / follow up
 (data/seed)          (3_verify_professors.bat)     (4_run_pipeline)   (review page)   (5_approve)     (Gmail)      (outreach mark-…)
```

## Statuses
| Status | Meaning |
|---|---|
| `discovered` | A lead was found (for example by OpenAlex). Nothing is checked yet. |
| `needs_verification` | Researched, but the official page and email are not yet confirmed. **All researched leads start here.** |
| `verified` | The official profile and institutional email are confirmed on an official page, or you confirmed them yourself. |
| `draft_ready` | An email draft exists and is waiting for your review. |
| `approved` | You approved the exact text (any later edit cancels the approval). |
| `sent` | You sent it, or Gmail confirmed sending. A follow-up date is set. |
| `follow_up_due` | No reply after the follow-up period (default 10 days). One polite follow-up is allowed. |
| `replied` / `closed` | They answered, or the conversation is finished. |
| `not_a_fit` | You decided not to contact them. |
| `bounced`, `opted_out`, `do_not_contact` | **Suppressed for good.** These people are added to `workspace\suppression_list.csv` and the tool will never draft or send to them again, even if they are imported again later. |

## A good weekly rhythm (about 30–60 minutes a day)
1. **Verify** about 40 leads (`3_verify_professors.bat`). For leads it could not confirm, open the link, find the email, then use `outreach confirm-email …`.
2. **Run the pipeline** (`4_run_pipeline.bat`). The review page opens in your browser.
3. **Review each draft properly:**
   - Click the profile link. Check the name, title and email.
   - Read the **abstract** of the paper the email mentions. If you have something genuine to say about it, add it as one sentence with `outreach set --id R0012 --field personal_note --value "Your sentence."`, then run `outreach draft --ids R0012 --force`.
   - Check that the research topic named in the email matches the official profile. If the recorded interests are wrong, fix them with `outreach set --id R0012 --field research_interests --value "..."` and redraft.
   - Check that the program and intake (Spring or Fall 2027) are right.
4. **Approve** (`5_approve_drafts.bat`). Type `yes` only for emails you would sign your name to.
5. **Send from Gmail.** Use the **Open in Gmail** button on the outbox page, **attach your CV PDF**, and press Send. Then record it: `outreach mark-sent --ids R0012,R0015`.
6. **Replies:** `outreach mark-replied --id R0012 --note "Wants a call on Friday"`. Reply personally and quickly (within 24 hours).
7. **Follow-ups:** `outreach followups --draft` writes one short, polite follow-up for anyone with no reply after 10 days. It goes back to `draft_ready`, so approve it (`5_approve_drafts.bat`), send it from the outbox, then `outreach mark-sent --ids …`. There is never a second follow-up.
8. **No or opt-out:** `outreach opt-out --id R0020`. They are never contacted again.

## The fit score (0–10)
The score helps you decide **who to email first**. It is **not** a prediction of admission. Every point is explained in the `fit_score_breakdown` column:

| Part | Points | How it's decided |
|---|---|---|
| Topic match | 0–3 | Their recorded research interests and papers, compared with your interests (keywords shown) |
| Your background | 0–2 | Whether your CV has direct or some experience in their topics |
| Program fit | 0–2 | A 2027 intake is open, and the program's IELTS minimum is at or below your score |
| Funding / recruiting | 0–2 | A recruiting statement, plus assistantship or grant evidence |
| Recent paper | 0–1 | A relevant paper from the last 3 years |

Missing evidence earns 0 points; nothing is guessed. A high score with **low confidence** means "promising, but check the facts".

## Spreadsheet exports
`exports\professors_<date>.xlsx` has these sheets: **Summary** (best first), **All fields**, **Drafts**, **Programs** (deadlines, IELTS, funding) and **Status counts**. These are snapshots for viewing: changes typed into them are **not** read back. The live data is `workspace\tracker.csv`.

## Changing a record safely
- Change one field: `outreach set --id R0012 --field research_interests --value "maternal nutrition; food insecurity"`. Run `outreach set --id R0012 --field x --value y` with a wrong field name to see the list of fields you can change. Emails are changed only with `outreach confirm-email`, and statuses only with the status commands (`mark-sent`, `not-a-fit`, `close` and so on).
- Add a dated note: `outreach note --id R0012 --text "Met her at a webinar on 3 Nov"`.
- **Do not edit and re-save `workspace\tracker.csv` in Excel.** Excel can rewrite dates (2026-10-21 becomes 21/10/2026), the text encoding and long numbers. The tool repairs dates it can read safely when it loads the file. Ambiguous ones such as 05/06/2026 are flagged by `outreach validate` for you to fix. If something goes wrong, the last 30 versions are in `workspace\backups`.

## Adding professors yourself
Add rows to a CSV or Excel file that uses the column names from `professors_template.csv`, then run `outreach import --file my_new_profs.xlsx`. Duplicates (same email, same profile URL, or same name and university) are merged automatically. Fill in at least `professor_name`, `university`, `faculty_profile_url` and `research_interests`, plus sources.

## Finding more leads (optional)
- `outreach discover`: finds senior authors of recent US papers on your topics, using the **OpenAlex** API. It needs a free API key in `.env` (`OPENALEX_API_KEY`). Leads arrive as `discovered` and must be verified like any other.
- `outreach check-funding`: looks up **active NIH grants** for your professors (NIH RePORTER; no key needed) and adds them as funding evidence.

Both run on your own PC and need internet. They were built from the official API documentation and tested with sample responses; run them once with a small `--limit` to confirm they work for you.

## Practice safely
`outreach init --sample --force` loads **fictional** sample data (domains end in `.example`, which can never receive email). Afterwards, `outreach init --force` starts again from the real leads. A backup of your tracker is kept either way.
