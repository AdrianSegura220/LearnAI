# src/learnai/domain/ids.py
from typing import NewType

VerificationKind = NewType("VerificationKind", str)
"""Selects which Verifier adapter judges a skill, e.g. "cas_symbolic".

Opaque, like FormConstraint: enumerating adapter kinds here would mean every
new subject edits the core, which is exactly what this seam exists to prevent.
Each adapter declares its own kind; the engine resolves skill -> verifier
through a registry. See spec §6.1.
"""

SkillId = NewType("SkillId", str)
ConceptId = NewType("ConceptId", str)
MisconceptionId = NewType("MisconceptionId", str)
ItemId = NewType("ItemId", str)
TemplateId = NewType("TemplateId", str)
StudentId = NewType("StudentId", str)
SessionId = NewType("SessionId", str)
TaskId = NewType("TaskId", str)
CourseId = NewType("CourseId", str)
