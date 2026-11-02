# LearnAI competitor matrix

**Snapshot: 1 November 2026.** Nine competitors, twelve comparison dimensions,
and separate rows for LearnAI's current engine and full intended platform.

- [Interactive matrix](competitor-matrix/learnai-competitor-matrix.html) — switch
  dimensions, filter competitor groups, search and open evidence links.
- [Editable spreadsheet](competitor-matrix/learnai-competitor-matrix.xlsx) — three
  comparison sheets, filterable evidence, sources and LearnAI's roadmap.
- [Structured comparison data](competitor-matrix/matrix-data.json) — the same
  findings in a maintainable format.

## Product intent

The founder's clarification expands the comparison beyond tutoring sessions:
**LearnAI is intended to be a persistent, personalised learning environment tied
to the student's own school or university curriculum, across subjects.**

The learner should return to their own topics, progress and next steps. The
platform should use curriculum requirements, demonstrated knowledge, prerequisite
readiness and retention needs to guide what happens next. The student should not
have to reconstruct their context or invent the next study prompt every visit.

The long-term subject ambition includes mathematics, chemistry, history, English
and other disciplines, from primary through high school and early university.
That is a product/architecture goal, with staged content and assessment coverage.
The implemented scope remains a twelve-skill quadratics Practice engine.

“Like Blackboard” describes the continuity and curriculum-specific student
experience. Whether LearnAI also replaces institutional administration, gradebooks,
assignment submission or LMS infrastructure is **not decided**. A standalone
learner product and an LMS-connected service remain possible delivery choices.

## How to interpret the matrix

**Documented** means a first-party source describes the feature; it does not mean
we tested it. **Scoped** identifies a related capability with a relevant limit.
**Not verified** means the review did not establish it, not that it is absent.
LearnAI uses separate **Foundation**, **Not built**, **Planned** and **Open decision**
labels. A roadmap cell must never be counted as shipped product parity.

Feature names are not interchangeable: a saved chat is not a course record; a
gradebook is not automatically a prerequisite model; flashcards do not prove a
spaced scheduler; and assessment scores need not separate assisted from unaided
performance. The matrix describes scope rather than awarding checkmarks or scores.

Sources were checked as public documentation on this date. Availability can vary
by region, age, plan, institution and course. This is a feature review, not a
pricing comparison, privacy audit or independent learning-outcomes benchmark.
Competitors will also evolve while LearnAI's roadmap is implemented.

## What the comparison changes

### StudyFetch is a particularly relevant direct comparison

