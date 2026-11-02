"""Generate a local, sourced competitor matrix as HTML, XLSX and JSON.

Run with xlsxwriter installed in a separate documentation environment.
No network requests, external assets, scores or invented feature absences.
"""
from pathlib import Path
import html
import json
import xlsxwriter

OUT = Path(__file__).resolve().parent
DATE = "2026-11-01"
SOURCES = {
    "O1": ("OpenAI — Using study mode", "https://help.openai.com/en/articles/11780217-using-study-mode-in-chatgpt"),
    "S1": ("StudyFetch — Study Plan", "https://sso.studyfetch.com/docs/docs/product-docs/6a519349893cd6f616be1054"),
    "S2": ("StudyFetch — Product overview", "https://www.studyfetch.com/"),
    "S3": ("StudyFetch — Flashcards and spaced repetition", "https://sso.studyfetch.com/docs/docs/product-docs/6a52628f02a11a95bc7fcc0e"),
    "S4": ("StudyFetch — Canvas integration", "https://sso.studyfetch.com/docs/docs/product-docs/6a067a051289ddc3f19038b2"),
    "Q1": ("Quizlet — Study paths", "https://help.quizlet.com/hc/en-us/articles/360048314692-Setting-up-a-study-path"),
    "Q2": ("Quizlet — Study activities and grading", "https://help.quizlet.com/hc/en-au/articles/360030841732-Studying-on-Quizlet"),
    "Q3": ("Quizlet — Spaced repetition", "https://help.quizlet.com/hc/en-us/articles/48324742264077-Studying-with-Spaced-Repetition"),
    "Q4": ("Quizlet — Ask Quizlet and current restrictions", "https://help.quizlet.com/hc/en-us/articles/42790350723725-Studying-with-Ask-Quizlet"),
    "Q5": ("Quizlet — Class Progress", "https://quizlet.com/features/class-progress"),
    "K1": ("Khan Academy — Khanmigo development report, May 2026", "https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/"),
    "K2": ("Khan Academy — Course mastery goals", "https://en.khanacademy.org/khan-for-educators/khan-for-educators-advanced-course/x2e5750eab575b791%3Akhan-for-educators-advanced/x2e5750eab575b791%3Amastery-learning-on-khan-academy/a/how-to-assign-mastery-goals-a9"),
    "K3": ("Khan Academy — Mastery challenges (2020 guide)", "https://www.khanacademy.org/resources/teacher-essentials/product-tour-videos/a/mastery-challenges-course-mastery"),
    "K4": ("Khan Academy — Khanmigo overview", "https://www.khanacademy.org/khan-labs"),
    "A1": ("McGraw Hill — ALEKS platform", "https://www.mheducation.com/highered/digital-products/aleks.html"),
    "A2": ("McGraw Hill — ALEKS learner FAQ", "https://www.mheducation.com/prek-12/support/knowledge/aleks-frequently-asked-questions-faq-for-students.html"),
    "A3": ("McGraw Hill — ALEKS quizzes, tests and homework", "https://www.mheducation.com/prek-12/support/knowledge/new-aleks---quiz-test-homework.html"),
    "C1": ("CENTURY — Teacher introduction", "https://knowledge.century.tech/teacher-introduction-to-century"),
    "C2": ("CENTURY — Science and Memory Boost", "https://www.century.tech/news/the-science-behind-century/"),
    "C3": ("CENTURY — Student workspace", "https://knowledge.century.tech/what-do-students-see"),
    "I1": ("IXL — Curriculum and textbook alignment", "https://www.ixl.com/"),
    "I2": ("IXL — Diagnostic", "https://www.ixl.com/diagnostic/info?lmsPlatform=1"),
    "I3": ("IXL — Instructional resources", "https://blog.ixl.com/2021/12/02/ixls-instructional-resources-tools-to-power-learning-at-home/"),
    "I4": ("IXL — Personalized practice guide", "https://www.ixl.com/materials/i_guides/IXL_for_Personalized_Practice_Implementation_Guide.pdf"),
    "I5": ("IXL — EU teacher guide; saved practice", "https://eu.ixl.com/userguides/eu/IXLUserGuide.pdf"),
    "V1": ("Canvas — Mastery Paths", "https://community.canvaslms.com/t5/Canvas-Basics-Guide/What-is-Mastery-Paths/ta-p/404483"),
    "V2": ("Canvas — Available IgniteAI features", "https://community.instructure.com/en/kb/articles/664510-what-are-the-available-ai-features-in-canvas"),
    "V3": ("Canvas — LMS tiers and availability", "https://www.instructure.com/products/canvas-tiers"),
    "B1": ("Blackboard — AVA student assistant", "https://help.anthology.com/blackboard/student/en/course-content-and-materials/ava-ai-virtual-assistant.html"),
    "B2": ("Blackboard — AI Conversation", "https://help.anthology.com/blackboard/student/en/course-content-and-materials/ai-conversation.html"),
    "B3": ("Blackboard — Outcomes and mastery", "https://help.anthology.com/blackboard/student/en/grades/blackboard-outcomes.html"),
    "L1": ("LearnAI — Implemented state / cofounder brief", "../2026-11-01-cofounder-brief.md"),
    "L2": ("LearnAI — Product design and roadmap", "../../superpowers/specs/2026-09-14-ai-tutoring-platform-design.md"),
    "L3": ("LearnAI — Difficulty implementation gaps", "../../superpowers/notes/2026-11-01-exercise-difficulty-follow-up.md"),
    "L4": ("LearnAI — Structured content proposal", "../../superpowers/specs/2026-10-31-structured-tutor-content-design.md"),
    "L5": ("Founder clarification — persistent curriculum-linked platform", "../2026-11-01-competitor-matrix.md#product-intent"),
}
STATUS = {
    "D": ("Documented", "Public first-party documentation describes the capability; not independently tested."),
    "S": ("Scoped", "Related capability exists, but with the limitation described in the cell."),
    "N": ("Not verified", "Not established in the reviewed sources. This does not mean absent."),
    "F": ("Foundation", "LearnAI engine/code exists, with no complete student product for this capability."),
    "P": ("Planned", "LearnAI roadmap or stated product intent; not a shipped capability."),
    "B": ("Not built", "Known implementation gap in the current LearnAI workspace."),
    "O": ("Open decision", "Possible extension or integration whose scope is not committed."),
}
FEATURES = [
    ("subjects", "Subject coverage", "platform", "Distinguish curated subject content, uploaded material, and an LMS hosting arbitrary courses."),
    ("curriculum", "School / university curriculum", "platform", "Actual syllabus/course alignment, not merely asking a chatbot about a topic."),
    ("workspace", "Persistent student workspace", "platform", "Saved personal courses, topics and progress across visits; session memory alone is narrower."),
    ("next", "What to study next", "platform", "Recommendations or automatic sequencing without needing a fresh prompt each session."),
    ("diagnostic", "Placement / knowledge gaps", "platform", "Assessment of starting knowledge and readiness; recommendation logic need not be a prerequisite graph."),
    ("tutor", "Contextual tutoring", "learning", "Interactive or instructional support, with the actual scope described."),
    ("modes", "Learn / practise / review / test", "learning", "Functional coverage, not matching product feature names or equal mode permissions."),
    ("retention", "Spaced / delayed review", "learning", "Distinguish memory-based scheduling from periodic reassessment or a flashcard button."),
    ("independence", "Assistance vs independence", "learning", "Evidence of unaided competence, separately from success while receiving tutoring."),
    ("assessment", "Subject-appropriate assessment", "learning", "Supported grading/checks/rubrics; not a guarantee of correctness across every discipline."),
    ("materials", "Course materials / rich content", "delivery", "Files, images, other inputs and subject/topic-specific presentation."),
    ("institution", "School / university workflows", "delivery", "Assignments, reporting and integrations; not all products are full LMS alternatives."),
]

