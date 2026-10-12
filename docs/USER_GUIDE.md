# User guide: from researched leads to replies

```
 researched leads ──► verify on official pages ──► score & draft ──► YOU check & edit ──► YOU approve ──► YOU send ──► track replies / follow up
 (data/seed)          (3_verify_professors.bat)     (4_run_pipeline)   (email editor)        (5_approve)     (Gmail)      (outreach mark-…)
```

## Statuses
| Status | Meaning |
|---|---|
| `discovered` | A lead was found (for example by OpenAlex). Nothing is checked yet. |
| `needs_verification` | Researched, but the official page and email are not yet confirmed. **All researched leads start here.** |
| `verified` | Three checks have passed: the **official profile** names the professor, the **institutional email** is published on an official page, and the **research** the email will describe appears on the official profile. Each can also be "confirmed by you" with an official link. A profile that exists, or a draft that was generated, is never enough. |
| `draft_ready` | An email draft exists and is waiting for your review. |
| `approved` | You approved the exact text (any later edit cancels the approval). |
| `sent` | You sent it, or Gmail confirmed sending. A follow-up date is set. |
| `follow_up_due` | No reply after the follow-up period (default 10 days). One polite follow-up is allowed. |
| `replied` / `closed` | They answered, or the conversation is finished. |
| `not_a_fit` | You decided not to contact them. |
| `bounced`, `opted_out`, `do_not_contact` | **Suppressed for good.** These people are added to `workspace\suppression_list.csv` and the tool will never draft or send to them again, even if they are imported again later. |

## The checks behind every email
Each professor has separate checks. The editor, the review page and the approval screen all show them, each with the official link, the date and a quote from the page.

| Check | What it looks at | Passed means |
|---|---|---|
| Official profile | The professor's university page | The page opens and names them (an "Emeritus" mention is flagged) |
| Institutional email | Official pages | The exact address is written on the page (or you confirmed it with the page link) |
| Research | The official profile and lab page | The research phrases the email will use appear there. Phrases that do not are **left out of the email** and listed as "not found" |
| Paper | Crossref or PubMed (free official APIs) | The link is this paper and the professor is an author. Only a checked paper is mentioned in an email |
| Program | The official program page | Degree, Spring/Fall entry, deadlines, IELTS minimum and requirements, each with its quote. Anything not on the page is flagged "not stated". A conflict with your research notes (for example "no Spring entry") is marked **failed** |
| Funding | Profile, lab and program pages (plus NIH grants) | Graded: **confirmed** (the program guarantees an assistantship, or the professor says they are recruiting a funded student), **possible** (general statements or an active grant: ask), **not verified**, or **not available** |

Status words: **passed** (checked automatically), **confirmed by you** (you checked it and gave the official link), **needs a look**, **FAILED**, **not checked yet**. Earlier research notes from search results are always labelled "not checked on an official page".

### Emails written with the earlier version
The earlier version marked a professor verified when the email check alone passed. Run `3_verify_professors.bat` once after updating: it checks those professors again first, with every check above.
- An email the tool wrote is set aside, and `4_run_pipeline.bat` writes it again from the checked facts. The old text is kept in `workspace\old_drafts\`, so nothing is lost. If you had approved it, approve the new text again.
- If the new checks do not all pass, the professor moves to **Waiting for checks** in the editor until you finish them.
- An email you edited in the editor is never replaced. It is kept and compared with the official page again. If new problems appear, its approval is cancelled so that you see them before approving again.

## A good weekly rhythm (about 30–60 minutes a day)
1. **Verify** about 40 leads (`3_verify_professors.bat`). It runs every check above.
2. **Finish what verify could not.** Open `edit_drafts.bat` and look under **Waiting for checks**:
   - If a university site blocked the automatic check, open the link yourself. If it is right, click **I checked this myself**, paste the official link and press **Mark as checked by me**.
   - If the research check failed, read "The official page says", then correct the research interests in the box and press **Save and check**. They are compared with the saved official page straight away.
   - If the email was not found, find it on the official page and record it with **I checked this myself** under Institutional email.
3. **Run the pipeline** (`4_run_pipeline.bat`). It writes emails for the verified professors and opens the **email editor**.
4. **Check and edit each email in the editor:**
   - Read the checks. Open the official profile and read the abstract of any paper the email mentions.
   - Edit the recipient, subject or text and press **Save changes**. Your edits are saved to the tracker, are still there next time, and are never overwritten when drafts are regenerated.
   - If you add a sentence about their work, the editor compares it with their official page and lists any words it could not find there. Make sure every claim is true.
   - To change the recipient, also paste the official page where that address is shown.
   - Check the **CV to attach** line at the top and open the CV once.
5. **Approve** (close the editor, then `5_approve_drafts.bat`). Each email is shown with its checks and the exact CV file. Type `yes` only for emails you would sign your name to. If a check **failed**, fix it in the editor first; type `approve anyway` only if you are sure the check is wrong.
6. **Send from Gmail.** Use the **Open in Gmail** button on the outbox page, **attach the CV named at the top of the outbox**, and press Send. Then record it: `outreach mark-sent --ids R0012,R0015`. (With the optional Gmail setup, `outreach send --method gmail-drafts` puts drafts with the CV attached into Gmail and confirms the attachment.)
7. **Replies:** `outreach mark-replied --id R0012 --note "Wants a call on Friday"`. Reply personally and quickly (within 24 hours).
8. **Follow-ups:** `outreach followups --draft` writes one short, polite follow-up for anyone with no reply after 10 days. It goes back to `draft_ready`, so check it in the editor, approve it (`5_approve_drafts.bat`), send it from the outbox, then `outreach mark-sent --ids …`. There is never a second follow-up.
9. **No or opt-out:** `outreach opt-out --id R0020`. They are never contacted again.

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
