# What needs credentials, what works without them, and the limits

## Works with no accounts or keys
| Feature | Notes |
|---|---|
| Import your CV/portfolio PDF | Local only |
| Tracker, validation, duplicate merging, fit scoring | Local only |
| Email drafts, review page, approval, outbox with "Open in Gmail" buttons | You send from your own Gmail in the browser. No setup is needed. |
| Excel/CSV export, follow-up reminders, suppression list | Local only |
| `verify` (checks official faculty pages) | Needs normal internet on your PC. Respects robots.txt, waits between requests, and backs off when asked. |
| `check-funding` (NIH RePORTER) | Official public API, no key needed. NIH asks users to keep to about 1 request per second, and the tool waits between requests. |

## Needs a free key or a one-time setup
| Feature | What you need | Where it goes |
|---|---|---|
| `discover` (OpenAlex) | A free **OpenAlex API key**, required for all requests since **13 Feb 2026**. The old "polite pool" email method no longer works. There is a free daily usage allowance; keyword searches cost more of it than filters, so the tool keeps queries small. | `OPENALEX_API_KEY=` in `.env` |
| Gmail drafts with your CV attached (`send --method gmail-drafts`) | A Google Cloud project with the Gmail API enabled, an OAuth **Desktop app** client file, and a one-time browser sign-in | `private_profile\credentials.json`; the token is saved to `private_profile\token.json`. See `docs/GMAIL_SETUP.md`. |
| Automatic sending (`send --method gmail-api`) | The Gmail setup above, **plus** `EMAIL_MODE=send_enabled` in `.env`. You still approve every email and type `SEND <n>` for each batch. | `.env` |

## Honest status of each feature (11 Oct 2026)
| Feature | Status |
|---|---|
| Core workflow (import, validate, dedupe, score, draft, review, approve, outbox, mark-sent, follow-ups, suppression, export) | **Implemented and tested.** 81 automated tests pass, including an end-to-end run on sample data. |
| `verify` | Implemented and tested against realistic sample web pages, including mailto links, "[at]/[dot]" anti-spam text, Cloudflare-protected emails, robots.txt, rate limits and 404 errors. **Not yet run against live university websites**, because the cloud build environment blocks outside websites. The first real run on your PC is its first live test, so start with `--limit 5`. |
| `discover` (OpenAlex) and `check-funding` (NIH) | Implemented from the official API documentation and tested with sample responses. **Not yet run live** (same reason). Try them with a small `--limit`. |
| Gmail drafts and sending | Implemented and tested with a fake Gmail service. **Not yet tested with a real Google account.** Test by sending to yourself first. |
| Web search for new professors | **Not built into the tool.** The researched leads in `data/seed/` came from a one-time AI-assisted research run. To add more, use `discover` (OpenAlex) or add professors yourself with `import`. |

## About Claude and other AI tools
- Claude Pro does **not** give this tool unlimited web research, and it does **not** give it access to your Gmail or Google Sheets. This tool runs on your own PC with your own accounts.
- The research leads in `data/seed/` were collected with Claude's web search during one session, which had a fixed search budget (about 200 searches per turn). That is why every lead is marked `needs_verification`.

## Safety limits built into the tool
- Drafts only by default. **The one-click pipeline never sends.**
- Every email needs your explicit approval after a full preview (recipient, subject, body, evidence). Editing an email after approval cancels the approval.
- Daily sending limit (default 30). Sends are spaced out, and a failed send is never recorded as sent.
- People who opt out, bounce, or must not be contacted are suppressed forever.
- No CAPTCHA solving, no logins, no getting around blocks. Pages that refuse automated access are left for you to check by hand.
- Secrets live only in `.env` and `private_profile\`, which are never uploaded to GitHub.