def cell(value):
    parts=value.split("|",2)
    status, detail = parts[:2]
    refs=parts[2].split() if len(parts)>2 else []
    assert status in STATUS
    assert all(ref in SOURCES for ref in refs)
    return {"status":status,"detail":detail,"sources":refs}

ROWS=[]
def row(name,group,audience,scope,values):
    assert len(values)==len(FEATURES), name
    ROWS.append({"name":name,"group":group,"audience":audience,"scope":scope,
                 "cells":{f[0]:cell(v) for f,v in zip(FEATURES,values)}})

row("LearnAI — current", "LearnAI", "Development engine; no deployed student UI", "Current worktree, including work awaiting integration.", [
    "F|Maths: 12 quadratics skills.|L1",
    "B|No operational curriculum overlay or enrolment.|L1 L2",
    "B|In-memory state; no persistent student dashboard.|L1",
    "F|Prerequisite frontier selection; difficulty bands still missing.|L1 L3",
    "F|Skill graph/state; full placement experience pending.|L1 L2",
    "F|Anthropic/OpenAI; revision-aware current-session tutoring.|L1",
    "F|Practice engine; other complete modes pending.|L1",
    "F|Memory/due-time calculations; no Review scheduler.|L1",
    "F|Assistance-aware evidence and mastery updates.|L1",
    "F|Supported maths forms/steps checked with SymPy.|L1",
    "F|Text/formula items; richer tutor blocks are a design draft.|L1 L4",
    "B|No institutional service, teacher UI or LMS integration.|L1",
])
row("LearnAI — full roadmap", "LearnAI", "Primary → high school → early university", "Target product, not availability, validated effectiveness or a dated commitment.", [
    "P|Any-subject ambition: maths, chemistry, history, English, more.|L2 L5",
    "P|Student's actual school/uni curriculum, syllabus and exams.|L2 L5",
    "P|Dedicated home, personal topics and durable cross-session progress.|L5",
    "P|Choose next learning/review from readiness, retention and curriculum.|L2 L5",
    "P|Locate knowledge frontier; repair prerequisites and advance.|L2 L5",
    "P|Tutor grounded in course, current work and longitudinal evidence.|L2 L5",
    "P|Integrated Learn, Practice, Review and Test/mock exams.|L2",
    "P|Scheduled retrieval, cards and fresh procedural checks.|L2",
    "P|Keep assistance visible; later unaided evidence of competence.|L2",
    "P|Subject-specific verifiers/rubrics; quality validated per subject.|L2 L5",
    "P|Own problems later; extensible blocks. Photo/interactive scope open.|L2 L4",
    "O|Curriculum-linked experience intended; LMS sync/admin scope undecided.|L5",
])
row("StudyFetch", "AI study tools", "Students and institutional offerings", "Course-material-based platform; Canvas integration requires institutional setup.", [
    "S|Broad subject reach through supplied course materials.|S2",
    "D|Syllabus and exam dates shape topic order.|S1",
    "D|Saved Study Sets, topic progress and mastery markers.|S1 S3",
    "D|Recommended topics and an ordered continuing study plan.|S1",
    "S|Topic pre-assessments; full prerequisite graph not verified.|S1",
    "D|Sparky and Tutor Me support course-material study.|S2",
    "D|Tutoring, quizzes, flashcards and practice exams.|S2",
    "D|Flashcard scheduling based on recall ratings.|S3",
    "N|Assistance-weighted mastery rules not established.|S1",
    "S|Topic assessments/tests; independent subject verifiers not established.|S1 S2",
    "D|Materials, lecture capture and generated audio/visual study aids.|S2",
    "S|Canvas login and course-material import; not full LMS parity.|S4",
])
row("Khan Academy + Khanmigo", "Adaptive learning", "School learners; subject/level and tutor access vary", "Compare the combined learning platform and tutor, not Khanmigo chat alone.", [
    "S|Multi-subject course/tutoring offer; coverage varies.|K4",
    "S|Teachers assign goals within available Khan courses.|K2",
    "D|Continuing course mastery goals and learner history.|K1 K2",
    "S|Mastery challenges and prerequisite-oriented tutor interventions.|K1 K3",
    "S|Course mastery and prerequisite evidence; scope varies.|K1 K2",
    "D|Tutor sees exercises; history and maths-checking work documented.|K1",
    "S|Course mastery/practice, review challenges and tutoring.|K1 K2 K3",
    "D|Personalised spaced review through mastery challenges.|K3",
    "S|Tracks unaided next-item performance; full help-weight policy unverified.|K1",
    "S|Maths verification reported; not all-subject proof of correctness.|K1",
    "N|Arbitrary school-syllabus ingestion not established in this review.|K2 K4",
    "D|Teacher class/course goals and learner monitoring.|K2 K4",
])
row("ALEKS", "Adaptive learning", "School and higher education; course dependent", "Course-based adaptive learning in its supported subject catalogue.", [
    "S|Maths and chemistry; not an all-subject catalogue.|A1",
    "D|Course learning paths plus instructor assignments.|A1 A3",
    "D|Personal knowledge state and continuing learning/review paths.|A2",
    "D|Individual paths; unretained topics return for relearning.|A2",
    "D|Initial and recurring knowledge checks identify gaps.|A1 A2",
    "N|General conversational tutor not established by reviewed pages.|A1",
    "D|Learning, review, knowledge checks, quizzes/tests/homework.|A2 A3",
    "S|Periodic retention checks and review; not the same as card scheduling.|A2",
    "S|Knowledge checks re-establish competence; exact help-weight rules unverified.|A2",
    "D|Supported maths/chemistry assessments and algorithmic questions.|A1 A3",
    "S|Course questions; arbitrary learner-material ingestion not established.|A1 A3",
    "D|Instructor assignments and progress/gap reporting.|A1 A3",
])
row("CENTURY", "Adaptive learning", "Primary/secondary and specified post-16 content", "Catalogue, curriculum and exam-board scope vary by offering.", [
    "S|English, maths, science; selected geography, PE and post-16 content.|C1",
    "D|National-curriculum/exam-board courses and teacher-set work.|C1",
    "D|Learner dashboard, usage and personal recommendations.|C3",
    "D|Continuously adapting pathways and prerequisite links.|C1 C2",
    "D|Identifies knowledge gaps to target resources.|C1",
    "S|Instruction, feedback and misconception remediation; chat unverified.|C1 C2",
    "S|Learning content, assessments and recommended review; exams scope unverified.|C2",
    "D|Memory Boost incorporates spaced retrieval.|C2",
    "N|Explicit assisted-vs-unaided mastery accounting not established.|C2",
    "S|Question feedback and performance analytics; subject scope bounded.|C2",
    "S|Authored learning content; arbitrary learner uploads not established.|C1 C2",
    "D|Classes, assignments, teacher and learner dashboards.|C1 C2 C3",
])
row("IXL", "Adaptive learning", "Primarily school-level personalised practice", "Diagnostic coverage is narrower than overall subject coverage.", [
    "S|Maths, language arts, science, social studies and Spanish.|I1",
    "D|Skills mapped to standards and textbook chapters.|I1",
    "D|Saved practice and personalised recommendation wall.|I4 I5",
    "D|Recommendations update as the student practises.|I2 I4",
    "S|Diagnostic and action plans in maths and language arts.|I2",
    "S|Worked examples/error explanations; conversational tutor unverified.|I3",
    "S|Lessons, adaptive practice and diagnostics; full mock-exam scope unverified.|I2 I3",
    "N|Memory-timed spaced-review scheduler not established.|I2 I3",
    "N|Explicit help-weighted competence model not established.|I2 I3",
    "D|Skill questions, immediate feedback and diagnostics.|I2 I3",
    "S|Lessons/examples and textbook mapping; arbitrary uploads unverified.|I1 I3",
    "D|Teacher analytics and implementation workflows.|I4 I5",
])
row("Quizlet", "AI study tools", "Broad study use; feature/region/age restrictions", "Plus study paths; Ask Quizlet currently US age 14+; spaced repetition web-only in reviewed docs.", [
    "S|Broad subject coverage via sets, guides and uploaded materials.|Q2 Q4",
    "S|Teacher/user sets can match class content; full syllabus orchestration unverified.|Q2 Q5",
    "S|Study-path progress saved; Ask Quizlet chat resets across pages.|Q1 Q4",
    "S|Adaptive sequence within sets; broader course sequencing unverified.|Q1",
    "S|Adapts to familiarity with a set; prerequisite placement unverified.|Q1 Q2",
    "S|Ask Quizlet explanations and follow-ups, with access restrictions.|Q4",
    "D|Learn, flashcards, tests, study guides and AI explanations.|Q2 Q4",
    "D|Recall-rated spaced repetition for flashcards on web.|Q3",
    "N|Longitudinal help-weighted mastery accounting not established.|Q1 Q2",
    "S|Smart grading and expert solutions; not universal verification.|Q2",
    "D|Files/images, audio and diagram sets; feature limits apply.|Q2 Q4",
    "S|Classes and Class Progress; full LMS workflows not established.|Q5",
])
row("ChatGPT / Study mode", "AI study tools", "Broad subject conversation; access and memory settings vary", "Study mode is a conversational learning experience. Do not equate optional memory with a curriculum mastery database.", [
    "S|Broad topic reach through the model and supplied material.|O1",
    "S|Uses a supplied syllabus/materials; managed curriculum mapping unverified.|O1",
    "S|Chat and optional memory; dedicated course-mastery dashboard unverified.|O1",
    "S|Can guide the next step in dialogue; persistent curriculum scheduler unverified.|O1",
    "S|Asks understanding questions; validated prerequisite placement unverified.|O1",
    "D|Guided questions, layered explanations and feedback.|O1",
    "S|Learning, practice, quizzes and review via conversation.|O1",
    "N|Automatic memory-based review scheduler not established for Study mode.|O1",
    "N|Separate assisted/independent mastery ledger not established.|O1",
    "S|Model feedback can be wrong; checked all-subject grading unverified.|O1",
    "D|Course files, images, PDFs and supported voice input.|O1",
    "S|Edu/teen controls documented; full course-LMS workflows not assessed.|O1",
])
row("Canvas LMS + IgniteAI", "Institutional LMS", "Institution-managed school/university courses", "AI and Mastery Paths depend on institution enablement/configuration; compare documented native features.", [
    "S|Hosts institution-authored courses across subjects; not a vetted content catalogue.|V1 V2",
    "D|Institution's actual courses, assignments and learning content.|V1 V2",
    "D|Persistent student courses, work and gradebook context.|V1 V2",
    "S|Instructor-configured score-based Mastery Paths.|V1",
    "S|Assignment-score branching; autonomous prerequisite diagnosis unverified.|V1",
    "S|Course-grounded AI study aids; full mastery-aware tutor unverified.|V2",
    "D|Course content, quizzes, assessments and AI study materials.|V1 V2",
    "N|Native student-memory spaced-review scheduler not established.|V2",
    "N|Tutor-assistance-weighted mastery ledger not established.|V1 V2",
    "S|Quizzes, rubrics and educator grading; varies by course design.|V1 V2",
    "D|Course files/pages; AI summaries, quizzes and flashcards.|V2",
    "D|Full LMS setting; tiers and enabled AI options vary.|V2 V3",
])
row("Blackboard LMS + AI", "Institutional LMS", "Institution-managed school/university courses", "AVA, AI Conversation and Outcomes availability depends on institutional/course configuration.", [
    "S|Hosts any course subject; learning content supplied by institution.|B1 B2",
    "D|Actual course content, assignments and institutional outcomes.|B1 B3",
    "D|Persistent course progress, grades and enabled Outcomes views.|B1 B3",
    "S|Modules/instructor workflow; autonomous skill scheduler unverified.|B1",
    "S|Outcome mastery from aligned assessments; prerequisite placement unverified.|B3",
    "S|Instructor-defined Socratic/role-play/quiz AI activities; AVA has scope limits.|B1 B2",
    "D|Course activities/assessments plus configured AI conversations.|B2 B3",
    "N|Student-memory spaced-review scheduler not established.|B1 B3",
    "N|Tutor-assistance-weighted mastery ledger not established.|B3",
    "S|Outcome-aligned educator assessments; course-specific rubrics/processes.|B3",
    "S|Course materials supported; AVA document access has explicit limits.|B1",
    "D|Institutional courses, instructor workflows and grade/outcome records.|B1 B3",
])

