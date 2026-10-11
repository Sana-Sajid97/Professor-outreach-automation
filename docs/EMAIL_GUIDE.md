# Emailing professors: what works, and how the drafts are built

## How the tool writes each draft
- **Their research** is quoted from the record's `research_interests` and recorded publications. Both come from official pages or the publication record, with sources.
- **Your experience** is copied word for word from your CV (`private_profile/profile.json`). The tool picks the one or two lines that best match the professor's topics. For data-heavy labs it adds your machine-learning project.
- **The request** asks politely whether they expect to take a new student for Spring or Fall 2027, and whether a research or teaching assistantship might be available. It **never assumes** either.
- **It never says "I read your paper".** It only mentions that the paper exists. Read at least the abstract before you send. If you have a genuine comment, add it as one sentence in `personal_note`.
- **Length and wording:** the body is kept to about 220 words, and the wording varies between professors so the emails are not identical copies.
- **Blocked automatically:** unverified records, suppressed people, departments that ask applicants not to contact faculty (for example the University of Minnesota Nutrition department before the second review round), and fit scores below the minimum.

## Good practice (common advice from US graduate programs and faculty)
1. **Subject line:** specific and honest, for example *"Prospective PhD student (Fall 2027): interest in your food insecurity research"*. Avoid "URGENT" and avoid vague subjects.
2. **First two sentences:** say who you are (degree, university, GPA) and why you are writing to *this* person.
3. **Show you know their work:** name one specific project or paper, and say how it connects to a question you care about.
4. **Show what you bring:** one or two concrete experiences (clinical counselling, community campaigns, Python/ML). Professors are deciding whether to invest grant money in you.
5. **Ask one clear question:** are they accepting students for 2027, and is RA/TA funding possible?
6. **Attach your 2-page CV as a PDF** named, for example, `Sana_Sajid_CV.pdf`.
7. **Send on weekday mornings in their time zone** (Tuesday–Thursday is often best). Avoid sending 30 emails within the same minute.
8. **Follow up once** after about 10 days, briefly and politely. If there's still no answer, move on (the tool closes the loop for you).
9. **Reply fast** (within 24 hours) when someone answers. Be ready for a short Zoom call. Prepare a 1-minute summary of your interests and two questions about their lab.
10. **Never send a mass email** with many recipients in "To" or "CC". One personalised email per professor.
11. **Respect "no":** if someone says they aren't taking students, thank them and mark the record `close` (or `opt-out` if they ask not to be contacted).
12. **Follow department rules:** some programs say not to contact faculty before admission review. The tool blocks drafts for those.

## Volume: quality beats quantity
- The default limit is **30 emails per day**, and that is plenty. Each email should take you 5–10 minutes to check and personalise.
- **300 a day is not recommended.** Professors in the same department talk to each other, and generic emails get ignored or flagged as spam. Google's limit for a personal Gmail account is about 500 emails per day, and senders of about 5,000 or more per day to Gmail users fall under its stricter bulk-sender rules. The tool's default of 30 per day stays far below both. It warns if `DAILY_SEND_LIMIT` is set above 50.
- These are **personal academic inquiries, not marketing**. Even so, the tool follows anti-spam good practice: honest subject lines, one email per person, at most one follow-up, a respected opt-out (suppression list), and no purchased or scraped lists.

## Example structure (the tool fills this in from verified facts)
```
Subject: Prospective PhD student (Spring/Fall 2027): interest in your food insecurity research

Dear Professor <Last name>,

My name is <name>, and I recently completed a <degree> at <university>, with a CGPA of <cgpa>. I am
writing because your research on <their topic, quoted> closely aligns with my interest in <topic>.
Your <year> paper, "<exact title>," is especially relevant to the questions I hope to study.

This connects with my own experience. <CV sentence>. I also bring quantitative skills: <CV sentence>.

I am planning to apply to <program> at <university> for <intake>, and I would be grateful to know whether
you expect to accept a new <degree> student in your group. I would also appreciate knowing whether a
graduate research or teaching assistantship might be available.

I have attached my CV for your reference and would be happy to share any additional information.
Thank you very much for your time and consideration.

Sincerely,
<signature from profile.json: name, degree/university, email, LinkedIn>
```
