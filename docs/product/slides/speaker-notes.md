# LearnAI — Presenter notes

25 slides · approximately 25 minutes · snapshot 1 November 2026

## 01. From helpful answers to lasting understanding

Open with the learning outcome, not the technology. LearnAI is intended to connect explanation, practice, independent evidence and retention across subjects and ages. Today this is a development-stage quadratics Practice engine, not a deployed student-facing product. This snapshot includes work awaiting integration. Suggested session: 20 minutes of presentation, followed by decisions together.

## 02. Understanding an explanation is only the start

This is our motivating hypothesis, not a measured result. Following a worked solution and solving a new problem independently are different experiences. Retention adds a third test: can the learner still do it after time has passed? Assistance should be welcomed; our progress evidence should remember how a success was achieved. We have not yet demonstrated learning gains with students.

## 03. Start narrow. Build for a broader horizon.

The long-term audience spans primary school, high school and early university. That is a vision, not current curriculum coverage. The existing 12-skill quadratics cluster makes a secondary-school pilot practical, but does not establish the best market entry point. We must choose the learner, geography, curriculum, language and buyer together. Physics is the original proposed second-subject test; other examples are possibilities.

## 04. One useful session, connected to the next

The first four stages have underlying engine support, but none has a product UI yet. A student can submit an answer or share a draft question with partial work. Checks and revision-aware history ground the tutor. The engine records assistance separately from independent evidence. Later scheduled retrieval is planned. Avoid making hints an endless loop: support should leave useful work to do, and escalate when the learner remains stuck.

## 05. Four modes. One implemented engine path.

Practice is the current engine path. Review has memory/freshness foundations but not a due queue, cards or a full mode. Learn is intended to estimate the learner's knowledge across the skill graph, identify ready-to-learn skills and teach from that frontier with progressively faded worked examples. Full Test/mock-exam orchestration and diagnostics remain planned. General policy contracts do not mean all modes are available. All still need a student-facing product experience.

## 06. Learn: start at the edge of what you know

Learner question: What am I ready to learn next? Learn should gauge the student's knowledge across the skill graph and build from the frontier between established knowledge and skills not yet learned. This is the founder's clarified product intent, consistent with the original design's placement and frontier sections (7.6–7.7). Use existing evidence and targeted checks where confidence is missing; do not assume every session needs a full placement test. Knowledge is an estimate, not a binary truth or one global level. There may be several frontier skills in different branches. A candidate skill needs sufficiently fresh prerequisite evidence; repair a weak prerequisite before advancing. The illustrated graph is simplified, not an exact rendering of repository skill edges. Teaching moves from worked examples to increasingly incomplete examples and then independent problems. Immediate post-instruction success is weak evidence of lasting mastery; later cold checks matter. Placement, Learn orchestration and the complete teaching experience remain planned. The exact diagnostic policy is not finalized by this slide.

## 07. Practice: turn understanding into capability

Learner question: Can I use what I have learned? Practice builds fluency and independence through varied problems. The learner attempts a problem, can share partial working or ask a specific question, receives help appropriate to the difficulty and tries again. The exercise and dialogue on this slide are illustrative, not a transcript or shipped UI. Valid alternative methods should be recognized. Help remains available without pretending assisted success is independent mastery. After instruction or a reveal, even a fresh immediate variant remains post-instruction evidence; later unaided performance is the stronger signal. Practice engine orchestration, supported verification, help permissions and assistance-aware evidence exist today. The student interface and durable product service do not.

## 08. Review: keep previous learning available

Learner question: Can I still recall and use this? Review is spaced retrieval of previously learned knowledge, not a replay of the explanation. The planned scheduler selects due skills and declarative cards; procedural checks use fresh exercise variants. The timeline is conceptual and does not commit fixed intervals. Try recalling before help so the initial performance remains informative. Under the current design, a lapse gets brief correction and a scheduling update; deeper tutoring is an explicit switch to Practice, preserving a short review session. Repeated lapses can reveal a prerequisite that needs rebuilding. Strength/stability/freshness foundations exist, but the due queue, cards, Review mode and full scheduling experience are not implemented.

## 09. Test: see what you can do without help

Learner question: What can I do independently across the target skills? The planned assessment experience uses selected or mixed skills, with help withheld during the test. Mock exams add timing and a course/exam blueprint; not every independent check needs to be timed. Results and diagnostic guidance arrive after the assessment has ended, not between turns while it is still underway. The intended outcome is a useful picture of strengths and gaps to inform later learning and practice. A short checkpoint already described inside Practice is not a separate fifth mode or a complete mock exam product. Full assessment orchestration, reporting and curriculum/exam configuration remain planned; existing help-policy abstractions do not make this a usable mode today.

