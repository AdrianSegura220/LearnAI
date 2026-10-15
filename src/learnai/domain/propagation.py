# src/learnai/domain/propagation.py
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime

from learnai.domain.graph import SkillGraph
from learnai.domain.ids import SkillId
from learnai.domain.mastery import SkillState, is_learned, retrievability
from learnai.domain.parameters import (
    DEFAULT_PARAMETERS,
    MasteryParameters,
    resolve_parameters,
)


def propagate_success(
    states: dict[SkillId, SkillState],
    graph: SkillGraph,
    skill_id: SkillId,
    now: datetime,
    params: MasteryParameters = DEFAULT_PARAMETERS,
    parameter_overrides: Mapping[SkillId, MasteryParameters] | None = None,
) -> dict[SkillId, SkillState]:
    """Credit an implicit retrieval to the direct hard prerequisites of a success.

    Solving something downstream demonstrates the prerequisite is still available,
    so refresh its memory rather than making the student sit a review of it. The
    credit is partial, reaches direct hard prerequisites only, and never touches
    strength — competence is only ever moved by direct evidence. Each target's
    own parameters price its nudge.
    """
    updated = dict(states)
    for prereq_id in graph.hard_prereqs(skill_id):
        prereq = updated.get(prereq_id)
        if prereq is None:
            continue
        prereq_params = resolve_parameters(prereq_id, params, parameter_overrides)
        if not is_learned(prereq, prereq_params) or prereq.stability <= 0.0:
            continue
        r = retrievability(prereq, now)
        growth = 1.0 + (
            prereq_params.prereq_propagation_weight
            * prereq_params.stability_growth_a
            * (1.0 - r)
        )
        updated[prereq_id] = replace(
            prereq,
            stability=prereq.stability * growth,
            last_success_at=now,
            last_reviewed_at=now,
        )
    return updated
