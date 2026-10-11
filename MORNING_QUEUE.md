# Morning queue: decisions and actions that need a human

*Built overnight, 11 Oct 2026. Highest priority first.*

## 🔴 1. GitHub: nothing could be pushed (needs you)
- Every attempt to push to `Sana-Sajid97/Professor-outreach-automation` was refused with **403**, from both git and the GitHub connector ("Resource not accessible by integration"). **The Claude GitHub App is not installed on Sana's repository.**
- Fix it in one of two ways:
  - reconnect GitHub at https://claude.ai/customize/connectors?auth_start=github&auth_start_force=1, or
  - have Sana install the app on her repository: https://github.com/apps/claude/installations/select_target.
- Then ask Claude to push the branch `claude/scholarship-application-automation-2yiu9t`. All work is committed there locally.
- **Backup:** a private Claude artifact holds a downloadable copy of the whole project (link in the session summary), in case the cloud session's container is recycled first.

## 🔴 2. Privacy: the public repository contains Sana's portfolio PDF
- `Sana Sajid - Portfolio (1) (1).pdf` (phone number, transcript, certificates) is committed to a **public** repository. Her CLAUDE.md and SAFETY_AND_PRIVACY.md say personal documents must stay out of public GitHub.
- **Recommended:** make the repository **private** (GitHub → Settings → General → Danger Zone → Change visibility).
- Alternatively, delete the PDF from the repository. It still exists in the history, so purging it fully needs a history rewrite (GitHub's "Removing sensitive data" guide).
- The tool reads the CV from the private `private_profile/` folder, so the PDF does not need to be in the repository.
- I did **not** delete or move it, because that is Sana's decision.

## 🟠 3. Spring 2027: act this week or let it go
- **No January research-assistant position is confirmed anywhere** (see `docs/STRATEGY_2027.md` §3). Most international spring deadlines have passed (Aug 1 to Oct 15), and federal SNAP-Ed funding (which paid many community-nutrition assistants) ended 30 Sep 2025.
- Urgent targets and dates:
  - **South Dakota State, Oct 15:** 4 days away.
  - **Montclair State, Nov 1:** Lauren Dinour's maternal and child health nutrition training grant may fund trainees; ask whether F-1 students qualify.
  - **Clemson:** rolling admission, but no spring I-20s after **Nov 15**.
  - **Utah State and Florida:** rolling.
  - **NDSU, Dec 1:** check whether the "blended" format works for an F-1 visa.
  - **New Mexico State:** spring I-20 deadline Dec 21.
  - **South Carolina State MS:** Nov 1; the application fee and GRE are waived for Spring 2027.
  - **Tuskegee MS:** rolling, but takes about 90 days to process, so apply now.
- **Decision:** spend about one week emailing these professors. If no funded offer appears by about **Nov 10**, put all effort into Fall 2027, which has far more fully funded options (Texas A&M, Penn State, Ohio State, Purdue, Emory, Michigan, ASU, Oregon State, UMass, UConn and others).

## 🟠 3b. A Fall 2027 deadline in 4 days
- **Baylor PhD in Exercise & Nutrition Sciences:** a $30,000 stipend plus tuition, open to bachelor's applicants, IELTS 6.5. It shows an **Oct 15 priority deadline** (from an older page; the other date is Feb 1). Check the official page today. If the date is real, email April Stull (functional foods for prediabetes) now, since a faculty mentor is required.

## 🟠 4. English test (affects admission AND funding)
- IELTS 6.5 meets many programs' minimums, but:
  - several strong programs require 7.0;
  - **teaching assistantships usually require IELTS speaking 7.0–8.0**.
- **Decision:** book a retake (IELTS or TOEFL; TOEFL now uses a 1–6 scale) for early to mid November, aiming for **7.0+ overall and 7.5+ speaking**. Consider the Duolingo English Test as a fast backup where programs accept it.
- Check that the current IELTS is less than 2 years old at application time.

## 🟠 5. Credential evaluation
- Order a **WES or ECE course-by-course evaluation now**; it takes weeks. Some programs require it (UNC Greensboro won't review an application without one; Wayne State requires it).

## 🟡 6. First run on Sana's Windows PC (about 30 minutes)
1. Follow `docs/WINDOWS_SETUP.md`: `1_setup_windows.bat`, then `2_import_profile.bat`.
2. Run `outreach verify --limit 5` first. This is the **first live test** of the page verifier: the cloud environment blocked university websites, so it was only tested on sample pages. If it fails, save the message from `workspace\logs\` and ask Claude to fix it.
3. Run `4_run_pipeline.bat` and read the drafts on the review page. Run `outreach preview` to see draft previews for not-yet-verified leads.

## 🟡 7. Profile improvements (see `docs/PROFILE_REVIEW.md`)
- **Rewrite the CV to 2 pages.** The current 29-page portfolio is not what US faculty expect.
- **Ask 3 recommenders by about 25 Oct.**
- **Rewrite the four CV lines** the email tool holds back (§6 of the review).
- **Merge the two GitHub accounts** into one.
- **Learn R and do a small NHANES project.**

## 🟡 8. Facts to double-check before relying on them
- Unconfirmed report of an **F-1 "duration of status" change** (a fixed admission period of up to 4 years) from 2026. This would affect 5-year PhD plans. Check https://travel.state.gov and the international office of each university.
- **Pakistan's status under Proclamation 10998** (39-country restrictions, effective 1 Jan 2026): research suggests Pakistan is *not* fully banned. Confirm the current list on travel.state.gov.
- Every deadline and IELTS minimum in `data/seed/programs.csv` comes from search summaries; many pages show undated or last-cycle dates. Confirm each on the official page before applying.

## 🟢 9. Optional setup
- **OpenAlex API key** (free): needed for `outreach discover` (new leads from recent papers).
- **Gmail API** (`docs/GMAIL_SETUP.md`): only if you want Gmail drafts with the CV attached. The "Open in Gmail" buttons work without it.
- **Network access in the cloud environment:** this Claude session could not open university websites (egress was blocked). To let a future cloud session verify pages itself, widen the environment's network access (cloud environment menu → Edit → Network access) or allow the needed domains.

## 🟢 10. Scope notes
- External scholarships are out of scope (assistantships only). Wave-1 scholarship research stays in `data/research/raw/scholarships.jsonl` for reference. In brief: P.E.O. IPS is open (eligibility form due 2026-12-15, up to $12,500, admission required); Fulbright Pakistan and AAUW are closed for 2027. Delete the file if it is not wanted.
- **University of Minnesota Nutrition** asks applicants **not** to contact faculty before the second review round. The tool blocks drafts to them.
