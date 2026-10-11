# Optional: Gmail drafts with your CV attached

**You do not need this.** The review and outbox pages already have **Open in Gmail** buttons that pre-fill each email; you attach your CV and press Send. Set up the Gmail API only if you want the tool to create real Gmail drafts, with the CV already attached, in your account.

## One-time setup (about 20 minutes)
1. Go to https://console.cloud.google.com/ and sign in with the Gmail account you will send from.
2. Create a project, for example "Outreach Assistant".
3. **APIs & Services → Library** → search for **Gmail API** → **Enable**.
4. **APIs & Services → OAuth consent screen** (also called "Google Auth Platform"):
   - User type: **External**.
   - App name: anything. Support email: yours.
   - Under **Test users**, add your own Gmail address.
5. **APIs & Services → Credentials → Create credentials → OAuth client ID** → Application type **Desktop app** → Create → **Download JSON**.
6. Rename the downloaded file to **`credentials.json`** and put it in the **`private_profile`** folder. It is never uploaded to GitHub.
7. Install the extra packages: in the project folder, open `cmd` and run
   ```
   .venv\Scripts\python -m pip install -r requirements-gmail.txt
   ```
8. In `.env`, set `CV_ATTACHMENT=private_profile/Your_CV.pdf`.

## Use it
```
outreach approve
outreach send --method gmail-drafts
```
The first time, a browser window asks you to sign in and allow access. Because your app is unverified, Google shows a warning; click **Continue**. The tool asks only for the `gmail.compose` permission (create drafts and send); it cannot read your inbox. Then type `DRAFT <n>` to confirm. Open Gmail → **Drafts**, check each one, and press **Send**. Afterwards, run `outreach mark-sent --ids …`.

## Automatic sending (not recommended to start with)
Set `EMAIL_MODE=send_enabled` in `.env`, then run `outreach send --method gmail-api`. You must type `SEND <n>`. The tool:
- stays within `DAILY_SEND_LIMIT`;
- waits 45–90 seconds between emails;
- stops at the first error;
- records an email as sent only when Gmail returns a message id.

**Test first** by approving one email whose recipient is your own address.

## If sign-in stops working
Delete `private_profile\token.json` and run the command again to sign in fresh. Google may expire sign-ins for apps in "Testing" mode after a while; when that happens, this sign-in step fixes it.

*This integration was tested with a fake Gmail service in the automated tests, not with a real account. Treat your first real use as a test.*
