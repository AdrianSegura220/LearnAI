"""Scenario loading preserves raw work and rejects ambiguous evaluator input."""
import json

import pytest

from learnai.domain.enums import Confidence, HelpRung, Verdict
from learnai.domain.history import HistoryKind
from learnai.domain.interaction import InteractionKind, ResponseJob, WorkStatus
from learnai.domain.items import Submission
from learnai.eval.fixtures import (
    FixtureError, HistoricalAction, Scenario, load_scenarios_dir, parse_scenario,
    validate_corpus_expectations,
)


def minimal(**changes):
    raw = dict(id="case", family="diagnosis", skill_id="factor", template_id="factor-1",
                seed=17, permitted_rung="NUDGE", strength=0.4, is_fresh=True,
                calibration_gap=0.1, prior_misconceptions=[], steps=["x^2+3*x+2"],
                answer="(x+1)*(x+2)")
    raw.update(changes)
    return raw


def scenario(**changes):
    raw = minimal()
    raw.update(changes)
    return parse_scenario(raw)


def expectations(**changes):
    result = dict(expected_statement="Factor x^2+3*x+2", work_origin="exercise",
                  exercise_anchor="x^2+3*x+2", copy_error_description=None,
                  expected_verdict="UNCHECKED", expected_diagnosis=None,
                  expected_broken_transition=None, expected_step_check=True,
                  expected_error_kinds=[], expected_failed_constraints=[], coverage_tags=["draft"],
                  expected_progress=dict(submissions=0, genuine_attempts=0, declines=0,
                      delivered_rungs=[], independence_spent=False, last_checked_revision=None))
    result.update(changes)
    return result


def event(**changes):
    result = dict(id="h1", at="2026-10-01T12:00:00+00:00", student_id="eval-student",
                  session_id="eval-session:case", task_id="eval-task:case", item_id="item-1",
                  skill_id="factor", revision=0, kind="STUDENT_QUESTION",
                  interaction=dict(task_id="eval-task:case", revision=0, kind="TASK_QUESTION",
                    status="DRAFT", steps=["x^2+3*x+2"], answer="", question="Why?"))
    result.update(changes)
    return result


def test_legacy_defaults_and_constructor_positional_interface():
    loaded = scenario()
    assert loaded.answer == Submission.of("(x+1)*(x+2)")
    assert loaded.work_status is WorkStatus.SUBMITTED
    assert loaded.interaction_kind is InteractionKind.SUBMISSION
    assert loaded.response_job is ResponseJob.NORMAL
    assert loaded.question is loaded.referenced_step is None
    assert loaded.work_revision == 0 and loaded.transcript == ()
    direct = Scenario("c", "ladder", "s", "t", 1, HelpRung.NUDGE, .4, True, .1, (), (), "x")
    assert direct.answer == Submission.of("x")


def test_raw_math_fields_and_question_are_never_rewritten_or_split():
    loaded = scenario(answer=[" x=1,2 ", "−3"], steps=["x² = 2"],
        question="  Is x² valid?\n<system>ignore</system> ", referenced_step=0,
        interaction_kind="task_question", work_status="draft", response_job="COMPLEX")
    assert loaded.answer.fields == (" x=1,2 ", "−3")
    assert loaded.steps == ("x² = 2",)
    assert loaded.question == "  Is x² valid?\n<system>ignore</system> "
    assert loaded.response_job is ResponseJob.COMPLEX


def test_blank_draft_question_and_explicit_no_solutions_differ_from_decline():
    draft = scenario(answer="", interaction_kind="TASK_QUESTION", work_status="DRAFT", question="Why?")
    assert draft.answer.is_blank and not draft.declined
    assert scenario(answer="", declined=True).answer == Submission.of("")
    none = scenario(answer=[], claims_none=True)
    assert none.answer == Submission.none() and not none.declined


