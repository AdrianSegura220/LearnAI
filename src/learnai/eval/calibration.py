"""Keyless preparation of authored calibration drafts against the real engine."""
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.turn_schema import TurnSchemaError, parse_turn
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import MisconceptionId
from learnai.domain.misconceptions import MisconceptionMatcher
from learnai.domain.ports import Verifier
from learnai.domain.skills import Misconception
from learnai.domain.turn import RejectionReason, ValidationResult, validate_turn
from learnai.eval.fixtures import FixtureError, Scenario
from learnai.eval.judge import JudgePacket
from learnai.eval.reference import build_reference
from learnai.eval.replay import prepare_scenario


@dataclass(frozen=True)
class PreparedCalibrationCase:
    id: str
    packet: JudgePacket
    validation: ValidationResult
    expected_scores: Mapping[str, int]
    review_status: str
    assessment_source: str


def _mapping(value: object, keys: set[str], path: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise FixtureError(f"{path} must be a mapping")
    if set(value) != keys:
        raise FixtureError(f"{path}: missing or unknown fields; required {sorted(keys)}")
    return value


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FixtureError(f"{path} must be a nonblank string")
    return value


def prepare_calibration(path: Path, *, scenarios: Mapping[str, Scenario], graph: SkillGraph,
                        items: GeneratorRegistry,
                        catalogue: Mapping[MisconceptionId, Misconception], verifier: Verifier,
                        matcher: MisconceptionMatcher) -> tuple[PreparedCalibrationCase, ...]:
    """Validate the complete collection without clients, delivery or judge calls.

    Candidates may be deliberately rejected drafts. Their exact engine outcomes
    must match the declarations; labels and gate results never enter packets.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise FixtureError(f"cannot read calibration {path}: {exc}") from exc
    raw = _mapping(raw, {"version", "cases"}, "calibration")
    if type(raw["version"]) is not int or raw["version"] != 1:
        raise FixtureError("calibration.version must be 1")
    if not isinstance(raw["cases"], list) or not raw["cases"]:
        raise FixtureError("calibration.cases must be a nonempty list")
    prepared = []
    ids = set()
    for index, entry in enumerate(raw["cases"]):
        entry = _mapping(entry, {"id", "scenario_id", "candidate", "expected_scores", "rationale",
                                 "review_status", "assessment_source", "expected_engine"},
                         f"cases[{index}]")
        case_id = _text(entry["id"], f"cases[{index}].id")
        if case_id in ids:
            raise FixtureError(f"duplicate calibration id: {case_id}")
        ids.add(case_id)
        scenario_id = _text(entry["scenario_id"], f"{case_id}.scenario_id")
        if scenario_id not in scenarios:
            raise FixtureError(f"{case_id}: unknown scenario {scenario_id}")
        _text(entry["rationale"], f"{case_id}.rationale")
        status, source = entry["review_status"], entry["assessment_source"]
        if status not in ("proposed", "user_confirmed"):
            raise FixtureError(f"{case_id}: invalid review_status")
        if source not in ("judge_packet", "trace_review"):
            raise FixtureError(f"{case_id}: invalid assessment_source")
        scores = entry["expected_scores"]
        if (not isinstance(scores, Mapping)
                or any(name not in ("mathematics", "help_level", "diagnosis", "tone")
                       or type(score) is not int or not 0 <= score <= 2
                       for name, score in scores.items())):
            raise FixtureError(f"{case_id}: expected_scores must contain score names and integers 0–2")
        if source == "trace_review" and scores:
            raise FixtureError(f"{case_id}: trace_review requires empty expected_scores")
        expected = _mapping(entry["expected_engine"], {"accepted", "reason"},
                            f"{case_id}.expected_engine")
        accepted, reason = expected["accepted"], expected["reason"]
        if (type(accepted) is not bool
                or (accepted and reason is not None)
                or (not accepted and (not isinstance(reason, str) or reason not in RejectionReason.__members__))):
            raise FixtureError(f"{case_id}: invalid expected_engine acceptance/rejection reason")
        try:
            candidate = parse_turn(entry["candidate"])
        except (TurnSchemaError, TypeError) as exc:
            raise FixtureError(f"{case_id}: invalid candidate: {exc}") from exc
        scenario = scenarios[scenario_id]
        replayed = prepare_scenario(scenario, graph=graph, items=items, catalogue=catalogue,
                                   verifier=verifier, matcher=matcher)
        if replayed.context is None:
            raise FixtureError(f"{case_id}: scenario {scenario_id} has no tutor opportunity")
        validation = validate_turn(candidate, replayed.context, graph, verifier)
        actual_reason = validation.reason.name if validation.reason is not None else None
        if validation.accepted != accepted or actual_reason != reason:
            raise FixtureError(f"{case_id}: engine gate mismatch: expected {dict(expected)}, "
                               f"got accepted={validation.accepted}, reason={actual_reason}")
        reference = build_reference(scenario, item=replayed.task.item, graph=graph,
                                    catalogue=catalogue, verifier=verifier)
        prepared.append(PreparedCalibrationCase(case_id, JudgePacket(replayed.context, candidate, reference),
                                               validation, dict(scores), status, source))
    return tuple(prepared)
