# US Professor Outreach Automation

Starter repository for researching US graduate programs and professors relevant to a BS in Human Nutrition and Dietetics graduate. Prioritize Spring 2027 and also consider Fall 2027.

## Quick start

1. Keep this repository public only if it contains code, documentation, and non-sensitive sample data. Never commit personal documents, credentials, or API keys.
2. Keep your CV and portfolio locally in the Git-ignored `private_profile/` folder, or provide them securely to Claude Code when needed.
3. Open the repository in Claude Code.
4. Ask Claude Code to read `CLAUDE.md`, `prompt.md`, `ONE_CLICK_SPEC.md`, `WORKFLOW.md`, and `SAFETY_AND_PRIVACY.md`.
5. Ask Claude Code to inspect the existing files and report a short implementation plan before changing code.
6. Build and test the MVP in phases, starting with 20–30 verified professor records.

## What it should do
- Research professors and graduate programs using reliable official sources.
- Track faculty pages, public institutional emails, publications, deadlines, recruitment/funding evidence, and verification status.
- Deduplicate records and explain research-fit scores.
- Generate individually personalized email drafts.
- Export CSV/XLSX and track outreach.

## One-click goal
A future command/button should run configured discovery, validation, deduplication, fit scoring, draft generation, and export. This does not guarantee 300 verified contacts daily. Email sending must be separate and require explicit human approval.

## Key files

- `CLAUDE.md`: Instructions for Claude Code.
- `prompt.md`: Main project prompt and requirements.
- `ONE_CLICK_SPEC.md`: One-click workflow specification.
- `WORKFLOW.md`: Research and verification workflow.
- `SAFETY_AND_PRIVACY.md`: Safety and privacy rules.
- `professors_template.csv`: Professor tracker template.
- `.env.example`: Example configuration settings.
- `.gitignore`: Files that should not be committed to GitHub.

These files are currently in the repository root. The automation must be implemented and tested before it can be considered functional.