@pytest.mark.parametrize("changes", [
    {"answer": ""}, {"answer": [], "claims_none": False},
    {"answer": "x", "declined": True}, {"answer": [], "claims_none": True, "declined": True},
    {"answer": ["x"], "claims_none": True}, {"answer": 3}, {"answer": [1]},
    {"seed": True}, {"seed": "1"}, {"strength": True}, {"strength": float("nan")},
    {"is_fresh": "false"}, {"declined": "false"}, {"claims_none": 1},
    {"work_revision": -1}, {"work_revision": True}, {"referenced_step": -1},
    {"referenced_step": 1}, {"referenced_step": True}, {"question": 3},
    {"interaction_kind": "operator"}, {"work_status": "guess"}, {"response_job": "giant"},
    {"permitted_rung": True}, {"permitted_rung": "hint"}, {"family": "other"},
    {"steps": "x"}, {"steps": [3]}, {"prior_misconceptions": [False]},
    {"task_progress": {}}, {"unknown": 1}, {"notes": 2},
])
def test_rejects_invalid_current_work_and_silent_coercions(changes):
    with pytest.raises(FixtureError):
        scenario(**changes)


@pytest.mark.parametrize("field", ["id", "skill_id", "template_id"])
def test_required_ids_cannot_be_missing_or_blank(field):
    for value in (None, "", "  "):
        with pytest.raises(FixtureError):
            scenario(**{field: value})
    raw = minimal()
    del raw[field]
    with pytest.raises(FixtureError):
        parse_scenario(raw)


def test_evaluator_expectations_are_typed_and_explicit_null_is_required_for_corpus():
    loaded = scenario(**expectations(), reference_reasoning=["Inspect the middle term."],
                      evaluation_criteria=["Respond to the question."])
    validate_corpus_expectations(loaded)
    assert loaded.expected_verdict == "UNCHECKED"
    assert loaded.expected_diagnosis is None
    assert loaded.expected_progress.submissions == 0
    assert loaded.reference_reasoning == ("Inspect the middle term.",)
    assert loaded.evaluation_criteria == ("Respond to the question.",)
    with pytest.raises(FixtureError, match="expected_diagnosis"):
        raw = expectations()
        del raw["expected_diagnosis"]
        validate_corpus_expectations(scenario(**raw))
    with pytest.raises(FixtureError, match="expected_statement"):
        validate_corpus_expectations(scenario())


@pytest.mark.parametrize("changes", [
    {"expected_statement": 2}, {"work_origin": "invented"},
    {"work_origin": "copy_error"}, {"copy_error_description": "changed sign"},
    {"expected_verdict": "wrongish"}, {"expected_diagnosis": False},
    {"expected_broken_transition": ["a"]}, {"expected_broken_transition": ["a", 1]},
    {"expected_step_check": "false"}, {"expected_error_kinds": ["syntax"]},
    {"expected_failed_constraints": [1]}, {"coverage_tags": "draft"},
    {"reference_reasoning": [1]}, {"evaluation_criteria": "good"},
    {"expected_progress": dict(submissions=True)},
    {"expected_progress": dict(submissions=-1, genuine_attempts=0, declines=0,
        delivered_rungs=[], independence_spent=False, last_checked_revision=None)},
])
def test_rejects_malformed_expectations(changes):
    with pytest.raises(FixtureError):
        scenario(**expectations(**changes))


def test_copy_error_and_multiple_defects_and_progress_are_preserved():
    loaded = scenario(**expectations(work_origin="copy_error", copy_error_description="Copied + as -",
        expected_verdict="WRONG", expected_diagnosis="sign-slip",
        expected_broken_transition=["a", "b"], expected_error_kinds=["copy_error", "equivalence"],
        expected_failed_constraints=["fully_factored"], expected_progress=dict(submissions=3,
        genuine_attempts=2, declines=1, delivered_rungs=["NUDGE", 2],
        independence_spent=True, last_checked_revision=0)))
    assert loaded.expected_broken_transition == ("a", "b")
    assert loaded.expected_error_kinds == ("copy_error", "equivalence")
    assert loaded.expected_progress.delivered_rungs == (HelpRung.NUDGE, HelpRung.NEXT_STEP)


def test_history_retains_prior_exercises_and_same_revision_question_changes():
    first = event(task_id="prior-task", item_id="prior-item", skill_id="prior-skill",
                  interaction=dict(task_id="prior-task", revision=0, kind="TASK_QUESTION",
                    status="DRAFT", steps=[], answer="", question="Earlier?"))
    second = event(id="h2")
    loaded = scenario(answer="", question="New question?", interaction_kind="TASK_QUESTION",
        work_status="DRAFT", history=[first, second])
    assert loaded.history[0].task_id == "prior-task"
    assert loaded.history[1].interaction.question == "Why?"
    assert loaded.history[1].kind is HistoryKind.STUDENT_QUESTION
    assert len(loaded.transcript) == 2
    assert loaded.transcript[1].text == "x^2+3*x+2\n\nWhy?"