INTRO = "A persistent, curriculum-linked learning home: each student has personal topics, progress and next steps across subjects. Compare LearnAI's implemented engine separately from its full intended platform."
CAUTION = "Snapshot: 1 November 2026. First-party documentation review, not hands-on benchmarking. Not verified means unknown, not absent. Subject breadth is not the same as validated teaching or assessment. No weighted scores or winner ranking. Competitors will also evolve."
ROADMAP = [
    ("Now", "Practice engine", "Quadratics, supported verification, tutor context, evidence and evaluation. No persistent student UI."),
    ("Near term", "Usable continuous product", "Quality/content presentation, authentication, storage, student workspace and resumable learning."),
    ("Planned", "Review + Learn", "Scheduled retrieval; knowledge-frontier placement and teaching with fading support."),
    ("Planned", "Curriculum-linked study", "Course overlays, syllabus topics, school/uni progression, exams and ongoing next-step planning. Mapping/import workflow still needs design."),
    ("Long term", "Any subject", "Maths, chemistry, history, English and other disciplines. Original sequence proposes physics as the first second-subject test; each needs content and suitable assessment."),
    ("Later / open", "Materials and richer interaction", "Bring-your-own problems with follow-up practice; subject-specific blocks. Photo input, interactive elements and exact timing remain open."),
    ("Open", "Institutional delivery model", "Decide LMS complement versus replacement, integrations, teacher/parent views and administration. Student curriculum alignment does not settle these."),
]
data={"as_of":DATE,"intro":INTRO,"caution":CAUTION,"statuses":STATUS,
      "features":[dict(zip(("id","label","group","definition"),f)) for f in FEATURES],
      "products":ROWS,"sources":{k:{"title":v[0],"url":v[1],"reviewed":DATE,"kind":"repository/founder" if k.startswith("L") else "first-party documentation"} for k,v in SOURCES.items()},
      "roadmap":ROADMAP}
