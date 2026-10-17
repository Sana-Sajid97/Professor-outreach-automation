# Windows setup (step by step, no programming needed)

Setup takes about 15 minutes the first time. After that you only double-click the numbered files.

## 1. Install Python (one time)
1. Go to https://www.python.org/downloads/ and click the yellow **Download Python 3.x** button (3.10 or newer).
2. Run the installer. On the first screen, **tick "Add python.exe to PATH"**, then click **Install Now**.
3. When it finishes, click **Close**.

## 2. Get the project folder
- **Easiest:** on the GitHub page of this repository, click the green **Code** button, then **Download ZIP**. Right-click the ZIP and choose **Extract All…**. Put the folder somewhere simple, such as `Documents\Professor-outreach-automation`.
- *(If you use Git: `git clone https://github.com/Sana-Sajid97/Professor-outreach-automation.git`.)*

## 3. Run the setup
Open the folder and double-click **`1_setup_windows.bat`**. It:
- creates a private Python environment (`.venv` folder);
- installs the required packages;
- creates your settings file `.env` from `.env.example`;
- checks that everything works.

If Windows shows "Windows protected your PC", click **More info** and then **Run anyway**. These are plain text files you can open in Notepad and read first.

## 4. Add your CV
1. Put your CV or portfolio PDF into the **`private_profile`** folder. This folder is private and never uploaded to GitHub.
2. Double-click **`2_import_profile.bat`**. It reads your CV into `private_profile\profile.json`, then starts your tracker from the researched professor leads.
3. Open `private_profile\profile.json` in Notepad and check your details. Emails will only use facts from this file.
4. Choose the CV that goes with every email (ideally a 2-page PDF named like `Sana_Sajid_CV.pdf`): double-click **`choose_cv.bat`** and pick the file in the window that opens, or drag the PDF onto `choose_cv.bat`. It copies the file into `private_profile\cv\` and checks it: a readable PDF, your name and email inside, the number of pages, the size and the file name. Double-click `choose_cv.bat` again any time to choose a different file.

## 5. Daily use
| Double-click | What it does |
|---|---|
| `3_verify_professors.bat` | Opens each professor's **official** pages and records separate checks: profile, email, research, papers, program page (degree, Spring/Fall 2027, deadlines, IELTS, requirements) and funding. It goes slowly on purpose (a few seconds between requests) and respects each site's rules. |
| `4_run_pipeline.bat` | One-click run: checks the data, removes duplicates, scores fit, writes email drafts and exports Excel. It then opens the **email editor** in your browser. **It never sends email.** |
| `edit_drafts.bat` | Opens the email editor any time: every email with its checks and evidence; edit the recipient, subject and text and press **Save**. Professors who still need a check are listed under "Waiting for checks", where you can record checks you did yourself or correct their research interests. Keep the black window open while you edit. When you are done, press **I'm done editing** at the top of the page. Every saved change also appears on the review page (`exports\review_latest.html`). |
| `5_approve_drafts.bat` | Shows each draft with its checks and the CV that will be attached. Type `yes` to approve it (`approve anyway` if a check failed). Then it makes an "outbox" page with **Open in Gmail** buttons, so you send each email yourself with your CV attached. |

To run any other command, open the folder, click the address bar, type `cmd` and press Enter. Then type, for example:
```
outreach status
outreach list
outreach mark-sent --ids R0012,R0015
outreach mark-replied --id R0012 --note "Asked for a Zoom call"
outreach opt-out --id R0020
outreach followups --draft
outreach programs
```

## 6. Where your files are
| Folder | Contents | Uploaded to GitHub? |
|---|---|---|
| `private_profile\` | Your CV, `profile.json`, Gmail sign-in token | **Never** |
| `workspace\` | Your live tracker (`tracker.csv`), suppression list, outreach log, backups | **Never** |
| `exports\` | Dated Excel/CSV exports, review pages, run reports | **Never** |
| `data\seed\` | Researched professor leads and programs (public information) | Yes |

You can open `workspace\tracker.csv` in Excel. **Close Excel before running the tool**: Windows locks files that are open in Excel, and the tool will tell you to close it. A backup is made every time the tracker is saved (`workspace\backups\`).

## 7. Troubleshooting
| Problem | Fix |
|---|---|
| "Python was not found" | Reinstall Python and tick **Add python.exe to PATH**. Then run `1_setup_windows.bat` again. |
| A Microsoft Store window opens when running Python | Windows has a fake "python" shortcut. Install Python from python.org (step 1), or turn off *App execution aliases → python.exe* in Windows Settings. |
| "Could not save tracker.csv because another program has it open" | Close the file in Excel and run the command again. |
| `pip install` fails | Check your internet connection. On university or office networks a firewall may block it; try a home network. |
| Accented names look wrong in Excel | Open the **.xlsx** export instead of the .csv, or use Excel's *Data → From Text/CSV* and choose UTF-8. |
| `verify` says "robots.txt does not allow automated access" or "Access denied" | That university does not allow automated checks. Open the profile link yourself, find the email, then run `outreach confirm-email --id R0007 --email "name@uni.edu" --source-url "https://…official page…"`. |
| The editor did not open in the browser | Copy the link shown in the black window into your browser. The link only works while that window is open. |
| "The email editor is still open" when approving | Save your edits, press **I'm done editing** at the top of the editor (or close its black window), then run `5_approve_drafts.bat` again. |
| "The tracker was changed by another window" | Two windows tried to change the tracker at once. Nothing was overwritten: close the other window and run the command again. |
| A check says "not checked yet" or "could not open the page automatically" | Some university sites block automated checks. Open the link yourself; if it is right, use **I checked this myself** in the editor (or `outreach confirm --id R0007 --check research --source-url "https://…"`). |
| "the CV is not ready" | Run `outreach cv` to see why (for example, the PDF does not contain your name). Fix it, or choose another file with `choose_cv.bat`. |
| Something went wrong (a bug) | Details are saved in `workspace\logs\`. Your data is safe in `workspace\backups\`. |

To check your setup at any time: `outreach doctor`. To run the tests: `.venv\Scripts\python -m pytest`.