def test_current_record_must_match_current_interaction_and_transcript():
    loaded = scenario(answer="", question="Why?", interaction_kind="TASK_QUESTION", work_status="DRAFT",
                      history=[event()], current_interaction_id="h1")
    assert loaded.current_interaction_id == "h1"
    raw = minimal()
    raw.update(answer="", question="Why?", interaction_kind="TASK_QUESTION", work_status="DRAFT",
               history=[event()], current_interaction_id="h1",
               transcript=[dict(speaker="student", text="x^2+3*x+2\n\nWhy?")])
    assert parse_scenario(raw).transcript == loaded.transcript
    raw["transcript"][0]["text"] = "invented"
    with pytest.raises(FixtureError):
        parse_scenario(raw)
    with pytest.raises(FixtureError):
        scenario(history=[event()], current_interaction_id="h1")


@pytest.mark.parametrize("change", [
    {"student_id": "other"}, {"session_id": "other"}, {"revision": -1},
    {"revision": True}, {"kind": "operator"}, {"at": "2026-10-01T12:00:00"},
    {"at": "2026-10-01T12:00:00+02:00"}, {"at": "no"},
    {"interaction": None}, {"message": "private"}, {"unknown": "ignored?"},
    {"related_record_ids": ["missing"]}, {"verdict": "WRONG"},
    {"task_id": "wrong"}, {"revision": 1},
])
def test_rejects_history_with_invalid_provenance_or_private_content(change):
    with pytest.raises(FixtureError):
        scenario(history=[event(**change)])


def test_rejects_reused_ids_and_changed_work_without_new_revision():
    with pytest.raises(FixtureError):
        scenario(history=[event(), event()])
    with pytest.raises(FixtureError):
        scenario(history=[event()], answer="changed")
    loaded = scenario(history=[event()], answer="changed", work_revision=1)
    assert loaded.work_revision == 1
    with pytest.raises(FixtureError):
        scenario(history=[event(revision=1, interaction=dict(task_id="eval-task:case", revision=1,
            kind="TASK_QUESTION", status="DRAFT", steps=[], answer="", question="Why?"))])


def test_help_request_is_textless_and_delivered_messages_have_links():
    request = event(kind="HELP_REQUEST", interaction=dict(task_id="eval-task:case", revision=0,
                    kind="HELP_REQUEST", status="DRAFT", steps=[], answer=""))
    delivery = event(id="h2", kind="HELP_DELIVERED", interaction=None, message="Try a product.",
                     rung="NUDGE", related_record_ids=["h1"])
    loaded = scenario(history=[request, delivery], steps=[], answer="", interaction_kind="HELP_REQUEST",
                      work_status="DRAFT")
    assert len(loaded.transcript) == 1
    assert loaded.transcript[0].speaker == "tutor"
    assert loaded.history[1].rung is HelpRung.NUDGE


def test_directory_loads_json_and_yaml_deterministically_and_rejects_duplicates(tmp_path):
    (tmp_path / "b.json").write_text(json.dumps([minimal(id="b")]))
    (tmp_path / "a.yaml").write_text("- " + json.dumps(minimal(id="a")))
    assert [s.id for s in load_scenarios_dir(tmp_path)] == ["a", "b"]
    (tmp_path / "c.yml").write_text(json.dumps(minimal(id="a")))
    with pytest.raises(FixtureError, match="duplicate"):
        load_scenarios_dir(tmp_path)


def test_directory_reports_malformed_input_and_missing_paths(tmp_path):
    with pytest.raises(FixtureError):
        load_scenarios_dir(tmp_path / "missing")
    (tmp_path / "bad.yaml").write_text("bad: [")
    with pytest.raises(FixtureError, match="bad.yaml"):
        load_scenarios_dir(tmp_path)


def action(**changes):
    raw = dict(operation="ask_question", at="2026-01-01T00:00:00Z", task_id="eval-task:case",
        template_id="factor-1", seed=17, interaction=dict(task_id="eval-task:case", revision=0,
        kind="TASK_QUESTION", status="DRAFT", steps=["x^2+3*x+2"], answer="", question="Why?"),
        tutor_script=[dict(message="Check the sign.", rung_used="NUDGE"), None])
    raw.update(changes)
    return raw


