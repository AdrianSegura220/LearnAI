"""Build the local founder deck; no network calls or project-runtime dependencies.

Install python-pptx, reportlab and pillow in a separate environment, then run this
file. PowerPoint shapes/text remain editable. PDF and preview use the same layout.
"""
from pathlib import Path
import math
import json
import textwrap

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import MSO_ANCHOR
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

OUT = Path(__file__).resolve().parent
PREVIEW = OUT / "previews"
PREVIEW.mkdir(exist_ok=True)
W, H = 1280, 720
SLIDE_COUNT = 25
DECK_STEM = "learnai-cofounder-v3"
NAVY, INK, IVORY = "142D3B", "193643", "F7F4ED"
TEAL, LIME, AMBER = "16877F", "D7ED9B", "F1C477"
MUTED, WHITE, PALE, DARKCARD = "63757C", "FFFFFF", "E5EDE7", "234250"
FONT_DIR = Path("/System/Library/Fonts/Supplemental")
REG, BOLD = FONT_DIR / "Arial.ttf", FONT_DIR / "Arial Bold.ttf"
pdfmetrics.registerFont(TTFont("Deck", str(REG)))
pdfmetrics.registerFont(TTFont("DeckBold", str(BOLD)))

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333333), Inches(7.5)
prs.core_properties.title = "LearnAI — From helpful answers to lasting understanding"
prs.core_properties.subject = "Cofounder onboarding — 1 November 2026"
prs.core_properties.author = "LearnAI"
pdf = canvas.Canvas(str(OUT / f"{DECK_STEM}.pdf"), pagesize=(W, H))
pdf.setTitle(prs.core_properties.title)
notes, checks, slides = [], [], []

def rgb(c):
    return RGBColor.from_string(c)

def color(c):
    return tuple(int(c[i:i+2], 16) / 255 for i in (0, 2, 4))

class Slide:
    def __init__(self, title, section, dark=False, note=""):
        self.n = len(slides) + 1
        self.title, self.dark = title, dark
        self.bg, self.fg = (NAVY, IVORY) if dark else (IVORY, INK)
        self.s = prs.slides.add_slide(prs.slide_layouts[6])
        self.s.background.fill.solid()
        self.s.background.fill.fore_color.rgb = rgb(self.bg)
        self.im = Image.new("RGB", (W, H), "#" + self.bg)
        self.d = ImageDraw.Draw(self.im)
        pdf.setFillColorRGB(*color(self.bg))
        pdf.rect(0, 0, W, H, fill=1, stroke=0)
        self.text(64, 34, "LEARN AI", 15, LIME if dark else TEAL, True, 180)
        self.text(925, 34, section.upper(), 13, self.fg, False, 290)
        self.line(64, 670, 1216, 670, "385563" if dark else "D6DED7", 1)
        self.text(64, 684, "FOUNDER BRIEF  /  01 NOV 2026", 11, "B3C5CA" if dark else MUTED, w=570)
        self.text(1150, 682, f"{self.n:02d} / {SLIDE_COUNT}", 13, self.fg, w=100)
        self.s.notes_slide.notes_text_frame.text = note
        notes.append(f"## {self.n:02d}. {title}\n\n{note}\n")
        slides.append(self)

    def rect(self, x, y, w, h, fill, radius=0, stroke=None):
        shape = self.s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
                                       int(x*9525), int(y*9525), int(w*9525), int(h*9525))
        shape.fill.solid(); shape.fill.fore_color.rgb = rgb(fill)
        if stroke:
            shape.line.color.rgb = rgb(stroke); shape.line.width = Pt(.75)
        else:
            shape.line.fill.background()
        if radius:
            shape.adjustments[0] = min(.12, radius / min(w, h))
        self.d.rounded_rectangle((x, y, x+w, y+h), radius=radius, fill="#"+fill,
                                 outline="#"+stroke if stroke else None)
        pdf.setFillColorRGB(*color(fill))
        if stroke: pdf.setStrokeColorRGB(*color(stroke))
        pdf.roundRect(x, H-y-h, w, h, radius, fill=1, stroke=int(bool(stroke)))

    def circle(self, x, y, r, fill):
        sh = self.s.shapes.add_shape(MSO_SHAPE.OVAL, int((x-r)*9525), int((y-r)*9525), int(2*r*9525), int(2*r*9525))
        sh.fill.solid(); sh.fill.fore_color.rgb = rgb(fill); sh.line.fill.background()
        self.d.ellipse((x-r,y-r,x+r,y+r), fill="#"+fill)
        pdf.setFillColorRGB(*color(fill)); pdf.circle(x,H-y,r,fill=1,stroke=0)

    def line(self, x1,y1,x2,y2,c=TEAL,width=3,arrow=False):
        sh = self.s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, int(x1*9525),int(y1*9525),int(x2*9525),int(y2*9525))
        sh.line.color.rgb = rgb(c); sh.line.width = Pt(width*.75)
        self.d.line((x1,y1,x2,y2),fill="#"+c,width=max(1,round(width)))
        pdf.setStrokeColorRGB(*color(c)); pdf.setLineWidth(width); pdf.line(x1,H-y1,x2,H-y2)
        if arrow:
            a=math.atan2(y2-y1,x2-x1)
            for delta in (-.55,.55):
                self.line(x2,y2,x2-12*math.cos(a+delta),y2-12*math.sin(a+delta),c,width)

    def text(self,x,y,t,size=24,c=None,bold=False,w=1100,h=None):
        c = c or self.fg
        font = ImageFont.truetype(str(BOLD if bold else REG),size)
        lines=[]
        for para in t.split("\n"):
            line=""
            for word in para.split():
                candidate=(line+" "+word).strip()
                if font.getlength(candidate)>w and line:
                    lines.append(line); line=word
                else: line=candidate
            lines.append(line)
        leading=size*1.23
        height=len(lines)*leading+4
        if h is not None and height>h:
            raise ValueError(f"Slide {self.n} text exceeds height: {t}")
        if x+w>W+1 or y+height>H+1:
            raise ValueError(f"Slide {self.n} text out of page: {t}")
        checks.append({"slide":self.n,"text":t,"x":x,"y":y,"width":w,"height":height})
        for i,line in enumerate(lines):
            yy=y+i*leading
            self.d.text((x,yy),line,font=font,fill="#"+c,anchor="lt")
            pdf.setFont("DeckBold" if bold else "Deck",size)
            pdf.setFillColorRGB(*color(c)); pdf.drawString(x,H-yy-size*.91,line)
            box=self.s.shapes.add_textbox(int(x*9525),int((yy-2)*9525),int(w*9525),int((size*1.4)*9525))
            tf=box.text_frame; tf.clear(); tf.word_wrap=False
            tf.margin_left=tf.margin_right=tf.margin_top=tf.margin_bottom=0
            tf.vertical_anchor=MSO_ANCHOR.TOP
            p=tf.paragraphs[0]; p.space_before=p.space_after=Pt(0)
            run=p.add_run(); run.text=line
            run.font.name="Arial"; run.font.size=Pt(size*.75); run.font.bold=bold; run.font.color.rgb=rgb(c)
        return height

    def heading(self,t,sub=None):
        self.text(64,100,t,44,bold=True,w=1150,h=115)
        if sub: self.text(66,177,sub,21,"B3C5CA" if self.dark else MUTED,w=1130)

    def pill(self,x,y,label,kind="built",w=120):
        fill={"built":TEAL,"next":AMBER,"later":"DDE4DF","concept":LIME}[kind]
        self.rect(x,y,w,28,fill,12)
        self.text(x+12,y+6,label,12,WHITE if kind=="built" else INK,True,w-18)

    def card(self,x,y,w,h,title,body="",fill=None):
        fill=fill or (DARKCARD if self.dark else WHITE)
        self.rect(x,y,w,h,fill,16)
        self.text(x+24,y+23,title,27,bold=True,w=w-48)
        if body: self.text(x+24,y+78,body,21,"B3C5CA" if self.dark else MUTED,w=w-48,h=h-88)

    def finish(self):
        self.im.save(PREVIEW/f"slide-{self.n:02d}.png")
        pdf.showPage()

