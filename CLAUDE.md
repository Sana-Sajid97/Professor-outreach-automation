# Claude Code Instructions

Build a reliable, beginner-friendly US graduate admissions research and professor-outreach assistant.

## Objective
Support an applicant with a BS in Human Nutrition and Dietetics, CGPA 3.85/4.00, and interests in public/community nutrition, food insecurity, maternal/pregnancy nutrition, diabetes/metabolic health, childhood obesity, clinical nutrition, nutrition epidemiology, and AI/ML as a supporting quantitative method. Prioritize Spring 2027 and also research Fall 2027.

## Rules
1. Read README.md, prompt.md, ONE_CLICK_SPEC.md, WORKFLOW.md, SAFETY_AND_PRIVACY.md, and professors_template.csv from the repository root before coding.
2. Inspect the repository, propose a short phased plan, then implement Phase 1.
3. Build a usable MVP before complex integrations. Make it beginner-friendly and Windows-compatible.
4. Prefer official university, faculty, lab, program, and publication sources.
5. Never invent emails, faculty, papers, deadlines, eligibility, funding, or recruiting status. Leave unknown fields blank or mark Not verified.
6. Deduplicate by institutional email, faculty URL, and name + university.
7. Support CSV/XLSX export and transparent fit explanations.
8. Keep private profile files, credentials, and tokens out of Git.
9. Respect site terms, robots rules, APIs, rate limits, privacy, and anti-spam requirements. Do not bypass CAPTCHAs or access controls.
10. Default to email drafts. Sending must be a separate action with explicit human approval and a preview of recipient, subject, body, and evidence.
11. Track opt-outs, bounces, and do-not-contact status; suppress those contacts from future outreach.
12. Do not claim that Claude Pro alone provides unlimited web research or Gmail/Sheets access. Document external credentials and limits.

## MVP deliverables
- Import applicant profile facts from supplied files.
- Validate records and source URLs.
- Deduplicate faculty records.
- Score fit transparently; score is a prioritization aid, not an admission probability.
- Generate personalized email drafts based on verified research.
- Export CSV/XLSX.
- Track statuses: discovered, needs_verification, verified, draft_ready, approved, sent, replied, follow_up_due, not_a_fit, bounced, opted_out.
- Include tests and exact Windows setup/run instructions.
- Do not claim web discovery works until a permitted search integration is configured and tested.

Before finishing, run tests, report what works and what still needs credentials, and give exact commands. Never claim an unimplemented feature works.