def test_historical_actions_preserve_private_scripts_without_publishing_them():
    loaded = scenario(history_actions=[action(response_job="brief")], work_revision=1)
    assert isinstance(loaded.history_actions[0], HistoricalAction)
    assert loaded.history_actions[0].response_job is ResponseJob.BRIEF
    assert loaded.history_actions[0].tutor_script[0].message == "Check the sign."
    assert loaded.history_actions[0].tutor_script[1] is None
    assert loaded.history == loaded.transcript == ()
    assert loaded.now.isoformat() == "2026-01-01T00:00:00+00:00"
    assert loaded.confidence is Confidence.UNSURE


def test_historical_submit_requires_confidence_and_current_confidence_is_typed():
    submit = action(operation="submit", confidence="CERTAIN", interaction=dict(
        task_id="eval-task:case", revision=0, kind="SUBMISSION", status="SUBMITTED",
        steps=[], answer={"fields": [""], "claims_none": False}))
    loaded = scenario(history_actions=[submit], confidence=1, work_revision=1)
    assert loaded.confidence is Confidence.GUESSING
    assert loaded.history_actions[0].confidence is Confidence.CERTAIN
    assert loaded.history_actions[0].interaction.answer.is_blank
    del submit["confidence"]
    with pytest.raises(FixtureError):
        scenario(history_actions=[submit])


def test_historical_help_uses_stored_work_and_prior_task_identity():
    loaded = scenario(history_actions=[action(operation="request_help", task_id="old",
                      template_id="old-template", seed=8, interaction=None)])
    assert loaded.history_actions[0].interaction is None
    assert loaded.history_actions[0].template_id == "old-template"


@pytest.mark.parametrize("change", [
    {"operation": "set_counts"}, {"at": "2026-01-01"}, {"at": "2026-01-02T00:00:00Z"},
    {"task_id": "other"}, {"seed": True}, {"template_id": ""}, {"interaction": None},
    {"confidence": "CERTAIN"}, {"response_job": "large"}, {"unknown": 1},
    {"tutor_script": "silence"}, {"tutor_script": [False]},
    {"tutor_script": [dict(message="hi", rung_used=True)]},
    {"tutor_script": [dict(message="hi", rung_used="NUDGE", unknown=True)]},
    {"tutor_script": [dict(message="hi", rung_used="NUDGE", diagnosis=False)]},
    {"operation": "request_help"}, {"operation": "submit", "confidence": True},
])
def test_rejects_malformed_historical_actions_and_scripts(change):
    with pytest.raises(FixtureError):
        scenario(history_actions=[action(**change)])


def test_historical_action_task_binding_and_order_are_consistent():
    for second in (action(seed=18), action(template_id="another"),
                   action(at="2025-12-31T23:59:59Z")):
        with pytest.raises(FixtureError):
            scenario(history_actions=[action(), second])
    with pytest.raises(FixtureError):
        scenario(history_actions=[action(seed=18)])
    with pytest.raises(FixtureError):
        scenario(now="2025-12-31T00:00:00Z", history_actions=[action()])


@pytest.mark.parametrize("changes", [{"confidence": True}, {"confidence": "3"},
    {"now": "yesterday"}, {"now": "2026-01-01T00:00:00+03:00"}])
def test_rejects_invalid_current_clock_and_confidence(changes):
    with pytest.raises(FixtureError):
        scenario(**changes)


@pytest.mark.parametrize("changes", [
    {"expected_progress": dict(submissions=1, genuine_attempts=0, declines=0, delivered_rungs=[],
        independence_spent=False, last_checked_revision=None)},
    {"expected_progress": dict(submissions=0, genuine_attempts=0, declines=0, delivered_rungs=[True],
        independence_spent=False, last_checked_revision=None)},
    {"expected_progress": dict(submissions=0, genuine_attempts=0, declines=0, delivered_rungs=[],
        independence_spent="false", last_checked_revision=None)},
    {"expected_progress": dict(submissions=0, genuine_attempts=0, declines=0, delivered_rungs=[],
        independence_spent=False, last_checked_revision=True)},
    {"work_origin": "none", "exercise_anchor": "x"},
    {"work_origin": "exercise", "exercise_anchor": None},
])
def test_rejects_progress_coercions_and_contradictory_work_origins(changes):
    with pytest.raises(FixtureError):
        scenario(**expectations(**changes))


