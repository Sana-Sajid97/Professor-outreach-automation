# Workflow and Quality Gates

1. Discover: state → public university → relevant department → faculty/lab → graduate program.
2. Verify: require official faculty/lab page; verify institutional email from official public page; use official program page for intake and deadlines.
3. Score fit transparently:
   - 0–3 direct topic alignment
   - 0–2 education/experience match
   - 0–2 program fit/eligibility evidence
   - 0–2 recruitment/funding evidence
   - 0–1 recent relevant publication evidence
   Total 10. This is a prioritization aid, not admission probability. Missing evidence lowers confidence.
4. Draft: reference a verified research topic or reviewed paper; ask about intake and funding without assuming either.
5. Review: human checks name, institution, email, sources, intake, fit explanation, and email body.
6. Track: discovered → needs_verification → verified → draft_ready → approved → sent → replied/follow_up_due/closed. Other statuses: not_a_fit, bounced, opted_out, do_not_contact.
7. Scale: use small batches, caching, rate limits, retries/backoff, error logs, and deduplication. Report actual throughput and limitations honestly.
