# Competitor comparison artifacts

Snapshot: 1 November 2026. Nine competitors, LearnAI current, LearnAI full roadmap;
twelve dimensions and source links for each supported finding.

- Open `learnai-competitor-matrix.html` locally for filters and grouped comparisons.
- Open `learnai-competitor-matrix.xlsx` for editable tables and filterable evidence.
- Read [the assessment](../2026-11-01-competitor-matrix.md) for implications of the
  persistent, personalised, curriculum-linked, any-subject vision.
- `build_matrix.py` is the authored source. `matrix-data.json` is its generated
  representation. Update the builder to preserve edits on regeneration.

Run with Python and `xlsxwriter` in a separate documentation environment:

```sh
python build_matrix.py
```

No project-runtime dependency changes are needed. The generated HTML loads no
external resources; it only follows source links when the reader selects them.
The workbook has no macros or external data connections. Existing presentation
exports are not overwritten by this builder.

Public documentation establishes described scope, not independently verified
effectiveness. Unknown is not absent. LearnAI roadmap coverage is not current
availability. Do not convert the matrix into an unsupported feature-score ranking.
