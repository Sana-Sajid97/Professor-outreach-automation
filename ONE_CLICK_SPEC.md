# One-Click Run Specification

Future user experience: one command/button should load the local profile, run configured permitted discovery, validate sources and emails, deduplicate, score fit with explanations, create drafts, export dated CSV/XLSX, and report failures or records needing manual review.

The one-click action must not send email. Sending is a separate review-and-approve workflow.

Possible future command (not functional until implemented and tested):
`python -m src.run_pipeline --intake "Spring 2027" --limit 30 --mode drafts`

Claude Code must not claim this command works until it exists and has been tested.