(OUT/"matrix-data.json").write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")

STYLE="""
:root{--ink:#173744;--muted:#536b73;--bg:#f5f3ec;--teal:#127c72;--line:#d9e2dd}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,sans-serif}header,main{max-width:1600px;margin:auto;padding:32px 36px}header{padding-bottom:12px}.eyebrow{font-size:12px;letter-spacing:.13em;font-weight:800;color:var(--teal)}h1{font-size:clamp(28px,4vw,48px);line-height:1.1;margin:14px 0}h2{font-size:25px}p{max-width:1050px}.muted,small{color:var(--muted)}.vision{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:26px 0}.vision div{background:#173744;color:#fff;padding:18px;border-radius:12px}.vision strong{display:block;color:#d9ef9f}.vision span{font-size:14px}.toolbar{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:18px 0}label{font-size:13px;font-weight:650}select,input,button{padding:10px 12px;background:white;border:1px solid #a6b9b0;border-radius:8px;color:var(--ink);font:inherit}input{min-width:230px}button{cursor:pointer}button.active{background:var(--teal);color:white}.tabs{display:flex;gap:8px;flex-wrap:wrap}.legend{display:flex;gap:9px;flex-wrap:wrap;margin:18px 0}.badge{display:inline-block;border-radius:5px;padding:3px 7px;font-size:11px;font-weight:750;white-space:nowrap}.D{background:#d4eadf;color:#14543f}.S{background:#deebf3;color:#274c64}.N{background:#e9eceb;color:#536364}.F{background:#fff0cf;color:#775614}.P{background:#e8e2f7;color:#564480}.B{background:#f5e1dc;color:#864738}.O{background:#eee7d8;color:#6b5c40}.tablewrap{overflow:auto;max-height:760px;border:1px solid var(--line);border-radius:12px;background:white}table{border-collapse:separate;border-spacing:0;width:100%;font-size:14px}th,td{padding:14px 16px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);vertical-align:top;min-width:225px;max-width:265px}thead th{position:sticky;top:0;background:#173744;color:white;z-index:3;text-align:left;font-size:13px}tr th:first-child{position:sticky;left:0;background:#f4f7f4;z-index:2;min-width:220px;text-align:left}thead th:first-child{background:#173744;z-index:4}.ours th:first-child{border-left:5px solid #16877f;background:#eaf3eb}.ours td{background:#fafbf6}.celltext{display:block;margin-top:7px}.refs{font-size:11px;margin-top:7px}a{color:#126c75;text-underline-offset:3px}.refs a{margin-right:6px}th small{display:block;font-weight:400;margin-top:6px;font-size:11px}.panel{background:white;border:1px solid var(--line);border-radius:14px;padding:20px 24px;margin:20px 0}.sources{columns:2;column-gap:35px}.source{break-inside:avoid;margin-bottom:12px;font-size:13px}.source:target{background:#fff0cf}summary{cursor:pointer;font-weight:700}.download{font-weight:700}.mobilehint{font-size:13px}footer{padding:24px 36px;color:var(--muted)}@media(max-width:750px){header,main{padding:20px 14px}.vision{grid-template-columns:1fr 1fr}.sources{columns:1}th,td{min-width:195px;padding:11px}.tablewrap{max-height:650px}tr th:first-child{min-width:170px}}@media print{.toolbar,.tabs,.download{display:none}.tablewrap{max-height:none;overflow:visible}table{font-size:9px}th,td{min-width:0;padding:6px}header,main{padding:12px}.vision{margin:10px 0}thead th,tr th:first-child{position:static}.sources{columns:2}}
"""
esc=html.escape
source_html="".join(f'<div class="source" id="source-{k}"><strong>{k}</strong> · <a href="{esc(v[1])}" target="_blank" rel="noopener">{esc(v[0])}</a><br><small>Reviewed {DATE} · {"Local evidence / founder intent" if k.startswith("L") else "First-party documentation"}</small></div>' for k,v in SOURCES.items())
payload=json.dumps(data,ensure_ascii=False).replace("<","\\u003c")
page='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LearnAI · Competitor matrix</title><style>'''+STYLE+'''</style></head><body>
<header><div class="eyebrow">LEARN AI / FOUNDER RESEARCH / 01 NOV 2026</div><h1>A learning home, built around the student.</h1><p>'''+esc(INTRO)+'''</p><div class="vision"><div><strong>Personal</strong><span>Dedicated topics and progress</span></div><div><strong>Curriculum-linked</strong><span>The student's actual school or uni</span></div><div><strong>Continuous</strong><span>A useful next step each visit</span></div><div><strong>Across subjects</strong><span>Full-roadmap ambition, staged delivery</span></div></div><p class="muted">'''+esc(CAUTION)+'''</p></header>
<main><div class="download"><a href="learnai-competitor-matrix.xlsx">Open editable spreadsheet</a> · <a href="../2026-11-01-competitor-matrix.md">Read the assessment and roadmap</a></div>
<section aria-labelledby="compare-title"><h2 id="compare-title">9 competitors · LearnAI now · LearnAI roadmap</h2><div class="tabs" role="group" aria-label="Comparison dimensions"><button data-view="platform" class="active" aria-pressed="true">Curriculum & continuity</button><button data-view="learning" aria-pressed="false">Learning experience</button><button data-view="delivery" aria-pressed="false">Materials & institutions</button><button data-view="all" aria-pressed="false">All dimensions</button></div>
<div class="toolbar"><label>Competitor group <select id="group"><option value="all">All competitors</option><option>Adaptive learning</option><option>AI study tools</option><option>Institutional LMS</option></select></label><label>Search <input id="search" placeholder="Product, curriculum, chemistry…" type="search"></label><button id="reset">Reset</button><span id="count" aria-live="polite"></span></div><div id="legend" class="legend"></div><p class="mobilehint">LearnAI rows stay visible. Scroll sideways for wider views. Source codes open the evidence list; row notes explain availability.</p><div class="tablewrap" tabindex="0" aria-label="Scrollable comparison matrix"><table id="matrix"></table></div><noscript><p>Enable JavaScript for filtering, or open the spreadsheet linked above.</p></noscript></section>
<section class="panel"><h2>How to read the overlap</h2><p><strong>Continuity is already a competitive category.</strong> StudyFetch describes syllabus-driven study plans; CENTURY and IXL describe ongoing personalised pathways. Canvas and Blackboard connect learning to institutional courses and are adding AI. Check scope rather than assuming these are one-off chats.</p><p><strong>Unknown is not a missing feature.</strong> Public pages rarely disclose exact help-weighted mastery rules, verifier architecture or scheduler parameters. Treat those cells as product-demo questions, not evidence of exclusivity.</p><p><strong>Any subject is a coverage strategy.</strong> Upload-based breadth, an LMS hosting a history course, and reliable assessment of historical argument are different capabilities. LearnAI's intent includes each subject's content, pedagogy and assessment.</p></section>
<section class="panel"><h2>Full LearnAI roadmap lens</h2><div id="roadmap"></div></section><details class="panel" open><summary>Sources and definitions</summary><p class="muted">Availability may vary by subscription, age, region, institution and course. Public descriptions are not performance benchmarks. Older manuals are labelled where applicable.</p><div id="definitions"></div><h2>Evidence links</h2><div class="sources">'''+source_html+'''</div></details></main><footer>Generated locally. No external scripts, tracking or network requests on page load. Pricing and comparative learning outcomes are outside this feature review.</footer>
<script id="data" type="application/json">'''+payload+'''</script><script>
const D=JSON.parse(document.getElementById('data').textContent);let view='platform';
const h=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
document.getElementById('legend').innerHTML=Object.entries(D.statuses).map(([k,v])=>`<span class="badge ${k}" title="${h(v[1])}">${h(v[0])}</span>`).join('');
function render(){const group=document.getElementById('group').value,q=document.getElementById('search').value.toLowerCase();const cols=D.features.filter(f=>view==='all'||f.group===view);const rows=D.products.filter(p=>p.group==='LearnAI'||((group==='all'||p.group===group)&&JSON.stringify(p).toLowerCase().includes(q)));document.getElementById('count').textContent=`${rows.length-2} competitors shown`;
document.getElementById('matrix').innerHTML=`<thead><tr><th scope="col">Product / scope</th>${cols.map(f=>`<th scope="col" title="${h(f.definition)}">${h(f.label)}</th>`).join('')}</tr></thead><tbody>${rows.map(p=>`<tr class="${p.group==='LearnAI'?'ours':''}"><th scope="row">${h(p.name)}<small>${h(p.audience)}</small><details><summary>Scope</summary><small>${h(p.scope)}</small></details></th>${cols.map(f=>{const c=p.cells[f.id];return `<td><span class="badge ${c.status}">${h(D.statuses[c.status][0])}</span><span class="celltext">${h(c.detail)}</span><div class="refs">${c.sources.map(id=>`<a href="#source-${id}" data-source="${id}" title="${h(D.sources[id].title)}">${id}</a>`).join('')}</div></td>`}).join('')}</tr>`).join('')}</tbody>`;}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{view=b.dataset.view;document.querySelectorAll('[data-view]').forEach(x=>{x.classList.toggle('active',x===b);x.setAttribute('aria-pressed',String(x===b))});render()});
document.getElementById('group').onchange=render;document.getElementById('search').oninput=render;document.getElementById('reset').onclick=()=>{document.getElementById('group').value='all';document.getElementById('search').value='';document.querySelector('[data-view="platform"]').click()};
document.addEventListener('click',e=>{if(e.target.dataset.source)document.querySelector('details.panel').open=true});
document.getElementById('roadmap').innerHTML=D.roadmap.map(r=>`<p><span class="badge P">${h(r[0])}</span> <strong>${h(r[1])}</strong> — ${h(r[2])}</p>`).join('');
document.getElementById('definitions').innerHTML=D.features.map(f=>`<p><strong>${h(f.label)}:</strong> ${h(f.definition)}</p>`).join('');render();
</script></body></html>'''
(OUT/"learnai-competitor-matrix.html").write_text(page)