## 10. Revisit. Retrieve. Reinforce.

We intend to combine two research-backed principles. Spacing distributes encounters with material over time; retrieval practice asks the learner to recall or solve before seeing the answer. Cepeda et al. (2008) experimentally varied study gaps and final-test delays: useful spacing depended on the retention horizon, and ever-longer gaps were not always better. Roediger and Karpicke (2006) found that retrieval practice improved delayed recall of prose passages compared with equivalent restudy. These findings support the direction, not a guarantee that LearnAI's particular scheduler or mathematics pedagogy is effective. Our application is to schedule brief recall cards and fresh procedural problems, lengthening intervals when evidence supports it and revisiting sooner after lapses. The timeline illustrates a successful-retrieval path, with no fixed intervals or measured retention values. LearnAI already implements memory stability, estimated retrievability and due-time calculations; the full due queue, cards and Review scheduler remain planned. The model parameters and learning outcomes need calibration with students. Sources: Cepeda et al., Spacing effects in learning (2008), https://pubmed.ncbi.nlm.nih.gov/19076480/ ; Roediger & Karpicke, Test-enhanced learning (2006), https://pubmed.ncbi.nlm.nih.gov/16507066/ . Repository: src/learnai/domain/mastery.py and planner.py; platform design sections 7.2 and 8.4.

## 11. Elo: match the challenge to the learner

Elo is a rating method originally associated with chess: results update ratings relative to what the competing ratings predicted. In our educational adaptation, compare a learner's estimated strength in a particular skill with the exercise's difficulty to predict success. Update the skill estimate using the difference between actual and expected performance, scaled by the update rate and evidence weight. Holding those factors equal, an unexpected success raises the estimate more than a predictable success; an unexpected failure lowers it more. Assisted evidence has zero strength-update weight, while immediate post-instruction evidence has low weight. The skill estimate is not an intelligence score or a cross-subject ranking. Strength updates and difficulty targeting are implemented; item difficulties currently come from authored/generated content, not a fully deployed joint item-calibration system. There is currently one fixed-difficulty template per skill, so the target cannot yet select an easier or harder template within that skill; generated variants inherit that same rating. The planner targets about 75% predicted success as a configurable starting policy, not a measured rate, universal optimum, or guarantee that available items exactly meet the target. Memory stability/freshness is a separate estimate for when to review. Educational precedent: Klinkenberg, Straatemeier & van der Maas (2011), Computer adaptive practice of Maths ability using a new item response model for on the fly ability and difficulty estimation, https://dare.uva.nl/id/de65bb65-d198-4dbc-ac7b-bc25ca23e627 ; https://doi.org/10.1016/j.compedu.2011.02.003 . That study used a richer scoring model incorporating accuracy and response time; LearnAI does not reproduce it exactly. Code: src/learnai/domain/mastery.py, planner.py and parameters.py. Our calibration still needs learner data.

## 12. A substantial foundation already exists

These capabilities exist in the current development workspace, which includes changes awaiting integration. There are 12 skill definitions and 12 deterministic generator templates. Verification handles bounded mathematical forms and supported partial work; it is not an arbitrary proof checker. Evidence storage is in memory; history retrieval is current-session only. Anthropic and OpenAI have separate tutor and evaluator configuration. Detailed implementation evidence is linked in the source brief.

## 13. The engine decides. The model explains.

Ordinary code owns help permissions, evidence and mastery updates. The AI tutor has no direct mastery-write tool. Responses pass delivery validation, but that guard cannot guarantee mathematical or pedagogical correctness. Implemented stack: Python 3.12+, SymPy, YAML, pytest/Hypothesis and provider adapters. FastAPI, PostgreSQL and React/TypeScript are proposed for the product layer. Evidence/events are in memory today. Each connector in this diagram represents an interaction, not a full network-service topology.

## 14. Encouraging signals. A small evidence base.

Latest recorded full keyless suite: 1,869 passed, four live probes deselected. This test count is software verification, not educational effectiveness, and was not rerun for this presentation. The fresh live batch had 14 scenarios, 13 accepted replies and one delivery failure. Median latency of accepted replies was 2.7 seconds (n=13), not a production SLO. All 13 delivered responses received user-confirmed ratings through assistant-facilitated review. Frozen automated-judge comparison remains pending. No learning gains or demand have yet been validated.

