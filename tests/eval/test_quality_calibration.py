"""Authored quality examples use production replay, parsing, gate and packets."""
from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest
import yaml

from learnai.domain.enums import HelpRung
from learnai.domain.turn import RejectionReason
from learnai.eval.fixtures import FixtureError, load_scenarios_dir
from learnai.eval.judge import build_judge_messages
from tests.eval.test_fixture_corpus import dependencies

ROOT = Path(__file__).resolve().parents[2]
CALIBRATION = ROOT / "eval/calibration/tutor_quality_v2.yaml"


@pytest.fixture(scope="module")
def scenarios():
    return {s.id: s for s in load_scenarios_dir(ROOT / "eval/fixtures")}


def case(**changes):
    raw = dict(id="factor-pair", scenario_id="leak-solve.factoring",
        candidate=dict(message="Which integers have product -63 and sum -2?", rung_used="NEXT_STEP"),
        expected_scores={"help_level": 2}, rationale="Guides factoring without giving a root.",
        review_status="user_confirmed", assessment_source="judge_packet",
        expected_engine=dict(accepted=True, reason=None))
    raw.update(changes)
    return raw


def prepare(path, scenarios, dependencies):
    from learnai.eval.calibration import prepare_calibration

    return prepare_calibration(path, scenarios=scenarios, **dependencies)


def write_collection(tmp_path, entries, **changes):
    raw = dict(version=1, cases=entries)
    raw.update(changes)
    path = tmp_path / "cases.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_authored_collection_labels_and_real_engine_outcomes(scenarios, dependencies):
    prepared = prepare(CALIBRATION, scenarios, dependencies)
    assert [p.id for p in prepared] == [
        "useful-factor-pair", "premature-root", "explain-corrected-work",
        "unnecessary-correction-rework", "concrete-multiplication",
        "repeated-vague-hint", "unsupported-verification-claim"]
    assert [dict(p.expected_scores) for p in prepared] == [
        {"help_level": 2}, {"help_level": 0}, {"help_level": 2},
        {"help_level": 1}, {"help_level": 2}, {"help_level": 0}, {}]
    assert [p.review_status for p in prepared] == ["user_confirmed"] + ["proposed"] * 6
    assert [p.validation.accepted for p in prepared] == [True, False, True, True, True, True, True]
    assert prepared[1].validation.reason is RejectionReason.ANSWER_LEAKED
    assert prepared[-1].assessment_source == "trace_review"
    assert [p.assessment_source for p in prepared[:-1]] == ["judge_packet"] * 6
    assert prepared[0].packet.context.permitted_rung is HelpRung.NAME_METHOD
    assert prepared[4].packet.context.permitted_rung is HelpRung.FULL_REVEAL
    assert prepared[4].packet.turn.rung_used is HelpRung.NEXT_STEP
    assert prepared[2].packet.context.interaction.revision == 1
    assert prepared[2].packet.context.diagnosis is None
    assert not prepared[2].packet.turn.message.endswith("?")
    with pytest.raises(FrozenInstanceError):
        prepared[0].id = "changed"


def test_packets_exclude_calibration_labels_and_never_deliver_candidates(tmp_path, scenarios, dependencies):
    raw = case(id="PRIVATE_LABEL", rationale="PRIVATE_RATIONALE")
    prepared, = prepare(write_collection(tmp_path, [raw]), scenarios, dependencies)
    packet = prepared.packet
    sent = json.loads(build_judge_messages(packet)[0]["content"])
    assert sent["candidate_response"]["message"] == raw["candidate"]["message"]
    assert packet.reference.answer is not None and packet.reference.reasoning
    assert packet.context.task_progress.delivered_rungs == ()
    assert not any(r.message == packet.turn.message for r in packet.context.history)
    text = json.dumps(sent)
    for private in ("PRIVATE_LABEL", "PRIVATE_RATIONALE", "expected_scores", "review_status",
                    "assessment_source", "expected_engine", "accepted", "validation"):
        assert private not in text