s=Slide("From helpful answers to lasting understanding","Vision",True,
"Open with the learning outcome, not the technology. LearnAI is intended to connect explanation, practice, independent evidence and retention across subjects and ages. Today this is a development-stage quadratics Practice engine, not a deployed student-facing product. This snapshot includes work awaiting integration. Suggested session: 20 minutes of presentation, followed by decisions together.")
s.text(64,120,"From helpful answers\nto lasting\nunderstanding.",60,bold=True,w=750)
s.text(68,385,"A learning platform built around what\nstudents can do independently.",26,"B3C5CA",w=690)
s.pill(68,500,"COFOUNDER ONBOARDING","concept",240)
s.text(68,552,"Engine foundation today.\nA student pilot next.",24,w=630)
for y,label,num,c in [(175,"UNDERSTAND","01",TEAL),(325,"PRACTISE","02",TEAL),(475,"RETAIN","03",LIME)]:
    if y<475:s.line(1000,y+50,1000,y+100,"54717B",3,True)
    s.circle(850,y+25,28,c);s.text(834,y+11,num,21,NAVY if c==LIME else WHITE,True,45)
    s.rect(900,y-13,300,77,DARKCARD,16);s.text(925,y+11,label,25,IVORY,True,260)
s.finish()

s=Slide("Understanding an explanation is only the start","The learning problem",note=
"This is our motivating hypothesis, not a measured result. Following a worked solution and solving a new problem independently are different experiences. Retention adds a third test: can the learner still do it after time has passed? Assistance should be welcomed; our progress evidence should remember how a success was achieved. We have not yet demonstrated learning gains with students.")
s.heading("Understanding an explanation\nis only the start.")
for x,num,title,body,c in [(64,"01","I can follow it.","Useful help in the moment",PALE),(463,"02","I can do it.","A fresh problem, independently",LIME),(862,"03","I still know it.","Evidence after a delay",WHITE)]:
    s.rect(x,275,354,260,c,18);s.text(x+25,300,num,52,TEAL,True,280)
    s.text(x+25,382,title,29,INK,True,310);s.text(x+25,435,body,22,MUTED,w=295)
    if x<862:s.line(x+363,405,x+387,405,TEAL,3,True)
s.text(64,588,"Our bet: connect all three into one focused learning experience.",26,INK,True,w=1120)
s.finish()

s=Slide("Start narrow. Build for a broader horizon.","Audience & scope",note=
"The long-term audience spans primary school, high school and early university. That is a vision, not current curriculum coverage. The existing 12-skill quadratics cluster makes a secondary-school pilot practical, but does not establish the best market entry point. We must choose the learner, geography, curriculum, language and buyer together. Physics is the original proposed second-subject test; other examples are possibilities.")
s.heading("Start narrow. Build for a broader horizon.","The first commercial segment is still a decision.")
for x,y,w,h,c in [(64,260,1152,345,PALE),(64,330,785,275,"C9DDD2"),(64,400,420,205,TEAL)]:s.rect(x,y,w,h,c,16)
s.text(90,285,"LONG-TERM VISION",14,TEAL,True,330)
s.text(510,290,"Primary → high school → early university",27,INK,True,670)
s.text(90,355,"PILOT HYPOTHESIS",14,INK,True,290)
s.text(510,374,"One student group.\nOne curriculum. One need.",25,INK,True,310)
s.text(90,425,"BUILT FOUNDATION",14,WHITE,True,320)
s.text(90,465,"Maths / Quadratics",30,WHITE,True,370)
s.text(90,521,"12 skills • Practice engine",22,WHITE,w=350)
s.text(884,445,"More subjects\nneed their own\ncontent + checks.",24,INK,w=275)
s.finish()

s=Slide("One useful session, connected to the next","Student experience",note=
"The first four stages have underlying engine support, but none has a product UI yet. A student can submit an answer or share a draft question with partial work. Checks and revision-aware history ground the tutor. The engine records assistance separately from independent evidence. Later scheduled retrieval is planned. Avoid making hints an endless loop: support should leave useful work to do, and escalate when the learner remains stuck.")
s.heading("One useful session, connected to the next.")
steps=[("Try","A focused\nproblem"),("Ask","Your work +\nyour question"),("Get help","One useful\nway forward"),("Show it","Try\nindependently"),("Return","A fresh check\nafter a delay")]
for i,(title,body) in enumerate(steps):
    x=64+i*236
    if i<4:s.line(x+56,315,x+270,315,"B9CEC4",4,True)
    s.circle(x+44,315,40,TEAL if i<4 else AMBER)
    s.text(x+35,296,str(i+1),30,WHITE if i<4 else INK,True,35)
    s.text(x,393,title,29,INK,True,218);s.text(x,443,body,22,MUTED,w=214)
s.rect(64,555,886,61,PALE,12);s.text(88,574,"Engine support exists • Student interface still to build",23,INK,w=845)
s.pill(1007,571,"PLANNED","next",155)
s.finish()

s=Slide("Four modes. One implemented engine path.","Product modes",True,note=
"Practice is the current engine path. Review has memory/freshness foundations but not a due queue, cards or a full mode. Learn is intended to estimate the learner's knowledge across the skill graph, identify ready-to-learn skills and teach from that frontier with progressively faded worked examples. Full Test/mock-exam orchestration and diagnostics remain planned. General policy contracts do not mean all modes are available. All still need a student-facing product experience.")
s.heading("Four modes. One implemented engine path.")
items=[(64,245,"Practice","Attempt. Ask. Adapt.","ENGINE BUILT","built"),(654,245,"Review","Retrieve before forgetting.","FOUNDATIONS ONLY","next"),(64,440,"Learn","Find your starting point. Build from there.","PLANNED","later"),(654,440,"Test","Demonstrate independence.","PLANNED","later")]
for x,y,title,body,status,kind in items:
    s.card(x,y,562,171,title,body);s.pill(x+320,y+24,status,kind,218)