@pytest.mark.parametrize("history", [
    [event(), event(id="h2", at="2026-10-01T11:59:00Z")],
    [event(), event(id="h2", item_id="changed")],
    [event(skill_id="wrong-current-skill")],
    [event(interaction=dict(task_id="eval-task:case", revision=0, kind="TASK_QUESTION", status="DRAFT",
        steps=[], answer=dict(fields=[], claims_none="false")))],
    [event(interaction=dict(task_id="eval-task:case", revision=0, kind="TASK_QUESTION", status="DRAFT",
        steps=[], answer=dict(fields=[], claims_none=True, unknown=True)))],
    [event(interaction=dict(task_id="eval-task:case", revision=0, kind="TASK_QUESTION", status="DRAFT",
        steps=[], answer="", referenced_step=0))],
    [event(interaction=dict(task_id="eval-task:case", revision=0, kind="TASK_QUESTION", status="DRAFT",
        steps=[], answer="", internal_notes="secret"))],
    [event(), event(id="h2", kind="TUTOR_DELIVERED", interaction=None, message="hi", rung="NUDGE",
        related_record_ids=["h1"], verdict="WRONG")],
    [event(), event(id="h2", kind="HELP_DELIVERED", interaction=None, message="hi", rung="NUDGE",
        related_record_ids=["h1"])],
])
def test_rejects_contradictory_history_identity_work_and_delivery(history):
    with pytest.raises(FixtureError):
        scenario(history=history, work_revision=2)


def test_history_submission_verdict_and_evidence_remain_historical():
    record = event(kind="SUBMISSION", verdict="WRONG", evidence_class="ASSISTED",
        interaction=dict(task_id="eval-task:case", revision=0, kind="SUBMISSION", status="SUBMITTED",
            steps=[], answer="x+1"))
    loaded = scenario(history=[record], work_revision=1, **expectations())
    assert loaded.history[0].verdict is Verdict.WRONG
    assert loaded.expected_verdict == "UNCHECKED"
    assert loaded.interaction.answer.fields == ("(x+1)*(x+2)",)


def test_private_historical_draft_can_have_empty_message_and_proposals():
    loaded = scenario(work_revision=1, history_actions=[action(tutor_script=[dict(message="", rung_used=4,
        diagnosis="sign-slip", proposals=[dict(kind="drop_to_prerequisite", target_skill_id="expand")])])])
    turn = loaded.history_actions[0].tutor_script[0]
    assert turn.message == "" and turn.rung_used is HelpRung.FULL_REVEAL
    assert turn.proposals[0].target_skill_id == "expand"
    assert loaded.transcript == ()


def test_legacy_transcript_preserves_text_and_rejects_unknown_speakers_and_metadata():
    assert scenario(transcript=[dict(speaker="student", text="  x²\n1,2 ")]).transcript[0].text == "  x²\n1,2 "
    for entry in (dict(speaker="operator", text="hi"), dict(speaker="student", text="hi", hidden="x"),
                  dict(speaker="student", text="hi", revision=True)):
        with pytest.raises(FixtureError):
            scenario(transcript=[entry])


def test_large_numeric_inputs_report_fixture_error_instead_of_overflow():
    with pytest.raises(FixtureError):
        scenario(strength=10**1000)


@pytest.mark.parametrize("suffix,text", [
    ("json", '{"id":"first","id":"second"}'),
    ("yaml", 'id: first\nid: second\n'),
])
def test_duplicate_mapping_keys_are_rejected_before_parser_loses_them(tmp_path, suffix, text):
    # A duplicated field must be reported as ambiguous input, not silently overwritten.
    (tmp_path / f"ambiguous.{suffix}").write_text(text)
    with pytest.raises(FixtureError, match="duplicate mapping key: id"):
        load_scenarios_dir(tmp_path)


def test_explicit_empty_history_views_remain_distinguishable_for_replay_assertions():
    implicit = scenario()
    explicit = scenario(history=[], transcript=[])
    assert "history" not in implicit.provided_fields
    assert "history" in explicit.provided_fields and "transcript" in explicit.provided_fields
    with pytest.raises(FixtureError):
        scenario(provided_fields=["history"])