wb=xlsxwriter.Workbook(OUT/"learnai-competitor-matrix.xlsx")
wb.set_properties({"title":"LearnAI competitor matrix","subject":"Current offerings versus full intended roadmap","author":"LearnAI"})
head=wb.add_format({"bold":True,"bg_color":"#173744","font_color":"white","text_wrap":True,"valign":"top"})
body=wb.add_format({"text_wrap":True,"valign":"top","font_color":"#173744"})
title=wb.add_format({"bold":True,"font_size":22,"font_color":"#173744"})
link=wb.add_format({"font_color":"#126C75","underline":True,"text_wrap":True,"valign":"top"})
fills={"D":"#D4EADF","S":"#DEEBF3","N":"#E9ECEB","F":"#FFF0CF","P":"#E8E2F7","B":"#F5E1DC","O":"#EEE7D8"}
fmt={k:wb.add_format({"text_wrap":True,"valign":"top","bg_color":v,"font_color":"#173744"}) for k,v in fills.items()}
read=wb.add_worksheet("Read me");read.set_column(0,0,24);read.set_column(1,5,20)
read.merge_range(0,0,1,5,"LearnAI · Competitor matrix",title)
for ri,t in [(3,INTRO),(6,CAUTION),(9,"9 competitors plus LearnAI current and full roadmap. A coloured cell describes scope, not a score. Sources and evidence are filterable in separate sheets."),(12,"The student's own curriculum, persistent workspace and automatic next steps are intended product requirements. Full LMS replacement and integration scope remain open.")]:
    read.merge_range(ri,0,ri+1,5,t,body);read.set_row(ri,30)