s.finish()

s=Slide("Learn: start at the edge of what you know","Mode 1 / Learn",note=
"Learner question: What am I ready to learn next? Learn should gauge the student's knowledge across the skill graph and build from the frontier between established knowledge and skills not yet learned. This is the founder's clarified product intent, consistent with the original design's placement and frontier sections (7.6–7.7). Use existing evidence and targeted checks where confidence is missing; do not assume every session needs a full placement test. Knowledge is an estimate, not a binary truth or one global level. There may be several frontier skills in different branches. A candidate skill needs sufficiently fresh prerequisite evidence; repair a weak prerequisite before advancing. The illustrated graph is simplified, not an exact rendering of repository skill edges. Teaching moves from worked examples to increasingly incomplete examples and then independent problems. Immediate post-instruction success is weak evidence of lasting mastery; later cold checks matter. Placement, Learn orchestration and the complete teaching experience remain planned. The exact diagnostic policy is not finalized by this slide.")
s.heading("Learn: start at the edge of what you know.","“What am I ready to learn next?”")
s.pill(1035,177,"PLANNED","next",180)
s.rect(64,257,785,326,WHITE,16)
s.text(88,279,"ESTIMATED KNOWLEDGE",13,TEAL,True,260)
s.text(363,279,"READY TO LEARN",13,TEAL,True,240)
s.text(644,279,"LATER",13,MUTED,True,155)
# A branching prerequisite graph, rather than a single linear ability level.
for x1,y1,x2,y2 in [(298,353,365,403),(298,447,365,424),(575,414,643,414)]:
    s.line(x1,y1,x2,y2,"A7BFB2",3,True)
s.line(298,534,605,534,"A7BFB2",3)
s.line(605,534,605,449,"A7BFB2",3)
s.line(605,449,643,449,"A7BFB2",3,True)
for x,y,w,h,title,fill,c in [(88,322,210,67,"Expand brackets",TEAL,WHITE),(88,416,210,67,"Common factors",TEAL,WHITE),(88,510,210,51,"Linear equations",TEAL,WHITE),(365,371,210,88,"Factorise\nquadratics",LIME,INK),(643,371,180,88,"Solve by\nfactoring",PALE,INK)]:
    s.rect(x,y,w,h,fill,12)
    s.text(x+15,y+15,title,21,c,True,w-28)
s.text(370,477,"THE LEARNING\nFRONTIER",14,TEAL,True,225)
s.text(890,266,"Locate → build → check",24,INK,True,330)
for y,num,title,body in [(326,"01","Gauge your starting point","Use evidence + targeted checks."),(421,"02","Teach the next ready skill","Worked examples → less help."),(516,"03","Update the picture","Try independently; check later.")]:
    s.text(890,y,num,18,TEAL,True,40)
    s.text(930,y,title,21,INK,True,280)
    s.text(930,y+35,body,18,MUTED,w=280)
s.text(64,614,"Illustrative graph • Readiness can differ by branch; weak prerequisites need repair.",22,MUTED,w=1152)
s.finish()

s=Slide("Practice: turn understanding into capability","Mode 2 / Practice",True,note=
"Learner question: Can I use what I have learned? Practice builds fluency and independence through varied problems. The learner attempts a problem, can share partial working or ask a specific question, receives help appropriate to the difficulty and tries again. The exercise and dialogue on this slide are illustrative, not a transcript or shipped UI. Valid alternative methods should be recognized. Help remains available without pretending assisted success is independent mastery. After instruction or a reveal, even a fresh immediate variant remains post-instruction evidence; later unaided performance is the stronger signal. Practice engine orchestration, supported verification, help permissions and assistance-aware evidence exist today. The student interface and durable product service do not.")
s.heading("Practice: turn understanding into capability.","“Can I use what I have learned?”")
s.pill(1035,177,"ENGINE BUILT","built",180)
s.rect(64,255,435,324,IVORY,18)
s.text(88,279,"ILLUSTRATIVE EXERCISE",13,TEAL,True,380)
s.text(88,337,"x² − 5x + 6 = 0",39,INK,True,385)
s.text(88,419,"“I have (x − 2)(x − 3).\nWhat do I do next?”",25,INK,w=380)
s.text(88,519,"Working + a focused question",19,MUTED,w=380)
s.line(520,405,582,405,LIME,3,True)
s.rect(608,255,608,172,DARKCARD,16)
s.text(632,281,"HELP THAT LEAVES A NEXT STEP",14,LIME,True,555)
s.text(632,326,"“What does a product of zero\ntell you about the factors?”",28,IVORY,w=555)
s.rect(608,451,608,128,DARKCARD,16)
s.text(632,474,"Try again → build fluency → vary the problem",24,IVORY,True,558)
s.text(632,523,"Record how much help the attempt needed.",21,"B3C5CA",w=555)
s.text(64,614,"Help is welcome. Assisted success and independent evidence stay distinct.",24,LIME,True,w=1150)
s.finish()

s=Slide("Review: keep previous learning available","Mode 3 / Review",note=
"Learner question: Can I still recall and use this? Review is spaced retrieval of previously learned knowledge, not a replay of the explanation. The planned scheduler selects due skills and declarative cards; procedural checks use fresh exercise variants. The timeline is conceptual and does not commit fixed intervals. Try recalling before help so the initial performance remains informative. Under the current design, a lapse gets brief correction and a scheduling update; deeper tutoring is an explicit switch to Practice, preserving a short review session. Repeated lapses can reveal a prerequisite that needs rebuilding. Strength/stability/freshness foundations exist, but the due queue, cards, Review mode and full scheduling experience are not implemented.")
s.heading("Review: keep previous learning available.","“Can I still recall and use this?”")
s.pill(973,177,"MODE PLANNED","next",242)
s.line(144,318,1125,318,"ABC5B7",5,True)
for x,num,title,body,fill in [(100,"01","Learned earlier","Previous independent evidence",TEAL),(492,"02","Due for retrieval","A card or a fresh problem",TEAL),(884,"03","Update the schedule","Use recall evidence to plan ahead",TEAL)]:
    s.circle(x+40,318,36,fill);s.text(x+28,303,num,24,WHITE,True,45)
    s.text(x,386,title,27,INK,True,322);s.text(x,435,body,22,MUTED,w=305)