## 15. An accepted answer can still be wrong

This is a paraphrase of one reviewed scenario, not a verbatim transcript. The student asked about subtracting 2 while solving x−2=0; the tutor incorrectly endorsed that operation when adding 2 was needed. Other reviewed cases assumed the referent of a negative sign, provided dense or excessive guidance, or failed delivery after malformed output. These are useful concrete targets for calibration. Several other replies handled conceptual questions and alternative methods well. Keep failures visible; do not turn acceptance rates into quality claims.

## 16. Make explanations readable by design

The structured tutor-content design is a reviewed draft awaiting approval and implementation. First version: paragraphs, lists and inline/display equations. This diagram is a product concept, not a working UI. The engine must validate the same semantic content the learner sees; provider output, history and evaluation must evolve together. Subject/topic boundaries should allow reusable later types such as reaction notation or timelines. Structured content does not itself ensure good pedagogy, and answers should not all become lists.

## 17. Turn the engine into one useful student session

No application server, authenticated product API, durable database or frontend currently exists in this workspace. The next product milestone combines four workstreams. Session data must persist and be safely scoped across sessions. The input experience needs direct learner testing. Operational work includes error/recovery flows, deployment and real cost accounting; OpenAI monetary accounting is currently incomplete despite usage tracking. Before use with minors, review appropriate account/data handling and applicable privacy requirements. Pilot recruitment and content review are product work, not merely infrastructure.

## 18. Two workstreams, one path to a pilot

This is a dependency sequence, not a dated commitment. Engineering: finish current quality calibration and integrate pending work; approve and implement structured presentation; build the persistent Practice product; run a bounded pilot. In parallel: decide the learner and need, prototype maths entry, identify buyer/distribution, recruit and agree success measures. Review follows with a real due queue, followed by Learn, curriculum/placement/assessment and second-subject expansion. Discovery should not wait for every technical foundation to be finished.

## 19. Keep the core generic. Prove each subject.

The subject-neutral engine already separates content and verification behind interfaces. Mathematics is the only implemented subject. Physics is the original proposed second-subject test. Chemistry/history examples illustrate a future extension boundary, not committed roadmap releases. Each expansion needs appropriate content, verification, pedagogy and evaluation; adding a model prompt is not enough. Future typed blocks may differ by topic while common interaction/evidence logic remains shared. Cross-subject portability is not yet validated.

## 20. Adaptive learning already has strong players.

Public vendor documentation reviewed 1 November 2026; not hands-on product testing. Not verified means unknown from the reviewed sources, not absent. No scoring or superiority claim. LearnAI current is an implemented engine foundation; full roadmap is intended future capability. The roadmap is a persistent personal learning home linked to the student's school/university curriculum: their courses, topics and progress, automatically resuming and recommending next steps. It targets maths, chemistry, history, English and other subjects incrementally, with subject-specific checks. Existing platforms already offer continuity, diagnostics and review. Khan Academy's mastery-challenge reference is a 2020 guide; availability must be checked for a purchase. ALEKS recurring knowledge checks are not the same implementation as memory-timed flashcards.

Companion matrix: ../competitor-matrix/learnai-competitor-matrix.html (keep the sibling competitor-matrix folder when sharing the local link). Full comparison and caveats: docs/product/2026-11-01-competitor-matrix.md.

Sources:
K1: Khan Academy — Khanmigo development report, May 2026 — https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/
K2: Khan Academy — Course mastery goals — https://en.khanacademy.org/khan-for-educators/khan-for-educators-advanced-course/x2e5750eab575b791%3Akhan-for-educators-advanced/x2e5750eab575b791%3Amastery-learning-on-khan-academy/a/how-to-assign-mastery-goals-a9
K3: Khan Academy — Mastery challenges (2020 guide) — https://www.khanacademy.org/resources/teacher-essentials/product-tour-videos/a/mastery-challenges-course-mastery
K4: Khan Academy — Khanmigo overview — https://www.khanacademy.org/khan-labs
A1: McGraw Hill — ALEKS platform — https://www.mheducation.com/highered/digital-products/aleks.html
A2: McGraw Hill — ALEKS learner FAQ — https://www.mheducation.com/prek-12/support/knowledge/aleks-frequently-asked-questions-faq-for-students.html
A3: McGraw Hill — ALEKS quizzes, tests and homework — https://www.mheducation.com/prek-12/support/knowledge/new-aleks---quiz-test-homework.html
C1: CENTURY — Teacher introduction — https://knowledge.century.tech/teacher-introduction-to-century
C2: CENTURY — Science and Memory Boost — https://www.century.tech/news/the-science-behind-century/
C3: CENTURY — Student workspace — https://knowledge.century.tech/what-do-students-see

