# US Professor Outreach Automation

Starter repository for researching US graduate programs and professors relevant to a BS in Human Nutrition and Dietetics graduate. Prioritize Spring 2027 and also consider Fall 2027.

## Quick start
1. Upload this repository to a private GitHub repository named `professor-outreach-automation`.
2. Add your CV/portfolio locally in `private_profile/` (git-ignored), or attach it directly in Claude Code. Do not commit sensitive documents, credentials, or API keys.
3. Open the repository in Claude Code.
4. Ask Claude Code to read `CLAUDE.md` and `prompts/MASTER_BUILD_PROMPT.md`, then implement the MVP in phases.
5. Begin with 20–30 verified faculty records; review quality before scaling.

## What it should do
- Research professors and graduate programs using reliable official sources.
- Track faculty pages, public institutional emails, publications, deadlines, recruitment/funding evidence, and verification status.
- Deduplicate records and explain research-fit scores.
- Generate individually personalized email drafts.
- Export CSV/XLSX and track outreach.

## One-click goal
A future command/button should run configured discovery, validation, deduplication, fit scoring, draft generation, and export. This does not guarantee 300 verified contacts daily. Email sending must be separate and require explicit human approval.

## Folders
- `CLAUDE.md`: Claude Code project rules.
- `prompts/MASTER_BUILD_PROMPT.md`: complete project brief.
- `prompts/PROFILE_TEMPLATE.md`: applicant profile template.
- `data/professors_template.csv`: database schema.
- `docs/WORKFLOW.md`: workflow and quality gates.
- `docs/SAFETY_AND_PRIVACY.md`: safety/privacy rules.
- `.env.example`: optional settings template.