s.rect(64,534,1152,93,PALE,14)
s.text(88,553,"Forgot something?",25,INK,True,300)
s.text(415,552,"Brief correction + reschedule.\nChoose Practice if you want to work on it now.",23,INK,w=760)
s.finish()

s=Slide("Test: see what you can do without help","Mode 4 / Test",True,note=
"Learner question: What can I do independently across the target skills? The planned assessment experience uses selected or mixed skills, with help withheld during the test. Mock exams add timing and a course/exam blueprint; not every independent check needs to be timed. Results and diagnostic guidance arrive after the assessment has ended, not between turns while it is still underway. The intended outcome is a useful picture of strengths and gaps to inform later learning and practice. A short checkpoint already described inside Practice is not a separate fifth mode or a complete mock exam product. Full assessment orchestration, reporting and curriculum/exam configuration remain planned; existing help-policy abstractions do not make this a usable mode today.")
s.heading("Test: see what you can do without help.","“Where am I independent, and where are the gaps?”")
s.pill(1035,177,"PLANNED","next",180)
s.rect(64,263,700,292,DARKCARD,18)
s.text(88,289,"DURING THE ASSESSMENT",14,LIME,True,630)
for x,label in [(88,"Skill A"),(299,"Skill B"),(510,"Skill C")]:
    s.rect(x,343,188,77,NAVY,12);s.text(x+27,367,label,25,IVORY,True,150)
s.text(88,458,"Attempt independently • No hints or tutor feedback",24,IVORY,w=630)
s.text(88,505,"Mock exam: add timing + an exam blueprint.",20,"B3C5CA",w=630)
s.line(779,406,847,406,LIME,3,True)
s.rect(872,263,344,292,IVORY,18)
s.text(895,289,"AFTER FINISHING",14,TEAL,True,298)
s.text(895,349,"Your diagnostic\nreport",32,INK,True,296)
s.text(895,452,"Strengths • Gaps\nWhat to work on next",23,MUTED,w=292)
s.text(64,609,"Assess first. Explain the results and plan the next learning steps afterwards.",24,LIME,True,w=1150)
s.finish()

s=Slide("Revisit. Retrieve. Reinforce.","Learning science",note=
"We intend to combine two research-backed principles. Spacing distributes encounters with material over time; retrieval practice asks the learner to recall or solve before seeing the answer. Cepeda et al. (2008) experimentally varied study gaps and final-test delays: useful spacing depended on the retention horizon, and ever-longer gaps were not always better. Roediger and Karpicke (2006) found that retrieval practice improved delayed recall of prose passages compared with equivalent restudy. These findings support the direction, not a guarantee that LearnAI's particular scheduler or mathematics pedagogy is effective. Our application is to schedule brief recall cards and fresh procedural problems, lengthening intervals when evidence supports it and revisiting sooner after lapses. The timeline illustrates a successful-retrieval path, with no fixed intervals or measured retention values. LearnAI already implements memory stability, estimated retrievability and due-time calculations; the full due queue, cards and Review scheduler remain planned. The model parameters and learning outcomes need calibration with students. Sources: Cepeda et al., Spacing effects in learning (2008), https://pubmed.ncbi.nlm.nih.gov/19076480/ ; Roediger & Karpicke, Test-enhanced learning (2006), https://pubmed.ncbi.nlm.nih.gov/16507066/ . Repository: src/learnai/domain/mastery.py and planner.py; platform design sections 7.2 and 8.4.")
s.heading("Revisit. Retrieve. Reinforce.","Spaced repetition + retrieval practice: research-backed principles.")
s.rect(64,242,1152,228,WHITE,16)
s.text(88,260,"ILLUSTRATIVE SUCCESSFUL-RETRIEVAL PATH",13,TEAL,True,750)
s.line(130,340,1130,340,"AEC8B7",4,True)
for x,label,fill in [(132,"Learn",TEAL),(325,"Recall",TEAL),(645,"Recall again",TEAL),(1092,"Return later",TEAL)]:
    s.circle(x,340,24,fill)
    s.text(x-65,384,label,23,INK,True,155)
s.text(380,289,"Gaps can grow as recall becomes more secure",21,TEAL,True,710)
s.text(88,438,"A lapse brings the next check closer. Timing adapts; this is not a fixed calendar.",18,MUTED,w=1100)
for x,title,body in [(64,"SPACING","Revisit across time."),(655,"RETRIEVAL","Try recalling before seeing the answer.")]:
    s.rect(x,494,561,88,PALE,12);s.text(x+23,510,title,14,TEAL,True,510);s.text(x+23,541,body,24,INK,True,510)
s.text(64,603,"Memory foundations built • Review scheduler planned • LearnAI outcomes still to validate",21,INK,w=1150)
s.text(64,644,"Research: Cepeda et al. (2008); Roediger & Karpicke (2006). Links and scope in presenter notes.",13,MUTED,w=1150)
s.finish()

s=Slide("Elo: match the challenge to the learner","Adaptive difficulty",True,note=
"Elo is a rating method originally associated with chess: results update ratings relative to what the competing ratings predicted. In our educational adaptation, compare a learner's estimated strength in a particular skill with the exercise's difficulty to predict success. Update the skill estimate using the difference between actual and expected performance, scaled by the update rate and evidence weight. Holding those factors equal, an unexpected success raises the estimate more than a predictable success; an unexpected failure lowers it more. Assisted evidence has zero strength-update weight, while immediate post-instruction evidence has low weight. The skill estimate is not an intelligence score or a cross-subject ranking. Strength updates and difficulty targeting are implemented; item difficulties currently come from authored/generated content, not a fully deployed joint item-calibration system. There is currently one fixed-difficulty template per skill, so the target cannot yet select an easier or harder template within that skill; generated variants inherit that same rating. The planner targets about 75% predicted success as a configurable starting policy, not a measured rate, universal optimum, or guarantee that available items exactly meet the target. Memory stability/freshness is a separate estimate for when to review. Educational precedent: Klinkenberg, Straatemeier & van der Maas (2011), Computer adaptive practice of Maths ability using a new item response model for on the fly ability and difficulty estimation, https://dare.uva.nl/id/de65bb65-d198-4dbc-ac7b-bc25ca23e627 ; https://doi.org/10.1016/j.compedu.2011.02.003 . That study used a richer scoring model incorporating accuracy and response time; LearnAI does not reproduce it exactly. Code: src/learnai/domain/mastery.py, planner.py and parameters.py. Our calibration still needs learner data.")
s.heading("Elo: match the challenge to the learner.","A rating method from chess, adapted to learners and exercises.")
s.pill(1035,217,"CORE BUILT","built",180)
for x,title,body in [(64,"Compare","Skill strength\nwith exercise difficulty"),(465,"Predict","Estimate the chance\nof an unaided success"),(866,"Update","Compare the result\nwith that prediction")]:
    s.rect(x,273,350,169,DARKCARD,15);s.text(x+23,297,title,29,IVORY,True,300);s.text(x+23,357,body,23,"D2E2E3",w=305)
    if x<866:s.line(x+357,357,x+390,357,LIME,3,True)
