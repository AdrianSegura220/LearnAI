# LearnAI cofounder presentation

25 slides for a roughly 25-minute founder onboarding conversation. Snapshot:
**1 November 2026**, including development work awaiting integration.

- [PowerPoint](learnai-cofounder-v3.pptx): editable text, shapes, diagrams and presenter notes.
- [PDF](learnai-cofounder-v3.pdf): portable presentation copy.
- [Slide overview](contact-sheet.png): all slides at a glance.
- [Presenter notes](speaker-notes.md): narration, evidence limits and discussion prompts.
- [Source brief](../2026-11-01-cofounder-brief.md): supporting detail and repository references.

The deck distinguishes implemented foundations, proposed product work and the
long-term vision. Evaluation figures are recorded observations, not new test
results or learning-effectiveness claims. No project content was uploaded to
Canva. The files are generated locally with no network requests by the builder.

Slides 6–9 explain Learn, Practice, Review and Test individually. Learn includes
the founder's clarification: estimate knowledge across the skill graph, identify
the frontier of ready-to-learn skills, and teach from there. Its graph is an
illustration, not the exact repository graph. Placement and the complete Learn
experience remain planned. See the presenter notes for assumptions and sources.

Slides 10–11 explain spaced repetition with retrieval practice, and Elo-style
skill estimation for difficulty matching. Research links appear in the presenter
notes. The deck distinguishes the evidence behind these principles from LearnAI's
still-unvalidated learning outcomes and calibration. Memory calculations and
strength updates are implemented; the complete Review scheduler remains planned.

Difficulty follow-up: the catalogue currently has only one fixed-difficulty
template per skill. Selecting a target therefore cannot yet select an easier or
harder variant within a skill. See the [future implementation note](../../superpowers/notes/2026-11-01-exercise-difficulty-follow-up.md)
for difficulty bands, generation control, evidence and calibration requirements.

Slide 23 covers proposed differentiation and the build-versus-buy question.
See the [positioning note](../2026-11-01-positioning-and-build-vs-buy.md) for the
competitor sources, current limits and evidence needed to earn an advantage.
Slides 20–22 compare nine competitors against LearnAI today and its full roadmap,
including the persistent, personalised, school/university curriculum-linked home
and the any-subject ambition. Public documentation is distinguished from unverified
capabilities; our roadmap is distinguished from shipped functionality. Source
URLs appear in each slide's presenter notes.

The [full interactive matrix](../competitor-matrix/learnai-competitor-matrix.html)
and [editable workbook](../competitor-matrix/learnai-competitor-matrix.xlsx) retain
the detailed evidence. Deck links to the HTML are relative: keep the sibling
`competitor-matrix/` folder when sharing them; viewers may restrict local links.
Version 3 preserves both earlier exports.

## Regenerate

Use a separate Python environment with `python-pptx`, `reportlab` and `pillow`;
these are documentation tools, not LearnAI application dependencies.

```sh
python build_deck.py
```

The builder currently uses macOS Arial font paths; change `FONT_DIR`, `REG` and
`BOLD` for another platform. It creates both formats, previews and speaker notes
from the same layout. All PowerPoint visuals are native editable elements.
Keep changes in the builder if you want to regenerate; direct PowerPoint edits
will be overwritten on regeneration. PDF fonts are embedded. PowerPoint uses
Arial, so layout can vary if a viewer substitutes fonts.