Its documented Study Plan organises topics around a syllabus and exam dates,
records progress and recommends the next topic. This overlaps substantially with
the intended continuous experience. It also documents Canvas sign-in/material
import and flashcard scheduling. It should not be presented as a one-off chatbot.
[Study Plan](https://sso.studyfetch.com/docs/docs/product-docs/6a519349893cd6f616be1054),
[Canvas integration](https://sso.studyfetch.com/docs/docs/product-docs/6a067a051289ddc3f19038b2),
[flashcards](https://sso.studyfetch.com/docs/docs/product-docs/6a52628f02a11a95bc7fcc0e).

### Adaptive platforms already connect progress to next steps

CENTURY describes curriculum-aligned content, personal pathways and spaced
retrieval. IXL documents continuously updated diagnostics and recommendations;
its diagnostic scope is maths and language arts, narrower than its wider content
catalogue. ALEKS describes adaptive paths and recurring retention checks in maths
and chemistry. These are important comparators for the learning engine, not just
exercise libraries.
[CENTURY](https://knowledge.century.tech/teacher-introduction-to-century),
[CENTURY review](https://www.century.tech/news/the-science-behind-century/),
[IXL diagnostic](https://www.ixl.com/diagnostic/info?lmsPlatform=1),
[ALEKS](https://www.mheducation.com/highered/digital-products/aleks.html),
[ALEKS retention](https://www.mheducation.com/prek-12/support/knowledge/aleks-frequently-asked-questions-faq-for-students.html).

### The learning platform around the tutor matters

Khan Academy plus Khanmigo should be evaluated together: course goals, tutoring,
learner history and maths checking form a broader offer than a chat window.
Quizlet likewise has saved study paths and spaced repetition, even though its
Ask Quizlet documentation currently describes conversation resets across pages.
Do not confuse the limitations of one chat feature with the entire platform.
[Khanmigo development report](https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/),
[Quizlet paths](https://help.quizlet.com/hc/en-us/articles/360048314692-Setting-up-a-study-path),
[Quizlet spaced repetition](https://help.quizlet.com/hc/en-us/articles/48324742264077-Studying-with-Spaced-Repetition),
[Ask Quizlet scope](https://help.quizlet.com/hc/en-us/articles/42790350723725-Studying-with-Ask-Quizlet).

### Institutional platforms are also adding AI and personalisation

Canvas documents score-based Mastery Paths and course-grounded AI study materials.
Blackboard documents outcome tracking and configured AI conversations, alongside
an assistant with course-access limitations. Therefore “an LMS with AI” alone is
not a unique position. These platforms could be competitors, distribution
partners or integration targets depending on the business model.
[Canvas paths](https://community.canvaslms.com/t5/Canvas-Basics-Guide/What-is-Mastery-Paths/ta-p/404483),
[Canvas AI](https://community.instructure.com/en/kb/articles/664510-what-are-the-available-ai-features-in-canvas),
[Blackboard Outcomes](https://help.anthology.com/blackboard/student/en/grades/blackboard-outcomes.html),
[Blackboard AI Conversation](https://help.anthology.com/blackboard/student/en/course-content-and-materials/ai-conversation.html).

## What “any subject” requires from LearnAI

The following are planning implications, not completed implementations or final
assessment designs. Broad model knowledge and the ability to host uploaded
material do not establish reliable teaching and assessment for every subject.

| Subject example | Content and interaction needs | Evidence/assessment work to design |
| --- | --- | --- |
| Mathematics | Notation, worked steps, graphs and appropriate methods | Supported symbolic checks, method requirements and reasoning beyond final answers |
| Chemistry | Formulae, reactions, quantities and diagrams | Chemical constraints, units and subject-valid reasoning checks |
| History | Chronology, sources, context and argument | Factual grounding plus rubrics for sourcing, interpretation and argument quality |
| English | Reading passages, grammar, writing and revision | Rubrics and calibrated judgement for comprehension and writing; multiple valid responses |

A common engine can own sessions, permissions, evidence provenance and scheduling.
Each subject/topic still needs content, skill/outcome modelling, input/rendering,
valid assessment rules and quality evaluation. Open-ended work may need different
evidence structures from the current binary maths outcomes. This should be
specified rather than assuming the existing verifier and mastery rules apply
unchanged everywhere.

## Planning consequences of the continuous platform

The clarification strengthens several future workstreams:

1. **Curriculum identity and versioning:** school/course, year, syllabus,
   learning objectives, required methods and exam dates; decide how this is
   entered, imported, reviewed and kept current.
2. **Persistent learner state:** durable accounts, topics, attempts, assistance,
   mastery and history with access controls and resumable work.
3. **Personal home and navigation:** current course, next activity, review due,
   progress and unfinished work without having to prompt an agent to reconstruct it.
4. **Ongoing planning:** reconcile prerequisites, curriculum pace, exams and
   retention, with an understandable reason for the recommended task.
5. **Subject expansion:** validated adapters/content and appropriate evidence,
   not merely a broader tutor prompt. Full coverage will be incremental.
6. **Institutional boundary:** decide which functions we own and where existing
   LMS platforms provide enrolment, materials, assignments and reporting.

These are planning implications; this comparison does not silently reprioritise
the existing implementation plan. Difficulty bands/calibration remain captured in
the [difficulty follow-up](../superpowers/notes/2026-11-01-exercise-difficulty-follow-up.md).

## Competitive conclusion and validation questions

The stronger product description is **a curriculum-linked personal learning
environment connecting teaching, practice, independent evidence and retention**.
That is more precise than “AI tutor”, but the matrix does not establish uniqueness
or superiority. Persistent pathways and broad subjects already exist in several
forms. The hypothesis to test is whether LearnAI can deliver this combination
better for a specific learner population and curriculum.

Prioritise demonstrations of StudyFetch, CENTURY, Khan Academy/Khanmigo and the
relevant institutional LMS. Use the same course segment and learner scenarios:

- Does the student resume at a useful next step without reconstructing context?
- Is the actual syllabus represented, including changes and exam requirements?
- What happens after help, a wrong answer, a prerequisite gap or a long absence?
- Can we distinguish remembered answers, assisted success and delayed independent performance?
- How does assessment work for history or writing, where several responses can be valid?
- What must the school configure, and how much ongoing effort does that require?

Results, learner usability and operating cost should determine positioning. An
undocumented competitor implementation detail is not a defensible advantage.

## Evidence maintenance

The matrix's source codes map to named links in the HTML and workbook. The
builder and JSON preserve cell-level provenance and status. Update them together
when a demo or new documentation changes a finding. Older documentation is noted;
confirm feature access in the target institution and market before sales use.
