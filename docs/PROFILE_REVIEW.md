# Profile review: how a US nutrition professor will read your application

*Prepared 11 October 2026 for Sana Sajid. It is based on your portfolio PDF, your public GitHub repositories, and web research on current (2025–2026) US admissions rules. Sources are listed at the end. Please correct anything that is inaccurate.*

> **Bottom line.** Your profile is a credible fit for **funded thesis-MS and some direct-entry PhD positions** in nutrition. That holds especially for labs that value clinical and community nutrition experience combined with data skills, which few nutrition graduates have. Two things limit you right now. The first is **English scores**: IELTS 6.5 rules out a number of programs and most teaching assistantships. The second is the **lack of a formal research output** (no poster, paper or research thesis). Both can be improved within weeks. The rest of this page explains how.

---

## 1. What a professor sees in the first 60 seconds

| Professors look for | What your profile shows | Verdict |
|---|---|---|
| Strong grades | CGPA **3.85/4.00**, among the top of your batch | ✅ Strong |
| Real nutrition experience | Clinical internship at **Fatima Memorial Hospital, Lahore**: Nutrition Care Process and medical nutrition therapy across 9 wards, including gynaecology and paediatrics. Counselling of underserved patients. Community nutrition-awareness campaigns. | ✅ Strong, but under-described in your CV |
| Research experience | A final-year project that is an internship report rather than a research thesis. Patient surveys. A machine-learning analysis notebook. | ⚠️ Present but informal |
| Quantitative skills | Python, XGBoost, SHAP, UMAP and clustering, plus statistics coursework | ✅ A real differentiator in nutrition |
| Fit with *their* research | Wide interests: food insecurity, maternal nutrition, diabetes, obesity, clinical nutrition, epidemiology | ⚠️ Narrow it to 1–2 themes in each email or statement |
| Can work as TA or RA | Teaching experience: Stanford Code in Place section leader, trainer for 200+ students | ⚠️ TA roles need high **spoken** English scores (see §3) |
| English | IELTS Academic **6.5** | ⚠️ Meets many programs' minimum, but not all, and rarely meets TA rules |
| Professional presentation | A 29-page portfolio with certificates. Two GitHub accounts with duplicated repositories. | ⚠️ Needs tightening to US norms |

## 2. Your strongest selling points (use them)

1. **Clinical nutrition in a real hospital.** You applied the Nutrition Care Process, wrote therapeutic diet plans and carried out medical nutrition therapy across nine wards. US labs running dietary-intervention trials value this. Say it plainly in your CV, and name the hospital and the wards.
2. **Diabetes and metabolic focus.** You managed dietary interventions for patients with diabetes, hypertension, obesity and renal disease, and led the "Cinnamon Bites" glycemic-control product team at a national expo. That is a coherent story for diabetes-prevention labs.
3. **Data skills that most nutrition applicants lack.** Your TRE–Alzheimer's notebook is well organised, and it honestly states that it does not claim TRE causes better outcomes; professors notice that kind of care. Nutrition epidemiology and "precision nutrition" groups need people who can code.
4. **Teaching and communication.** Section leader for Stanford Code in Place (2026), Python and IELTS trainer for 200+ students, debate awards, and a seminar you organised. This supports your potential as a teaching assistant once your spoken-English score allows it.
5. **Community work with underserved groups.** This links naturally to food-insecurity and health-equity research.

## 3. Concerns a professor is likely to have, and how to answer them

### 3.1 English scores limit both admission and funding
- IELTS 6.5 meets the minimum at many programs in our research, including Texas A&M, Penn State, Purdue, Michigan State, Tennessee, Oregon State, Arizona State, UConn, UNH and Nebraska.
- It is **below the minimum at others**: UNC Chapel Hill, UC Davis, Rutgers, Cornell, Harvard, Tufts, Maryland, Johns Hopkins, UW–Madison and the UC campuses ask for 7.0. Illinois gives full admission status only from 7.5. See `data/seed/programs.csv`.
- **Teaching assistantships have separate, higher spoken-English rules.** Examples: IELTS *speaking* 8.0 at Michigan State, UConn and Arizona State; 7.0 speaking at Oregon State; and some Florida universities do not accept IELTS at all for TA eligibility. With 6.5 overall you depend on **research** assistantships, which are funded by a professor's grant.
- **Action:** retake soon, aiming for **7.0+ overall and 7.5–8.0 in speaking**.
  - The **TOEFL iBT moved to a new 1–6 score scale on 21 January 2026**: 5.0 ≈ 95+ and 4.5 ≈ 86+ on the old scale. Check how each program states its minimum.
  - Many programs also accept the **Duolingo English Test** (typically 110–120), which reports results within days and makes a useful backup. Confirm with each program.
  - Some schools only accept scores up to **2 years old**, so check the date of your IELTS.

