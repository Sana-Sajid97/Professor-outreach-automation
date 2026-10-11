# Research data schema and rules (for research agents)

Date of this research run: **2026-10-11**. Use `"date_checked": "2026-10-11"` on every record.

## The applicant (who this research is for)

- Sana Sajid, Pakistani international applicant (needs F-1 visa; female).
- BS Human Nutrition & Dietetics, PMAS-Arid Agriculture University Rawalpindi, Nov 2021 - Aug 2025, CGPA 3.85/4.00.
- IELTS Academic overall **6.5** (subscores unknown). Programs that require IELTS 7.0 overall are a poor fit unless she retakes the test; record the exact minimum.
- Experience: clinical nutrition counseling and diet planning for underserved patients (diabetes, hypertension, obesity, renal); community nutrition-awareness internship with lifestyle surveys; final-year project assessing patients (COPD, diabetes, hypertension, pregnancy); "Cinnamon Bites" glycemic-control product at a national innovation expo; AI-assisted renal diet plan (hackathon honorable mention); XGBoost + SHAP machine-learning project on the ADNI Alzheimer's dataset; Python teaching (Stanford Code in Place section leader).
- **GOAL (clarified by the applicant's family on 2026-10-11; this overrides everything else):**
  - She wants a **FULLY FUNDED position through an ASSISTANTSHIP ONLY**: a graduate research assistantship (GRA/RA), graduate assistantship (GA) or teaching assistantship (GTA/TA) that pays a stipend **and** waives tuition. The degree can be an MS (thesis) or a PhD.
  - She is **NOT** targeting external or generic scholarships (Fulbright, AAUW and the like). Do not research those.
  - **Spring 2027 and Fall 2027 are EQUALLY important.** Target both.
  - **Every US state counts, and ANY university counts.** Ranking does not matter: regional public universities, land-grant universities, HBCUs and smaller schools are all welcome. What matters is real assistantship funding open to international (F-1) students, and IELTS 6.5 being accepted.
  - The most valuable evidence is:
    - (a) a program or department statement that admitted students (including international students) receive assistantships with tuition waivers;
    - (b) a professor with active grant funding (NIH, USDA-NIFA, NSF, foundations) or an explicit recruiting statement;
    - (c) advertised GRA/GTA openings.

## Topic vocabulary (use these keys in `matched_topics`)

| key | meaning |
|---|---|
| `community_nutrition` | public health or community nutrition, nutrition programs and policy (SNAP, WIC, school meals) |
| `food_insecurity` | food insecurity, food access, nutrition-related inequities and disparities |
| `maternal_nutrition` | maternal, prenatal and pregnancy nutrition, lactation, infant and early-life feeding |
| `diabetes_metabolic` | diabetes prevention, obesity-related metabolic health, cardiometabolic risk |
| `childhood_obesity` | childhood or pediatric obesity and its prevention |
| `clinical_nutrition` | clinical nutrition, medical nutrition therapy, dietary intervention trials |
| `nutrition_epidemiology` | nutritional epidemiology, cohort or diet-disease studies, dietary assessment methods |
| `ai_ml` | AI, machine learning or data science applied to nutrition or health |

## Hard rules: never break these

1. **Never invent anything.** That includes people, titles, emails, paper titles, years, URLs, deadlines, funding, recruiting status and IELTS minimums. If you did not see it in a search result, leave it blank or write `Not verified`.
2. **Emails:** record `institutional_email` ONLY if the exact address appears in search-result text from the person's official university page or directory. **Never guess or build an email from a pattern** such as `first.last@uni.edu`. If you did not see it, leave it `""`. Software on the applicant's PC will open the official page later and extract the email.
3. **Official sources first:** the faculty profile must be on the university's own domain (usually `.edu`). Use Google Scholar, ResearchGate, LinkedIn or news sites only as secondary evidence, never as the profile URL.
4. **Current people only:** skip anyone who is emeritus, retired, deceased, or has moved to another institution. If the evidence conflicts, say so in `confidence_notes`.
5. **Supervisors only:** include faculty who can plausibly supervise graduate students (assistant, associate or full professor, or research faculty with graduate-faculty status). Skip lecturers, adjunct or clinical instructors unless the evidence says they advise thesis students.
6. **Publications:** give exact titles with a DOI, PubMed or publisher URL, prefer 2022-2026, and include the year. If you are unsure of the exact title, leave it blank.
7. **Funding or recruiting evidence:** quote what you saw and give its URL, for example "Lab page: 'We are recruiting a PhD student for Fall 2027' (url)" or "Active NIH R01 'title' per NIH RePORTER (url)". General statements such as "most graduate students receive assistantships" go in the PROGRAM record's `funding_summary`. Otherwise write `Not verified`.
8. **Deadlines:** give the exact date with its source. If you saw only an older cycle (for example Fall 2026), write that explicitly: `Fall 2026 deadline was Dec 1, 2025; 2027 not yet posted`.
9. `WebFetch` does **not** work in this environment (DNS is blocked). Use **WebSearch** only. Use `allowed_domains` to target official domains. Use `mode: "extended"` for hard facts such as deadlines, IELTS minimums and current titles.
10. Write only to your own output files listed in your task. Do not edit any other file, and do not run git.

## Output format: JSON Lines (one JSON object per line, UTF-8)

### Professor record (`*_professors.jsonl`)

```json
{"professor_name": "First Last", "title": "Associate Professor", "university": "Official University Name", "state": "XX",
 "department_or_school": "Department of Nutrition, School of Public Health",
 "faculty_profile_url": "https://official.edu/...", "institutional_email": "", "email_source_url": "", "email_evidence": "",
 "lab_url": "", "research_interests": "short phrase; short phrase; short phrase",
 "relevant_publication_1": "Exact Title", "publication_1_url": "https://doi.org/...", "publication_1_year": "2025",
 "relevant_publication_2": "", "publication_2_url": "", "publication_2_year": "",
 "matched_topics": ["food_insecurity", "maternal_nutrition"],
 "research_fit_explanation": "1-3 sentences: which of the applicant's interests match THIS person's actual research, and why.",
 "graduate_program": "PhD in Nutrition", "program_url": "https://official.edu/...",
 "spring_2027_status": "Accepting - intl deadline 2026-11-01 (url) | No spring admission | Not verified",
 "fall_2027_status": "Accepting - intl deadline 2026-12-01 (url) | Not verified",
 "application_deadline": "2026-12-01 (Fall 2027, international, priority for funding)",
 "recruiting_evidence": "Not verified", "funding_or_assistantship_evidence": "Not verified",
 "funding_signal": "e.g. 'PI on active NIH R01 (2024-2029) per university news (url)' or Not verified",
 "eligibility_notes": "Graduate school minimum IELTS 6.5 overall (url); GRE not required (url)",
 "source_urls": ["https://...", "https://..."], "date_checked": "2026-10-11",
 "confidence_notes": "What is still unverified or uncertain.", "research_agent": "<your agent id>"}
```

### Program record (`*_programs.jsonl`)

```json
{"university": "", "state": "XX", "program_name": "", "degree_level": "PhD | MS (thesis) | MS (non-thesis) | MPH | MSPH | combined MS/PhD",
 "department_or_school": "", "program_url": "",
 "spring_2027_admission": "Yes | No | Not verified", "spring_2027_deadline": "YYYY-MM-DD (international) or text or Not verified",
 "fall_2027_deadline": "YYYY-MM-DD or text or Not verified", "funding_deadline_note": "",
 "ielts_min_overall": "6.5 | 7.0 | Not verified", "ielts_subscore_note": "", "toefl_min": "", "english_req_source_url": "",
 "gre_policy": "Required | Optional | Not required | Not verified",
 "funding_summary": "Quoted or paraphrased evidence about assistantships, waivers and stipends, or Not verified", "funding_source_url": "",
 "application_fee_usd": "", "advisor_contact_expected": "Yes | No | Not verified",
 "assistantship_types": "GRA | GTA | GA | RA - quote", "assistantship_covers": "stipend amount / tuition waiver / health insurance - quote",
 "international_eligible_for_assistantships": "Yes | No | Not stated", "assistantship_deadline": "date to be considered for funding",
 "notes": "", "source_urls": ["https://..."], "date_checked": "2026-10-11", "research_agent": "<your agent id>"}
```

### Heartbeat (`data/research/status/<agent id>.json`)

Overwrite this small file after each state, program or batch you finish, so the coordinator can see progress:

```json
{"agent": "<id>", "updated_at": "<ISO time or step number>", "professors": 0, "programs": 0, "now_working_on": "...", "done": false}
```

Set `"done": true` when you finish.
