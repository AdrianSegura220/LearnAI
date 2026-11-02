# Exercise difficulty: gaps for future planning

**Status:** deferred planning input, recorded 1 November 2026. This captures the
founder discussion; it is not an approved implementation design or a claim that
adaptive exercise difficulty is complete.

## Current implementation

- The quadratics catalogue has **12 templates across 12 skills: one template per
  skill**. Each template declares one fixed difficulty; all its generated
  variants inherit that value, regardless of their sampled numbers.
- The planner computes a target difficulty from the student's per-skill strength.
  The registry selects the nearest available template within that skill.
- With only one candidate per skill, changing the target cannot select an easier
  or harder template. Variants change, but generation is not controlled by the
  requested difficulty.
- Elo-style learner-strength updates exist. Empirical item/template-difficulty
  calibration does not. The roughly 75% predicted-success target is a starting
  policy, not a measured success rate or guaranteed achievable selection.

Describe this as a **difficulty-targeting foundation**, not fully adaptive
exercise difficulty. Difficulty ratings and learner strength use a per-skill
scale; numbers from different skills are not a global difficulty ranking.

## Missing work

### 1. Meaningful difficulty variation within a skill

Choose multiple authored template bands, parameter-controlled generation, or a
combination. Identify which features change challenge without changing the
intended skill: coefficient ranges, signs, fractions, required transformations
and representation are possible subject-specific factors, not proven rankings.

Keep domain interfaces generic and generation rules in subject adapters. Check
that harder variants do not silently require an unintroduced prerequisite. A
randomly larger number is not, by itself, a calibrated harder exercise.

### 2. Honest selection and fallback behavior

Define achievable ranges, band boundaries and behavior when no suitable item is
available. Preserve both requested and served difficulty. Never label an item
with the requested rating merely because the generator was asked for it.
Record template/version, seed and relevant variant features for reproducibility.

### 3. Evidence suitable for calibration

Audit existing events and add only missing metadata: served difficulty and rating
version, pre-attempt strength/prediction, outcome, assistance/evidence class,
attempt/session identity and selection context. Avoid duplicate updates or
treating repeated attempts as independent observations. Unreadable input and
invalid items must not become evidence that a valid exercise is hard.

Define eligible evidence explicitly. Assisted successes must not be treated as
unaided successes; immediate post-instruction attempts need distinct handling.
Account for memory freshness and missing prerequisites when interpreting failure.

### 4. Empirical difficulty calibration

Choose the estimation unit: template, difficulty band or a model of variant
features. Individually rating every seeded exercise is unlikely to provide enough
repeat observations. Start from authored estimates and update only with adequate
eligible data, tracking uncertainty and sample counts.

The existing design proposes smaller, opposite-direction updates for item
difficulty: better-than-predicted results lower its estimate; worse results raise
it. Define update rates, minimum evidence and outlier handling. Anchor reference
items or recenter each skill's scale so learner and item estimates cannot drift
together. Account for adaptive selection rather than comparing raw success rates
across differently skilled groups.

### 5. Versioning and validation

Version calibration policies and ratings; retain the difficulty and model inputs
actually used for each historical attempt. Specify how recalibration interacts
with replay and mastery thresholds without silently rewriting past evidence.

Verify deterministic generation, answer validity, skill isolation, real selection
between difficulty levels, fallbacks and replay. Evaluate predictions on held-out
students/sessions against the fixed-rating baseline. A simulation can verify
mechanics; it cannot establish real difficulty ordering or learning benefits.

## Suggested sequence and open decisions

First build and review a small range of difficulty levels for a bounded skill
set. Next instrument and observe real attempts. Then evaluate calibration offline
before promoting it to live selection. Full spaced-review scheduling remains a
separate dependency; Elo strength does not replace the memory model.

Future planning should settle: initial skills/bands, generation API, calibration
unit, evidence eligibility, scale anchors, minimum data, success criteria and
rating/replay migration. Do not choose arbitrary thresholds here or automatically
insert this work ahead of already agreed quality/presentation work.

## Repository references

- [Templates](../../../src/learnai/adapters/content/generators/quadratics.py)
- [Generator registry](../../../src/learnai/adapters/content/registry.py)
- [Template contract](../../../src/learnai/adapters/content/types.py)
- [Planner](../../../src/learnai/domain/planner.py)
- [Mastery model](../../../src/learnai/domain/mastery.py)
- [Platform design](../specs/2026-09-14-ai-tutoring-platform-design.md), sections
  6.2, 7.1 and 7.8: declared difficulty, co-estimation and calibration.