s.text(64,471,"Surprising success → larger increase. Expected success → smaller increase.",24,LIME,True,w=1150)
s.rect(64,525,1152,72,IVORY,14)
s.text(88,549,"Skill strength → how challenging?",25,INK,True,535)
s.text(665,549,"Memory freshness → when to revisit?",25,INK,True,525)
s.text(64,615,"Per-skill estimate • Assistance-aware evidence • Calibration still needs student data",21,"B3C5CA",w=1150)
s.text(64,648,"Educational precedent: Klinkenberg, Straatemeier & van der Maas (2011). Source and limits in notes.",13,"B3C5CA",w=1150)
s.finish()

s=Slide("A substantial foundation already exists","Built in the workspace",note=
"These capabilities exist in the current development workspace, which includes changes awaiting integration. There are 12 skill definitions and 12 deterministic generator templates. Verification handles bounded mathematical forms and supported partial work; it is not an arbitrary proof checker. Evidence storage is in memory; history retrieval is current-session only. Anthropic and OpenAI have separate tutor and evaluator configuration. Detailed implementation evidence is linked in the source brief.")
s.heading("A substantial foundation already exists.","Implemented in the development workspace; not a deployed service.")
for x,num,label in [(64,"12","quadratics skills"),(445,"12","exercise templates"),(826,"2","AI providers")]:
    s.text(x,248,num,82,TEAL,True,325);s.text(x,343,label,24,INK,True,335)
for x,title,body in [(64,"Learning engine","Prerequisites\nAdaptive practice\nAssistance-aware evidence"),(455,"Grounded interaction","Maths + partial-work checks\nRevision-aware context\nControlled help"),(846,"Quality tooling","Bounded runtime\nSaved traces + replay\nRegression + live evaluation")]:
    s.rect(x,418,370,206,WHITE,16);s.text(x+22,441,title,25,INK,True,330);s.text(x+22,492,body,21,MUTED,w=330)
s.finish()

s=Slide("The engine decides. The model explains.","Architecture",True,note=
"Ordinary code owns help permissions, evidence and mastery updates. The AI tutor has no direct mastery-write tool. Responses pass delivery validation, but that guard cannot guarantee mathematical or pedagogical correctness. Implemented stack: Python 3.12+, SymPy, YAML, pytest/Hypothesis and provider adapters. FastAPI, PostgreSQL and React/TypeScript are proposed for the product layer. Evidence/events are in memory today. Each connector in this diagram represents an interaction, not a full network-service topology.")
s.heading("The engine decides. The model explains.")
s.rect(64,265,260,150,IVORY,15);s.text(88,293,"Student UI + API",26,INK,True,220);s.pill(88,350,"PLANNED","next",130)
s.rect(410,250,360,205,TEAL,18);s.text(443,282,"Practice engine",34,WHITE,True,300);s.text(443,343,"Permissions\nEvidence • Progress",25,WHITE,w=295)
s.line(324,340,410,340,LIME,3,True)
for y,title,sub in [(215,"Content + verifier","Exercises and supported checks"),(353,"AI tutor adapters","Anthropic / OpenAI")]:
    s.rect(855,y,360,112,DARKCARD,14);s.text(878,y+20,title,25,IVORY,True,315);s.text(878,y+65,sub,18,"B3C5CA",w=315)
    s.line(770,y+65,855,y+65,LIME,3,True)
s.line(590,455,590,520,LIME,3,True)
s.rect(410,520,360,104,DARKCARD,12);s.text(435,537,"Evidence + session history",23,IVORY,True,315);s.text(435,578,"IN MEMORY TODAY",15,LIME,True,315)
s.line(855,464,855,493,LIME,2);s.line(855,493,260,493,LIME,2);s.line(260,493,260,415,LIME,2,True)
s.text(64,547,"Response → engine validation\n→ student delivery",22,"B3C5CA",w=320)
s.text(855,550,"Durable storage +\ncross-session access: next",22,"B3C5CA",w=350)
s.finish()

s=Slide("Encouraging signals. A small evidence base.","What we know",note=
"Latest recorded full keyless suite: 1,869 passed, four live probes deselected. This test count is software verification, not educational effectiveness, and was not rerun for this presentation. The fresh live batch had 14 scenarios, 13 accepted replies and one delivery failure. Median latency of accepted replies was 2.7 seconds (n=13), not a production SLO. All 13 delivered responses received user-confirmed ratings through assistant-facilitated review. Frozen automated-judge comparison remains pending. No learning gains or demand have yet been validated.")
s.heading("Encouraging signals. A small evidence base.")
for x,num,label,detail in [(64,"1,869","keyless tests passed","Latest recorded full suite\n4 live probes deselected"),(455,"13 / 14","live replies accepted","One delivery failure\nSmall scenario batch"),(846,"2.7s","median accepted latency","13 accepted replies\nNot a production guarantee")]:
    s.rect(x,246,370,296,WHITE,16);s.text(x+24,275,num,65,TEAL,True,326);s.text(x+24,369,label,23,INK,True,326);s.text(x+24,425,detail,20,MUTED,w=320)
s.rect(64,574,1152,58,PALE,12);s.text(87,591,"Software evidence ≠ learning outcomes. Automated judge comparison is still pending.",23,INK,w=1110)
s.finish()

s=Slide("An accepted answer can still be wrong","What quality work revealed",True,note=
"This is a paraphrase of one reviewed scenario, not a verbatim transcript. The student asked about subtracting 2 while solving x−2=0; the tutor incorrectly endorsed that operation when adding 2 was needed. Other reviewed cases assumed the referent of a negative sign, provided dense or excessive guidance, or failed delivery after malformed output. These are useful concrete targets for calibration. Several other replies handled conceptual questions and alternative methods well. Keep failures visible; do not turn acceptance rates into quality claims.")
s.heading("An accepted answer can still be wrong.")
s.rect(64,246,610,329,IVORY,18);s.pill(88,269,"REVIEWED CASE · PARAPHRASED","next",315)
s.text(94,328,"x − 2 = 0",55,INK,True,540);s.text(94,405,"Student asks: “Subtract 2?”",28,INK,w=540)
s.text(94,465,"Tutor endorsed it.\nThe useful step was to add 2.",25,TEAL,True,540)
s.text(744,264,"Three priorities",31,IVORY,True,445)
for y,n,t in [(337,"01","Clarify ambiguity"),(416,"02","Check the actual advice"),(495,"03","Leave useful work to do")]:
    s.text(744,y,n,22,LIME,True,60);s.text(806,y,t,24,IVORY,w=400)