for ri,(k,(label,desc)) in enumerate(STATUS.items(),16):
    read.write(ri,0,label,fmt[k]);read.merge_range(ri,1,ri,5,desc,body);read.set_row(ri,32)
for group,label in [("platform","Curriculum and continuity"),("learning","Learning experience"),("delivery","Materials and institutions")]:
    sh=wb.add_worksheet(label[:31]);cols=[f for f in FEATURES if f[2]==group]
    sh.set_column(0,0,31);sh.set_column(1,len(cols),36);sh.freeze_panes(2,1)
    sh.merge_range(0,0,0,len(cols),f"{label} · {DATE} · Read the status and scope together",head)
    sh.write_row(1,0,["Product / scope"]+[f[1] for f in cols],head);sh.set_row(1,32)
    for ri,p in enumerate(ROWS,2):
        sh.write(ri,0,p['name']+'\n'+p['audience'],body);sh.set_row(ri,100)
        sh.write_comment(ri,0,p['scope'])
        for ci,f in enumerate(cols,1):
            c=p['cells'][f[0]];refs=' '.join(c['sources'])
            sh.write(ri,ci,STATUS[c['status']][0]+'\n'+c['detail']+('\nSources: '+refs if refs else ''),fmt[c['status']])
            sh.write_comment(ri,ci,f[3]+'\n\n'+'\n'.join(f'{sid}: {SOURCES[sid][1]}' for sid in c['sources']))
    sh.autofilter(1,0,len(ROWS)+1,len(cols));sh.set_landscape();sh.fit_to_pages(1,0);sh.repeat_rows(0,1)
