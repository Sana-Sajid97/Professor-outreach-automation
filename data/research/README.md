# How the research data was collected (and its limits)

- **When:** 11 October 2026, in three "waves" of parallel AI research agents. Each agent covered a group of US states or a group of universities.
- **How:** web-search results from official university pages (`.edu`), PubMed/DOI records, and official program and graduate-school pages. Every record lists its `source_urls`.
- **Main limitation:** the research environment could **search** the web but could not **open** pages. Every fact therefore comes from search-result summaries of official pages, which is why every professor lead is marked `needs_verification`. The tool's `verify` command opens each official page on your own PC and confirms the person and their email before any email can be drafted.
- **Never invented:** emails were recorded only when one appeared in a search result from an official page (8 cases). All other emails are blank on purpose. They are not guessed from patterns such as `first.last@uni.edu`.
- **Deadlines:** many program pages show recurring dates without a year ("Dec 1"), or show the previous cycle. Records say so. Always confirm on the official page.

## Files
| File | Contents |
|---|---|
| `SCHEMA.md` | Rules and formats the agents followed (includes the clarified assistantship-only goal) |
| `raw/region-*.jsonl` | Wave 1 (regional): professors and programs |
| `raw/w2-*.jsonl` | Wave 2 (all states; assistantship-funded focus) |
| `raw/w3-*.jsonl` | Wave 3 (faculty depth at the strongest funded programs, Spring 2027 RA targets, publication enrichment) |
| `raw/spring-2027_programs.jsonl` | Spring 2027 intake hunt |
| `raw/funded-positions.jsonl` | Advertised funded positions (few were found; most funding comes through admission or directly from professors) |
| `raw/profile_research.json` | Facts used for `docs/PROFILE_REVIEW.md` (English tests, credential evaluation, visa, what programs look for) |
| `raw/technical_facts.json` | API and compliance facts used in the code and docs (OpenAlex key requirement, robots.txt behaviour, Gmail OAuth) |
| `raw/scholarships.jsonl` | Wave-1 research on external scholarships. **Out of scope** after the goal was clarified (assistantships only); kept for reference. |
| `wave2_leads.md` | Unverified name leads used to direct later waves |
| `status/*.json` | Agent heartbeat files |

Rebuild the seed files after adding research: `python scripts/build_seed.py`.