### 3.2 No formal research output yet
A PI deciding whether to pay you from a grant wants evidence that you can finish a research task. Your final-year project is a strong *clinical* report, but it is not hypothesis-driven research. Two inexpensive ways to fix that within weeks:
- **A small public-data analysis in your target area.** Example: *food insecurity and diet quality in US adults*, using NHANES (free and public) in **R**. Write it up as a 4–6 page report on GitHub. It shows exactly the skills nutrition-epidemiology labs hire for, and it is relevant to food-insecurity faculty.
- **Turn the hospital case studies into a short case-series poster** (anonymised and with your supervisor's permission). Submit it to a student session or a regional nutrition conference abstract call.

### 3.3 Your machine-learning project: strong, but a careful reviewer will ask two questions
1. **Some of the "compact" features help define the diagnosis itself.** MMSE, CDR-SB and ADAS-Cog are clinical assessments used when ADNI assigns diagnostic groups, so high accuracy is partly expected. Run an *ablation*: retrain without the cognitive test scores and report what imaging or metabolic markers alone achieve, with confidence intervals. That turns a likely criticism into a strength.
2. **Data source.** The notebook uses a Kaggle re-upload of ADNI data. ADNI data are shared under a Data Use Agreement that requires an application and acknowledgement. If you keep working with ADNI, apply for official access (LONI IDA) and follow the agreement. For nutrition labs, an NHANES-based project (see 3.2) is more relevant anyway.

### 3.4 Presentation: US norms differ from portfolio style
- **US faculty expect a 2–3 page academic CV, not a 29-page portfolio.** Leave out certificates and photos of awards. A professor spends under a minute on a CV.
- **Lead with nutrition.** Put blockchain and agentic-AI hackathons (for example QubicAgent) in a single "Other technical projects" line. Nutrition PIs want to see focus.
- **Tone and accuracy:**
  - Remove self-praise such as "stellar CGPA" and let the numbers speak.
  - Fix typos, for example "Internation Hackathons".
  - Describe the final-year project accurately. It is a clinical nutrition internship report at Fatima Memorial Hospital, not a study of hypochondriasis.
- **Name your university consistently,** exactly as on your degree and transcript. Your project report says it was completed at Barani Institute of Sciences, Sahiwal Campus, under PMAS-Arid Agriculture University Rawalpindi. Credential evaluators and admissions staff compare names across documents, so state it the same way everywhere.
- **GitHub:** merge your two accounts (`thesanasajid` and `Sana-Sajid97`) into one. Pin your 3 best nutrition-related repositories, each with a clear README, and delete the duplicates. If a project uses simulated data (NutriCoach-AI mentions a "simulated research study"), say so prominently.
- **Privacy:** this repository is public and contains your portfolio PDF, with your phone number and transcript. Make the repository private, or remove the PDF. See `MORNING_QUEUE.md`.

## 4. Action plan, in priority order

| When | Action | Why |
|---|---|---|
| **This week** | Run the tool's `verify` step on your PC. Email the **Spring 2027** research-assistantship targets first (see `docs/STRATEGY_2027.md`). | Spring is only possible if a professor with grant money takes you for January |
| This week | Order a **WES or ECE course-by-course evaluation** | Required by some universities (for example Wayne State and UNC Greensboro, which won't review an application without one). It takes weeks. |
| This week | Book an **IELTS/TOEFL retake** for early-to-mid November. Consider **Duolingo** as a fast backup. | Scores must arrive before the Dec 1–15 deadlines. A higher speaking score opens TA funding. |
| By 20 Oct | Rewrite your **CV to 2 pages** (template in §5). Rewrite two CV lines for emails (§6). | Professors read your CV first |
| By 25 Oct | Ask **3 recommenders**: an internship supervisor, an FYP supervisor, and a professor who taught you research methods or statistics. Give each your CV and target list. | Most funded PhD programs need 3 letters by Dec 1 |
| Oct–Nov | Learn **R** (and basic SPSS/SAS). Complete the **NHANES mini-project**. | Nutrition labs list SAS, R and SPSS skills. It also gives you a research output. |
| Nov | Write a **statement of purpose for each program**, naming 2–3 faculty and one clear research question | UT Austin and TWU ask for named faculty or a named advisor; Emory weighs research fit |
| Before visa | Keep your **social-media accounts public** and consistent with your CV. Book your interview in Pakistan as early as possible. | US policy since June 2025 requires public social media for F, M and J applicants. Pakistan applicants interview in-country. |

## 5. A 2-page academic CV that US professors expect

```
SANA SAJID
Email · LinkedIn · GitHub (one account) · City, Pakistan

RESEARCH INTERESTS
Food insecurity and maternal/metabolic health; dietary interventions for diabetes prevention;
data-driven nutrition epidemiology.

EDUCATION
BS Human Nutrition & Dietetics, [official university name as on degree], 2021–2025
CGPA 3.85/4.00 (top of batch) · Relevant coursework: Public Health Nutrition, Research Methods,
Statistics, Dietetics

RESEARCH & ANALYTICAL EXPERIENCE
• Clinical nutrition internship & final-year project, Fatima Memorial Hospital, Lahore (2025)
  Applied the Nutrition Care Process and MNT across 9 wards (incl. gynaecology/obstetrics,
  paediatrics, nephrology); documented case studies; follow-up assessments.
• Machine-learning analysis of Alzheimer's biomarkers (2026), Python/XGBoost/SHAP
  [one line on the result + the ablation you add]; GitHub link.
• [NHANES food-insecurity analysis in R (2026), once completed]

CLINICAL & COMMUNITY NUTRITION
• Nutrition counselling and diet planning for underserved patients (diabetes, hypertension,
  obesity, renal disease), recognised with an award for contribution to patient health (2025).
• Community nutrition-awareness campaigns; lifestyle surveys (internship).
• "Cinnamon Bites" glycemic-control product, team lead, National Innovation Expo (award).

TEACHING
• Section Leader, Stanford Code in Place (2026); Python and IELTS trainer for 200+ students.

SKILLS
Nutrition assessment (anthropometry, BIA, SGA, MNA, MUST, NCP) · Python · R · Statistics
· Data collection & analysis

AWARDS & ACTIVITIES (one line each)
```

## 6. Two CV lines worth rewriting so the email tool can use them

The tool copies sentences from your CV into emails word for word. It never makes them up. It has **held back four of your CV lines** (E06, E07, E08 and E28 in `profile.json`) because they read like long lists. After you rewrite your CV, re-run `import-profile`, or edit `email_sentence` in `private_profile/profile.json` and set `"use_in_emails": true`. Suggested rewrites (check that they are accurate first):

- **Final-year project (E28):** *"During my final-year clinical project, I assessed patients with diabetes, hypertension, COPD and pregnancy-related nutrition needs, prepared diet plans, and followed up on their progress."* This lets maternal-nutrition professors see your pregnancy-related experience.
- **New internship line:** *"During my clinical internship at Fatima Memorial Hospital, Lahore, I applied the Nutrition Care Process and medical nutrition therapy across nine wards, including gynaecology and paediatrics."*

## 7. What this means for your strategy

1. **Funding will come from assistantships, so target professors with grants.** Mentor-based programs say this directly. LSU: admission depends on space in an individual professor's program. NC State: admission is limited by faculty funding. The email tool is built for exactly this.
2. **Thesis MS with a research assistantship, then PhD, is a realistic and respected path.** Some PhD programs expect a master's (for example Montana State's PhD). Others fund BS-entry PhD students fully (Texas A&M, Penn State, Purdue, Emory and others in `docs/STRATEGY_2027.md`). Apply to both kinds.
3. **Do not count on teaching assistantships until your speaking score rises.**
4. **Your differentiator is clinical plus data skills.** Lead with it when writing to labs that do dietary interventions, diabetes or epidemiology.

---

### Sources (checked 11 Oct 2026 via web search; see also `data/research/raw/profile_research.json`)
- TOEFL scale change: https://www.ets.org/toefl/institutions/ibt/score-scale-update.html
- TA spoken-English rules:
  - Michigan State: https://grad.msu.edu/academics/policies-and-procedures/msu-policy-affecting-international-teaching-assistants
  - UConn: https://ita.uconn.edu/english-proficiency-policy-for-ita/
  - Arizona State: https://learnenglish.asu.edu/international-teaching-assistant-ita
  - USF: https://www.usf.edu/graduate-studies/funding/graduate-assistantships-resource-center/
- Credential evaluation:
  - Wayne State: https://gradschool.wayne.edu/admissions/international-process-transcripts
  - Syracuse (four-year Pakistani bachelor's degrees): https://www.syracuse.edu/admissions-aid/application-process/international/graduate/equivalence-us-bachelors/
- What programs look for:
  - Emory: https://nutrition.emory.edu/admissions/index.html
  - UT Austin: https://nutrition.utexas.edu/academics/graduate-programs/graduate-program-admissions
  - NC State: https://cals.ncsu.edu/food-bioprocessing-and-nutrition-sciences/students/graduate/nutrition-science/
  - LSU: https://www.lsu.edu/agriculture/nfs/programs/doctorate.php
  - Loma Linda (SAS/R/SPSS): https://publichealth.llu.edu/academics/doctor-philosophy-phd/phd-nutrition
- Visa:
  - US Embassy Pakistan: https://pk.usembassy.gov/visas/
  - Social-media vetting (US Mission Mexico notice): https://mx.usembassy.gov/student-visa-social-media-vetting/
  - Proclamation 10998: https://travel.state.gov/content/travel/en/News/visas-news/
- University rankings (THE 2026): https://www.timeshighereducation.com/world-university-rankings/pmas-arid-agriculture-university-rawalpindi
- Your repositories:
  - https://github.com/Sana-Sajid97/tre-alzheimers-biomarkers
  - https://github.com/Sana-Sajid97/Final-Year-Project
  - https://github.com/thesanasajid

*Visa and immigration rules change often. Always confirm on travel.state.gov and with each university's international office.*