s.text(64,607,"Delivery checks are a guardrail, not a guarantee of teaching quality.",26,LIME,True,w=1150)
s.finish()

s=Slide("Make explanations readable by design","Next: presentation",note=
"The structured tutor-content design is a reviewed draft awaiting approval and implementation. First version: paragraphs, lists and inline/display equations. This diagram is a product concept, not a working UI. The engine must validate the same semantic content the learner sees; provider output, history and evaluation must evolve together. Subject/topic boundaries should allow reusable later types such as reaction notation or timelines. Structured content does not itself ensure good pedagogy, and answers should not all become lists.")
s.heading("Make explanations readable by design.","A shared content contract for the engine and the front end.")
s.pill(64,233,"DESIGN DRAFT","next",175)
for y,label,t in [(292,"PARAGRAPH","One clear idea."),(385,"LIST","A short sequence of steps."),(478,"EQUATION","x² − 5x + 6 = 0")]:
    s.rect(64,y,360,77,WHITE,12);s.text(84,y+12,label,12,TEAL,True,320);s.text(84,y+37,t,24,INK,w=320)
s.line(450,421,575,421,TEAL,3,True)
s.rect(606,248,610,351,NAVY,18);s.pill(632,270,"PRODUCT CONCEPT","concept",190)
s.text(638,329,"Look for two numbers.",29,IVORY,True,535)
s.text(638,391,"• Their product is 6.\n• Their sum is −5.",26,IVORY,w=525)
s.rect(638,484,540,76,DARKCARD,12);s.text(660,502,"Which pair would you try?",28,LIME,True,490)
s.text(64,618,"Text, lists and maths first. Interactive elements later.",23,MUTED,w=1152)
s.finish()

s=Slide("Turn the engine into one useful student session","The product gap",note=
"No application server, authenticated product API, durable database or frontend currently exists in this workspace. The next product milestone combines four workstreams. Session data must persist and be safely scoped across sessions. The input experience needs direct learner testing. Operational work includes error/recovery flows, deployment and real cost accounting; OpenAI monetary accounting is currently incomplete despite usage tracking. Before use with minors, review appropriate account/data handling and applicable privacy requirements. Pilot recruitment and content review are product work, not merely infrastructure.")
s.heading("Turn the engine into\none useful student session.")
for x,y,num,title,body in [(64,266,"01","A usable interface","Maths input • Work • Feedback"),(655,266,"02","A persistent service","API • Auth • Database • History"),(64,444,"03","Operational confidence","Recovery • Monitoring • Cost"),(655,444,"04","A bounded pilot","Learners • Content • Data care")]:
    s.rect(x,y,561,151,WHITE,16);s.circle(x+45,y+48,23,TEAL);s.text(x+32,y+35,num,21,WHITE,True,40)
    s.text(x+88,y+29,title,28,INK,True,448);s.text(x+25,y+100,body,22,MUTED,w=510)
s.finish()

s=Slide("Two workstreams, one path to a pilot","Roadmap",True,note=
"This is a dependency sequence, not a dated commitment. Engineering: finish current quality calibration and integrate pending work; approve and implement structured presentation; build the persistent Practice product; run a bounded pilot. In parallel: decide the learner and need, prototype maths entry, identify buyer/distribution, recruit and agree success measures. Review follows with a real due queue, followed by Learn, curriculum/placement/assessment and second-subject expansion. Discovery should not wait for every technical foundation to be finished.")
s.heading("Two workstreams, one path to a pilot.","Dependency order, not delivery dates.")
s.text(64,245,"ENGINEERING",14,LIME,True,250)
for i,(title,body) in enumerate([("Quality baseline","Judge comparison\nFailure follow-up"),("Presentation","Readable content\nValidated rendering"),("Practice product","UI + API + storage\nResumable sessions"),("Student pilot","Observe real use\nMeasure outcomes")]):
    x=64+i*294
    s.rect(x,282,270,163,TEAL if i==3 else DARKCARD,15);s.text(x+18,306,title,25,IVORY,True,235);s.text(x+18,367,body,20,"D2E2E3",w=235)
    if i<3:s.line(x+270,353,x+291,353,LIME,2,True)
s.text(64,482,"PRODUCT + BUSINESS — START NOW",14,LIME,True,600)
s.rect(64,516,1152,80,LIME,15);s.text(88,542,"Choose the learner   →   Prototype input   →   Validate buyer   →   Recruit + learn",25,INK,True,w=1100)
s.text(64,627,"After the pilot: Review → Learn → curriculum & assessment → another subject",21,"B3C5CA",w=1150)
s.finish()

s=Slide("Keep the core generic. Prove each subject.","Long-term architecture",note=
"The subject-neutral engine already separates content and verification behind interfaces. Mathematics is the only implemented subject. Physics is the original proposed second-subject test. Chemistry/history examples illustrate a future extension boundary, not committed roadmap releases. Each expansion needs appropriate content, verification, pedagogy and evaluation; adding a model prompt is not enough. Future typed blocks may differ by topic while common interaction/evidence logic remains shared. Cross-subject portability is not yet validated.")
s.heading("Keep the core generic. Prove each subject.")
s.rect(64,269,410,300,NAVY,20);s.text(94,301,"Shared learning core",31,IVORY,True,350);s.text(94,376,"Sessions\nHelp permissions\nEvidence + progress\nHistory + evaluation",26,"D2E2E3",w=345)
for y,title,body,kind in [(251,"Mathematics","Quadratics content + verifier","built"),(383,"Physics","Proposed second-subject test","next"),(515,"Other subjects","New content, checks and formats","later")]:
    s.line(474,y+52,598,y+52,TEAL,3,True);s.rect(618,y,598,103,WHITE,14)
    s.text(640,y+17,title,27,INK,True,360);s.text(640,y+60,body,21,MUTED,w=540)
    s.pill(1063,y+15,{"built":"BUILT","next":"LATER","later":"VISION"}[kind],kind,127)
s.text(64,621,"Extensibility is a design direction. A second subject must validate it.",23,MUTED,w=1150)
s.finish()

