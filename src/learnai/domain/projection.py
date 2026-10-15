# src/learnai/domain/projection.py
from collections.abc import Iterable, Mapping
from dataclasses import replace as dc_replace

from learnai.domain.calibration import update_calibration
from learnai.domain.events import AttemptRecorded, EvidenceEvent, HelpTaken
from learnai.domain.evidence import EVIDENCE_WEIGHT
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import SkillId, StudentId
from learnai.domain.mastery import SkillState, is_learned, update_stability, update_strength
from learnai.domain.parameters import (
    DEFAULT_PARAMETERS,
    MasteryParameters,
    resolve_parameters,
)
from learnai.domain.propagation import propagate_success


def apply_event(
    states: dict[SkillId, SkillState],
    event: EvidenceEvent,
    graph: SkillGraph,
    params: MasteryParameters = DEFAULT_PARAMETERS,
    parameter_overrides: Mapping[SkillId, MasteryParameters] | None = None,
) -> dict[SkillId, SkillState]:
    """Fold one event into the projection. Used live and on replay — never diverge."""
    if isinstance(event, HelpTaken):
        return dict(states)  # help is audited, never credited

    assert isinstance(event, AttemptRecorded)
    weight = event.contract_weight * EVIDENCE_WEIGHT[event.evidence_class]
    current = states.get(event.skill_id) or SkillState(event.student_id, event.skill_id)
    event_params = resolve_parameters(event.skill_id, params, parameter_overrides)

    updated = update_strength(
        current, event.item_difficulty, event.outcome, weight, event_params
    )
    if weight > 0.0:
        updated = update_stability(updated, event.correct, event.at, event_params)
    updated = dc_replace(
        updated,
        calibration_gap=update_calibration(
            current.calibration_gap, event.confidence, event.correct, event_params
        ),
    )

    result = dict(states)
    result[event.skill_id] = updated
    if event.correct and weight > 0.0:
        result = propagate_success(
            result, graph, event.skill_id, event.at, params, parameter_overrides
        )
    return {
        sid: _earn_if_due(state, resolve_parameters(sid, params, parameter_overrides))
        for sid, state in result.items()
    }


def _earn_if_due(state: SkillState, params: MasteryParameters) -> SkillState:
    """Latch the achievement the moment the bar is crossed (spec §7.3).

    is_learned is a badge, not a reading: strength may fall again, but an
    earned skill stays earned. One-way by construction — the marker is only
    ever set, and the live path and the replay both come through here."""
    if state.ever_learned or not is_learned(state, params):
        return state
    return dc_replace(state, ever_learned=True)


def project(
    events: Iterable[EvidenceEvent],
    graph: SkillGraph,
    student_id: StudentId,
    params: MasteryParameters = DEFAULT_PARAMETERS,
    parameter_overrides: Mapping[SkillId, MasteryParameters] | None = None,
) -> dict[SkillId, SkillState]:
    """Rebuild a student's whole mastery state from the log. The truth is the log."""
    states: dict[SkillId, SkillState] = {}
    for event in events:
        if event.student_id != student_id:
            continue
        states = apply_event(states, event, graph, params, parameter_overrides)
    return states