## 21. Study tools are becoming learning homes.

Public vendor documentation reviewed 1 November 2026; not hands-on product testing. Not verified means unknown from the reviewed sources, not absent. No scoring or superiority claim. LearnAI current is an implemented engine foundation; full roadmap is intended future capability. The roadmap is a persistent personal learning home linked to the student's school/university curriculum: their courses, topics and progress, automatically resuming and recommending next steps. It targets maths, chemistry, history, English and other subjects incrementally, with subject-specific checks. StudyFetch materially overlaps our intended continuous syllabus-led experience; do not portray all alternatives as one-off chats. Quizlet spaced repetition is documented for web, and Ask Quizlet currently has US/14+ availability and chat resets across page changes; saved study paths still persist. Broad uploaded-material or model reach does not prove equally reliable subject-specific assessment.

Companion matrix: ../competitor-matrix/learnai-competitor-matrix.html (keep the sibling competitor-matrix folder when sharing the local link). Full comparison and caveats: docs/product/2026-11-01-competitor-matrix.md.

Sources:
S1: StudyFetch — Study Plan — https://sso.studyfetch.com/docs/docs/product-docs/6a519349893cd6f616be1054
S2: StudyFetch — Product overview — https://www.studyfetch.com/
S3: StudyFetch — Flashcards and spaced repetition — https://sso.studyfetch.com/docs/docs/product-docs/6a52628f02a11a95bc7fcc0e
S4: StudyFetch — Canvas integration — https://sso.studyfetch.com/docs/docs/product-docs/6a067a051289ddc3f19038b2
Q1: Quizlet — Study paths — https://help.quizlet.com/hc/en-us/articles/360048314692-Setting-up-a-study-path
Q2: Quizlet — Study activities and grading — https://help.quizlet.com/hc/en-au/articles/360030841732-Studying-on-Quizlet
Q3: Quizlet — Spaced repetition — https://help.quizlet.com/hc/en-us/articles/48324742264077-Studying-with-Spaced-Repetition
Q4: Quizlet — Ask Quizlet and current restrictions — https://help.quizlet.com/hc/en-us/articles/42790350723725-Studying-with-Ask-Quizlet
Q5: Quizlet — Class Progress — https://quizlet.com/features/class-progress
O1: OpenAI — Using study mode — https://help.openai.com/en/articles/11780217-using-study-mode-in-chatgpt

## 22. School continuity is already a baseline.

Public vendor documentation reviewed 1 November 2026; not hands-on product testing. Not verified means unknown from the reviewed sources, not absent. No scoring or superiority claim. LearnAI current is an implemented engine foundation; full roadmap is intended future capability. The roadmap is a persistent personal learning home linked to the student's school/university curriculum: their courses, topics and progress, automatically resuming and recommending next steps. It targets maths, chemistry, history, English and other subjects incrementally, with subject-specific checks. LMS platforms already provide persistent institutional workflows and are adding AI. Hosting any subject is different from providing a validated content catalogue and assessment engine for every subject. Canvas Mastery Paths use instructor-configured score branches; Blackboard outcome mastery derives from aligned assessments. Neither is evidence of a full autonomous prerequisite diagnosis and memory scheduler. Full LMS replacement, administration and gradebook scope remain open decisions for LearnAI.

Companion matrix: ../competitor-matrix/learnai-competitor-matrix.html (keep the sibling competitor-matrix folder when sharing the local link). Full comparison and caveats: docs/product/2026-11-01-competitor-matrix.md.

Sources:
I1: IXL — Curriculum and textbook alignment — https://www.ixl.com/
I2: IXL — Diagnostic — https://www.ixl.com/diagnostic/info?lmsPlatform=1
I3: IXL — Instructional resources — https://blog.ixl.com/2021/12/02/ixls-instructional-resources-tools-to-power-learning-at-home/
I4: IXL — Personalized practice guide — https://www.ixl.com/materials/i_guides/IXL_for_Personalized_Practice_Implementation_Guide.pdf
I5: IXL — EU teacher guide; saved practice — https://eu.ixl.com/userguides/eu/IXLUserGuide.pdf
V1: Canvas — Mastery Paths — https://community.canvaslms.com/t5/Canvas-Basics-Guide/What-is-Mastery-Paths/ta-p/404483
V2: Canvas — Available IgniteAI features — https://community.instructure.com/en/kb/articles/664510-what-are-the-available-ai-features-in-canvas
V3: Canvas — LMS tiers and availability — https://www.instructure.com/products/canvas-tiers
B1: Blackboard — AVA student assistant — https://help.anthology.com/blackboard/student/en/course-content-and-materials/ava-ai-virtual-assistant.html
B2: Blackboard — AI Conversation — https://help.anthology.com/blackboard/student/en/course-content-and-materials/ai-conversation.html
B3: Blackboard — Outcomes and mastery — https://help.anthology.com/blackboard/student/en/grades/blackboard-outcomes.html