# Condensed presentation view of the evidence-backed companion matrix.
matrix = json.loads((OUT.parent / "competitor-matrix/matrix-data.json").read_text())
comparisons = [
    ("Adaptive learning already has strong players.", "CURRICULUM PLATFORMS", [
        ("Khan Academy\n+ Khanmigo", "Course goals, saved mastery,\nteacher assignments", "Multi-subject courses; tutor;\npractice + mastery review", "Availability varies by course;\nhelp-weight policy unverified"),
        ("ALEKS", "Knowledge checks; ongoing\npersonal learning path", "Maths + chemistry; practice,\nquizzes and retention checks", "Narrower subject scope;\ngeneral chat not verified"),
        ("CENTURY", "Curriculum-linked learner\nworkspace + adaptive path", "English, maths, science + more;\nspaced Memory Boost", "Defined curriculum coverage;\ngeneral chat not verified"),
    ], ["K1", "K2", "K3", "K4", "A1", "A2", "A3", "C1", "C2", "C3"],
    "Existing platforms already offer continuity, diagnostics and review. Khan Academy's mastery-challenge reference is a 2020 guide; availability must be checked for a purchase. ALEKS recurring knowledge checks are not the same implementation as memory-timed flashcards."),
    ("Study tools are becoming learning homes.", "AI & STUDY TOOLS", [
        ("StudyFetch", "Syllabus study plan, saved\nprogress + recommended topics", "Broad course uploads; AI tutor,\npractice exams + spaced cards", "Canvas integration exists;\nfull prerequisite graph unverified"),
        ("Quizlet", "Saved sets and study paths;\nadaptive Learn progress", "Broad subject materials; Learn,\ntests, spaced cards + Ask", "Full syllabus planning unverified;\nAsk has access/history limits"),
        ("ChatGPT\nStudy mode", "Chat history + optional memory;\nstudent supplies study context", "Broad subjects; guided dialogue,\nexplanations + practice", "Persistent curriculum mastery\nand review scheduler unverified"),
    ], ["S1", "S2", "S3", "S4", "Q1", "Q2", "Q3", "Q4", "Q5", "O1"],
    "StudyFetch materially overlaps our intended continuous syllabus-led experience; do not portray all alternatives as one-off chats. Quizlet spaced repetition is documented for web, and Ask Quizlet currently has US/14+ availability and chat resets across page changes; saved study paths still persist. Broad uploaded-material or model reach does not prove equally reliable subject-specific assessment."),
    ("School continuity is already a baseline.", "PRACTICE & SCHOOL PLATFORMS", [
        ("IXL", "Standards/textbook mapping;\nsaved progress + next skills", "K–12, multiple subjects;\ndiagnostics + practice feedback", "Diagnostic scope: maths + ELA;\nspaced scheduler unverified"),
        ("Canvas LMS\n+ IgniteAI", "Courses, assignments, grades;\ninstructor-set Mastery Paths", "Any hosted subject; AI study\ntools, quizzes + flashcards", "Course hosting ≠ vetted content;\nAI depends on tier and opt-in"),
        ("Blackboard LMS\n+ AI", "Courses, grades and\naligned outcome mastery", "Any hosted subject; AVA,\nSocratic dialogue + quizzes", "Institution configuration matters;\nautonomous review unverified"),
    ], ["I1", "I2", "I3", "I4", "I5", "V1", "V2", "V3", "B1", "B2", "B3"],
    "LMS platforms already provide persistent institutional workflows and are adding AI. Hosting any subject is different from providing a validated content catalogue and assessment engine for every subject. Canvas Mastery Paths use instructor-configured score branches; Blackboard outcome mastery derives from aligned assessments. Neither is evidence of a full autonomous prerequisite diagnosis and memory scheduler. Full LMS replacement, administration and gradebook scope remain open decisions for LearnAI."),
]
for title, group, rows, refs, nuance in comparisons:
    source_notes = "\n".join(f"{ref}: {matrix['sources'][ref]['title']} — {matrix['sources'][ref]['url']}" for ref in refs)
    s = Slide(title, "Competitor comparison", note=(
        "Public vendor documentation reviewed 1 November 2026; not hands-on product testing. "
        "Not verified means unknown from the reviewed sources, not absent. No scoring or superiority claim. "
        "LearnAI current is an implemented engine foundation; full roadmap is intended future capability. "
        "The roadmap is a persistent personal learning home linked to the student's school/university curriculum: "
        "their courses, topics and progress, automatically resuming and recommending next steps. "
        "It targets maths, chemistry, history, English and other subjects incrementally, with subject-specific checks. "
        + nuance + "\n\nCompanion matrix: ../competitor-matrix/learnai-competitor-matrix.html "
        "(keep the sibling competitor-matrix folder when sharing the local link). "
        "Full comparison and caveats: docs/product/2026-11-01-competitor-matrix.md.\n\nSources:\n" + source_notes))
    s.heading(title, group + "  •  Publicly documented offers vs our foundation and full roadmap")
    columns = [(78, 190), (286, 285), (593, 320), (935, 266)]
    for (x, width), label in zip(columns, ["PRODUCT", "CURRICULUM & CONTINUITY", "LEARNING & SUBJECT REACH", "SCOPE / LIMITS"]):
        s.text(x, 229, label, 13, TEAL, True, width)
    for i, row in enumerate(rows):
        y = 260 + i * 85
        s.rect(64, y, 1152, 77, WHITE, 10)
        for j, ((x, width), value) in enumerate(zip(columns, row)):
            s.text(x, y + 16, value, 18, INK if j == 0 else MUTED, j == 0, width, h=60)
    for y, label, values, fill, fg in [
        (524, "LearnAI / TODAY", ["Practice engine; in-memory state", "Quadratics; checks + AI tutor", "No student UI or durable storage"], PALE, INK),
        (579, "LearnAI / PLANNED", ["Personal curriculum home; next steps", "Any-subject vision; four modes", "Staged rollout; value to prove"], NAVY, IVORY),
    ]:
        s.rect(64, y, 1152, 47, fill, 10)
        for j, ((x, width), value) in enumerate(zip(columns, [label] + values)):
            s.text(x, y + 12, value, 16, fg, j == 0, width, h=40)
    s.text(64, 643, "Unknown ≠ absent. Roadmap ≠ shipped. Sources in notes. Full interactive matrix (link)", 13, MUTED, w=1150)
    # Relative file link: keep the sibling matrix folder alongside the deck.
    companion = "../competitor-matrix/learnai-competitor-matrix.html"
    s.s.shapes[-1].text_frame.paragraphs[0].runs[0].hyperlink.address = companion
    pdf.linkURL(companion, (64, H-661, 700, H-641), relative=0)
    s.finish()