ev=wb.add_worksheet("Evidence");ev.write_row(0,0,["Product","Dimension","Status","Finding","Source IDs","Source URLs"],head);ev.freeze_panes(1,2)
ev.set_column(0,0,29);ev.set_column(1,1,30);ev.set_column(2,2,17);ev.set_column(3,3,65);ev.set_column(4,4,16);ev.set_column(5,5,75)
ri=1
for p in ROWS:
    for f in FEATURES:
        c=p['cells'][f[0]];ev.write_row(ri,0,[p['name'],f[1],STATUS[c['status']][0],c['detail'],' '.join(c['sources']),'\n'.join(SOURCES[sid][1] for sid in c['sources'])],body);ev.set_row(ri,52);ri+=1
ev.autofilter(0,0,ri-1,5)
ss=wb.add_worksheet("Sources");ss.write_row(0,0,["ID","Title","Link","Reviewed","Kind"],head);ss.freeze_panes(1,0)
ss.set_column(0,0,9);ss.set_column(1,1,56);ss.set_column(2,2,85);ss.set_column(3,3,16);ss.set_column(4,4,29)
for ri,(sid,source) in enumerate(data['sources'].items(),1):
    ss.write(ri,0,sid,body);ss.write(ri,1,source['title'],body)
    url=source['url'];ss.write_url(ri,2,url if '://' in url else 'external:'+url,link,url)
    ss.write(ri,3,DATE,body);ss.write(ri,4,source['kind'],body);ss.set_row(ri,44)
ss.autofilter(0,0,len(SOURCES),4)
rs=wb.add_worksheet("LearnAI roadmap");rs.write_row(0,0,["Stage","Capability","Scope"],head);rs.set_column(0,0,20);rs.set_column(1,1,34);rs.set_column(2,2,100)
for ri,r in enumerate(ROADMAP,1):rs.write_row(ri,0,r,body);rs.set_row(ri,55)
rs.freeze_panes(1,0)
wb.close()
print(f"Built {len(ROWS)} product rows × {len(FEATURES)} dimensions; {len(SOURCES)} sources; HTML, XLSX and JSON.")