@pytest.mark.parametrize("field,value", [
    ("id", " "), ("scenario_id", "missing"), ("candidate", []),
    ("candidate", {"message": "bad\x1b", "rung_used": "NUDGE"}),
    ("candidate", {"message": "hint", "rung_used": "INVALID"}),
    ("candidate", {"message": "hint", "rung_used": "NUDGE", "unknown": 0, 1: 0}),
    ("expected_scores", {"unknown": 2}), ("expected_scores", {"tone": 3}),
    ("expected_scores", {"tone": -1}), ("expected_scores", {"tone": True}),
    ("expected_scores", {"tone": 1.5}), ("expected_scores", []),
    ("review_status", "confirmed"), ("assessment_source", "trace"),
    ("rationale", " \n"), ("expected_engine", {"accepted": "true", "reason": None}),
    ("expected_engine", {"accepted": True, "reason": "ANSWER_LEAKED"}),
    ("expected_engine", {"accepted": False, "reason": None}),
    ("expected_engine", {"accepted": False, "reason": "answer_leaked"}),
    ("expected_engine", {"accepted": True}),
])
def test_invalid_case_fails_preparation(tmp_path, scenarios, dependencies, field, value):
    with pytest.raises(FixtureError):
        prepare(write_collection(tmp_path, [case(**{field: value})]), scenarios, dependencies)


@pytest.mark.parametrize("field", list(case()))
def test_missing_case_fields_fail(tmp_path, scenarios, dependencies, field):
    raw = case()
    del raw[field]
    with pytest.raises(FixtureError, match="missing"):
        prepare(write_collection(tmp_path, [raw]), scenarios, dependencies)


@pytest.mark.parametrize("changes", [dict(version=2), dict(version=True), dict(cases={}),
                                        dict(cases=[]), dict(extra="unknown")])
def test_invalid_collection_fails(tmp_path, scenarios, dependencies, changes):
    with pytest.raises(FixtureError):
        prepare(write_collection(tmp_path, [case()], **changes), scenarios, dependencies)


def test_duplicate_ids_fail(tmp_path, scenarios, dependencies):
    with pytest.raises(FixtureError, match="duplicate"):
        prepare(write_collection(tmp_path, [case(), case()]), scenarios, dependencies)


@pytest.mark.parametrize("text", ["[", "null", "[]", "version: 1", "cases: []"])
def test_malformed_or_incomplete_document_fails(tmp_path, scenarios, dependencies, text):
    path = tmp_path / "malformed.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(FixtureError):
        prepare(path, scenarios, dependencies)


def test_missing_file_fails(tmp_path, scenarios, dependencies):
    with pytest.raises(FixtureError, match="cannot read calibration"):
        prepare(tmp_path / "missing.yaml", scenarios, dependencies)


def test_unknown_case_field_fails(tmp_path, scenarios, dependencies):
    with pytest.raises(FixtureError, match="unknown fields"):
        prepare(write_collection(tmp_path, [case(unexpected=True)]), scenarios, dependencies)


def test_trace_review_requires_empty_scores(tmp_path, scenarios, dependencies):
    with pytest.raises(FixtureError, match="trace_review"):
        prepare(write_collection(tmp_path, [case(assessment_source="trace_review")]), scenarios, dependencies)


def test_completed_scenario_has_no_tutor_opportunity(tmp_path, scenarios, dependencies):
    with pytest.raises(FixtureError, match="tutor opportunity"):
        prepare(write_collection(tmp_path, [case(scenario_id="ladder-corrected-final")]), scenarios, dependencies)


@pytest.mark.parametrize("candidate,expected_engine", [
    (dict(message="One root is x = 9.", rung_used="NUDGE"), dict(accepted=True, reason=None)),
    (dict(message="Look at the signs.", rung_used="NUDGE"), dict(accepted=False, reason="ANSWER_LEAKED")),
    (dict(message="One root is x = 9.", rung_used="FULL_REVEAL"),
     dict(accepted=False, reason="ANSWER_LEAKED")),
])
def test_gate_mismatches_fail_for_exact_declared_reason(tmp_path, scenarios, dependencies, candidate, expected_engine):
    with pytest.raises(FixtureError, match="engine.*mismatch"):
        prepare(write_collection(tmp_path, [case(candidate=candidate, expected_engine=expected_engine)]),
                scenarios, dependencies)


def test_intentional_rejection_keeps_packet_without_delivery(tmp_path, scenarios, dependencies):
    raw = case(candidate=dict(message="One root is x = 9.", rung_used="NUDGE"),
               expected_engine=dict(accepted=False, reason="ANSWER_LEAKED"))
    prepared, = prepare(write_collection(tmp_path, [raw]), scenarios, dependencies)
    assert prepared.validation.reason is RejectionReason.ANSWER_LEAKED
    assert prepared.packet.context.task_progress.delivered_rungs == ()
    assert prepared.packet.turn.message == "One root is x = 9."
    assert not any(r.message == prepared.packet.turn.message for r in prepared.packet.context.history)