s=Slide("Earn trust in independent progress","Positioning & build vs buy",note=
"This is a proposed positioning hypothesis, not a demonstrated competitive advantage. We should not claim uniqueness for AI tutoring, Elo, skill graphs, spaced repetition or mathematical checking. OpenAI describes Study mode's guided questions and understanding checks (https://help.openai.com/en/articles/11780217-using-study-mode-in-chatgpt). McGraw Hill describes ALEKS knowledge checks and adaptive learning paths (https://www.mheducation.com/highered/digital-products/aleks.html). Khan Academy reports mathematical checking, learner-history experiments and unaided next-item outcome measurement in its May 2026 Khanmigo report (https://blog.khanacademy.org/how-khan-academy-is-building-a-better-ai-tutor-our-most-recent-learnings/). These are first-party descriptions, not a head-to-head benchmark. Our intended offer connects useful help, assistance-aware independent evidence and later retrieval for a specific learner need. Supported checks and evidence contracts exist; the full persistent product and spaced-review experience do not. Why buy rather than build? A capable organisation can build. The potential value is avoiding ongoing content, verification, calibration, product and operational work, if we demonstrate a better result and acceptable total effort. We have not established lower cost or superior outcomes. Why buy from us rather than another vendor is a separate question requiring customer discovery and comparative evidence. Possible advantages to earn: curriculum/language fit, usable maths input, calibrated content, learning outcomes, workflow fit and trusted distribution. None is claimed as proven today. Build can be rational for buyers with strong teams or core product/control requirements. No API or white-label business model is implied. Detailed sources and pilot questions: docs/product/2026-11-01-positioning-and-build-vs-buy.md.")
s.heading("Earn trust in independent progress.","Positioning hypothesis • Prove the value for a specific learner group.")
for x,title,body in [(64,"Useful support","Supported maths checks\nContext-aware tutoring"),(455,"Honest evidence","Keep assistance visible\nCheck independent work"),(846,"Lasting learning","Return to fresh problems\nMeasure after a delay")]:
    s.rect(x,249,370,164,WHITE,15);s.text(x+23,275,title,28,INK,True,325);s.text(x+23,337,body,23,MUTED,w=325)
s.rect(64,445,1152,143,NAVY,16)
s.text(88,467,"WHY NOT BUILD IT?",14,LIME,True,330)
s.text(88,505,"“You could. Our job is to make a maintained learning system\nmore valuable than building and operating one yourselves.”",28,IVORY,True,w=1095)
s.text(64,609,"Prove: learning outcomes + curriculum/workflow fit + total operating effort.",23,INK,True,w=1152)
s.text(64,645,"Tutoring and adaptivity already exist: ChatGPT Study mode, ALEKS, Khanmigo. Comparison sources in notes.",13,MUTED,w=1152)
s.finish()

s=Slide("Measure what students can do later","Pilot evidence",note=
"The primary outcome hypothesis is better independent performance on fresh problems after a delay. No numerical thresholds are agreed; choose them with a pilot population and baseline. Separate learning outcomes from engagement and software reliability. Four evidence groups matter: unaided/delayed success; completion and input friction; incorrect/missing replies and recovery; repeat need, willingness to pay and fully accounted cost per useful session. These metrics are proposed for the pilot, not measured achievements.")
s.heading("Measure what students can do later.","Primary hypothesis: stronger independent performance after a delay.")
for x,y,num,title,body in [(64,263,"01","Learning","Fresh unaided success\nDelayed success"),(655,263,"02","Experience","Session completion\nMaths-input friction"),(64,443,"03","Reliability","Wrong or missing feedback\nRecovery + latency"),(655,443,"04","Business","Repeat need • Willingness to pay\nCost per useful session")]:
    s.rect(x,y,561,162,PALE if num=="01" else WHITE,16);s.text(x+23,y+25,num,20,TEAL,True,48);s.text(x+78,y+22,title,29,INK,True,450);s.text(x+78,y+76,body,23,MUTED,w=455)
s.finish()

s=Slide("Choose one learner. One problem. One useful session.","Decisions together",True,note=
"Close with joint decisions rather than a sales pitch. The business/product co-founder can lead discovery, buyer/distribution validation and pilot design alongside engineering. Decide the initial student group and learning moment, country/curriculum/language, who pays and how we reach them, the input experience to prototype, and the evidence that justifies the next investment. Pricing, launch dates and market-size claims are intentionally not invented. Source: docs/product/2026-11-01-cofounder-brief.md and its technical reading section. Brief: https://chatgpt.com/space/page_69f590c2b0688191b452e138672dd156 . Snapshot includes development work awaiting integration.")
s.text(64,115,"Choose one learner.\nOne problem.\nOne useful session.",57,IVORY,True,860)
for x,title,body in [(64,"WHO?","Student • Curriculum\nBuyer • Distribution"),(455,"WHAT?","Learning moment\nInput experience"),(846,"WHAT PROVES IT?","Pilot evidence\nValue + viable cost")]:
    s.rect(x,390,370,172,DARKCARD,16);s.text(x+23,416,title,23,LIME,True,325);s.text(x+23,467,body,24,IVORY,w=325)
s.text(64,597,"Our next job: turn a strong foundation into a testable product promise.",26,IVORY,True,w=1150)
s.finish()

assert len(slides)==SLIDE_COUNT
prs.save(OUT / f"{DECK_STEM}.pptx")
pdf.save()
(OUT / "speaker-notes.md").write_text(f"# LearnAI — Presenter notes\n\n{len(slides)} slides · approximately 25 minutes · snapshot 1 November 2026\n\n"+"\n".join(notes)+"\nSources: [Cofounder brief](../2026-11-01-cofounder-brief.md), [platform design](../../superpowers/specs/2026-09-14-ai-tutoring-platform-design.md), and the founder's clarification of Learn as estimating and expanding the knowledge frontier.\n\nResearch references:\n\n- [Cepeda et al. (2008): Spacing effects in learning](https://pubmed.ncbi.nlm.nih.gov/19076480/) — timing depends on the retention horizon.\n- [Roediger & Karpicke (2006): Test-enhanced learning](https://pubmed.ncbi.nlm.nih.gov/16507066/) — retrieval practice and delayed recall.\n- [Klinkenberg et al. (2011): Computer adaptive practice of Maths ability](https://dare.uva.nl/id/de65bb65-d198-4dbc-ac7b-bc25ca23e627) — an educational adaptation of Elo-style estimation.\n\nThese studies motivate design choices; none validates LearnAI's implementation or establishes its learning outcomes.\n")
with (OUT / "speaker-notes.md").open("a") as notes_file:
    notes_file.write('\n\n## Difficulty follow-up for presenters\n\nThe current catalogue has one fixed-difficulty template per skill. The planner computes a target, but the registry cannot yet choose an easier or harder template within that skill, and generated variants inherit the same rating. Present this as a difficulty-targeting foundation. Multiple bands or controlled generation and empirical calibration remain future work. See the [planning note](../../superpowers/notes/2026-11-01-exercise-difficulty-follow-up.md). This addendum supplements the existing exported deck.\n')
(OUT / "layout-checks.json").write_text(json.dumps(checks,indent=2,ensure_ascii=False)+"\n")
sheet=Image.new("RGB",(1280,math.ceil(len(slides)/3)*250),"#D7DED8")
for i,slide in enumerate(slides):
    thumb=slide.im.resize((400,225))
    sheet.paste(thumb,(13+(i%3)*426,12+(i//3)*250))
sheet.save(OUT / "contact-sheet.png")
print(f"Created {len(slides)} slides, {len(checks)} bounded text blocks, editable PPTX, PDF, notes and previews.")