## 23. Earn trust in independent progress

This is a proposed positioning hypothesis, not a demonstrated competitive advantage. We should not claim uniqueness for AI tutoring, Elo, skill graphs, spaced repetition or mathematical checking. OpenAI describes Study mode's guided questions and understanding checks (https://help.openai.com/en/articles/11780217-using-study-mode-in-chatgpt). McGraw Hill describes ALEKS knowledge checks and adaptive learning paths (https://www.mheducation.com/highered/digital-products/aleks.html). Khan Academy reports mathematical checking, learner-history experiments and unaided next-item outcome measurement in its May 2026 Khanmigo report (https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/). These are first-party descriptions, not a head-to-head benchmark. Our intended offer connects useful help, assistance-aware independent evidence and later retrieval for a specific learner need. Supported checks and evidence contracts exist; the full persistent product and spaced-review experience do not. Why buy rather than build? A capable organisation can build. The potential value is avoiding ongoing content, verification, calibration, product and operational work, if we demonstrate a better result and acceptable total effort. We have not established lower cost or superior outcomes. Why buy from us rather than another vendor is a separate question requiring customer discovery and comparative evidence. Possible advantages to earn: curriculum/language fit, usable maths input, calibrated content, learning outcomes, workflow fit and trusted distribution. None is claimed as proven today. Build can be rational for buyers with strong teams or core product/control requirements. No API or white-label business model is implied. Detailed sources and pilot questions: docs/product/2026-11-01-positioning-and-build-vs-buy.md.

## 24. Measure what students can do later

The primary outcome hypothesis is better independent performance on fresh problems after a delay. No numerical thresholds are agreed; choose them with a pilot population and baseline. Separate learning outcomes from engagement and software reliability. Four evidence groups matter: unaided/delayed success; completion and input friction; incorrect/missing replies and recovery; repeat need, willingness to pay and fully accounted cost per useful session. These metrics are proposed for the pilot, not measured achievements.

## 25. Choose one learner. One problem. One useful session.

Close with joint decisions rather than a sales pitch. The business/product co-founder can lead discovery, buyer/distribution validation and pilot design alongside engineering. Decide the initial student group and learning moment, country/curriculum/language, who pays and how we reach them, the input experience to prototype, and the evidence that justifies the next investment. Pricing, launch dates and market-size claims are intentionally not invented. Source: docs/product/2026-11-01-cofounder-brief.md and its technical reading section. Brief: https://chatgpt.com/space/page_69f590c2b0688191b452e138672dd156 . Snapshot includes development work awaiting integration.

Sources: [Cofounder brief](../2026-11-01-cofounder-brief.md), [platform design](../../superpowers/specs/2026-09-14-ai-tutoring-platform-design.md), and the founder's clarification of Learn as estimating and expanding the knowledge frontier.

Research references:

- [Cepeda et al. (2008): Spacing effects in learning](https://pubmed.ncbi.nlm.nih.gov/19076480/) — timing depends on the retention horizon.
- [Roediger & Karpicke (2006): Test-enhanced learning](https://pubmed.ncbi.nlm.nih.gov/16507066/) — retrieval practice and delayed recall.
- [Klinkenberg et al. (2011): Computer adaptive practice of Maths ability](https://dare.uva.nl/id/de65bb65-d198-4dbc-ac7b-bc25ca23e627) — an educational adaptation of Elo-style estimation.

These studies motivate design choices; none validates LearnAI's implementation or establishes its learning outcomes.


## Difficulty follow-up for presenters

The current catalogue has one fixed-difficulty template per skill. The planner computes a target, but the registry cannot yet choose an easier or harder template within that skill, and generated variants inherit the same rating. Present this as a difficulty-targeting foundation. Multiple bands or controlled generation and empirical calibration remain future work. See the [planning note](../../superpowers/notes/2026-11-01-exercise-difficulty-follow-up.md). This addendum supplements the existing exported deck.
