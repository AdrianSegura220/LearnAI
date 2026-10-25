"""Independent generated-content, checked-work and replay assertions."""
from collections.abc import Mapping

from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.rendering import render_blocks
from learnai.domain.enums import HelpRung, Verdict
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import MisconceptionId
from learnai.domain.interaction import InteractionKind, VerificationSnapshot, prepare_verification
from learnai.domain.items import Formula
from learnai.domain.misconceptions import MisconceptionMatcher
from learnai.domain.ports import Verifier
from learnai.domain.skills import Misconception
from learnai.eval.fixtures import FixtureError, Scenario, validate_corpus_expectations
from learnai.eval.replay import prepare_scenario


def validate_scenario(scenario: Scenario, *, graph: SkillGraph, items: GeneratorRegistry,
                      catalogue: Mapping[MisconceptionId, Misconception], verifier: Verifier,
                      matcher: MisconceptionMatcher) -> None:
    """Validate one selection without applying complete-corpus coverage floors."""
    def require(condition: bool, discrepancy: str) -> None:
        if not condition:
            raise FixtureError(f"{scenario.id}: {discrepancy}")

    validate_corpus_expectations(scenario)
    try:
        item = items.instantiate(scenario.template_id, scenario.seed)
        require(scenario.skill_id in graph.skills and item.skill_id == scenario.skill_id,
                "skill does not match generated template")
        require(render_blocks(item.statement) == scenario.expected_statement,
                "statement differs from pinned generated exercise")
        scenario.answer.check_shape(item.answer_spec.kind)
        canonical = item.worked_steps[0] if item.worked_steps else None
        if scenario.work_origin != "none":
            # No-worked-step generators need an explicitly reviewed statement or
            # formula anchor. This checks the snapshot, not a word-to-model proof.
            anchors = (canonical,) if canonical else (render_blocks(item.statement), *(
                block.source for block in item.statement if isinstance(block, Formula)))
            require(scenario.exercise_anchor in anchors, "anchor differs from generated exercise")
            if not canonical:
                require(bool(scenario.reference_reasoning), "anchor requires reviewed reference reasoning")
            if scenario.work_origin == "exercise" and scenario.steps:
                if canonical:
                    require(verifier.diff_steps((canonical, scenario.steps[0])) is None,
                            "first mathematical line differs from generated starting work")
                else:
                    require(bool(scenario.reference_reasoning), "first line needs reviewed model linking")
            if scenario.work_origin == "copy_error":
                require(bool(scenario.steps) and bool(scenario.copy_error_description),
                        "copy error requires copied first line and description")
                if canonical:
                    require(verifier.diff_steps((canonical, scenario.steps[0])) is not None,
                            "copy error first line does not differ from exercise")
        else:
            require(not scenario.steps, "first line needs an exercise or copy-error origin")
        prepared = prepare_scenario(scenario, graph=graph, items=items, catalogue=catalogue,
                                    verifier=verifier, matcher=matcher)
        task = prepared.task
        # MALFORMED deliberately leaves no stored verification or evidence.
        checked = task.last_verification
        if prepared.outcome is not None and prepared.outcome.verdict is Verdict.MALFORMED:
            checked = prepare_verification(scenario.interaction, item=item, verifier=verifier,
                catalogue=tuple(catalogue[m] for m in graph.skills[item.skill_id].misconception_ids),
                matcher=matcher, check_answer=True, check_steps=True)
        checked = checked or VerificationSnapshot(task.work_revision, False, False, None, None, None)
        verdict = checked.verdict.name if checked.answer_checked and checked.verdict else "UNCHECKED"
        require(verdict == scenario.expected_verdict, f"verdict {verdict} differs from expectation")
        require(checked.diagnosis == scenario.expected_diagnosis,
                f"diagnosis {checked.diagnosis!r} differs from expectation")
        diff = checked.step_diff
        broken = (diff.previous, diff.current) if diff else None
        require(broken == scenario.expected_broken_transition, "broken transition differs from expectation")
        require(checked.steps_checked == scenario.expected_step_check, "step-check scope differs from expectation")
        require(checked.failed_constraints == scenario.expected_failed_constraints,
                "failed constraints differ from expectation")
        errors = set()
        if diff:
            errors.add("unreadable" if diff.unreadable else "equivalence")
        if checked.verdict is Verdict.MALFORMED:
            errors.add("unreadable")
        if checked.failed_constraints:
            errors.add("form_constraint")
        if scenario.work_origin == "copy_error":
            errors.add("copy_error")
        require(errors == set(scenario.expected_error_kinds), "error kinds differ from expectation")
        rung = prepared.context.permitted_rung if prepared.context else HelpRung.NONE
        require(rung == scenario.permitted_rung, f"rung {rung.name} differs from expected opportunity")
        require(prepared.progress == scenario.expected_progress, "progress differs from replay")
        if "history" in scenario.provided_fields:
            require(prepared.session.history == scenario.history, "history differs from replay")
        if "transcript" in scenario.provided_fields:
            actual = prepared.session.transcript
            require(len(actual) == len(scenario.transcript), "transcript length differs from replay")
            for supplied, recorded in zip(scenario.transcript, actual):
                require(supplied.speaker == recorded.speaker and supplied.text == recorded.text and all(
                    getattr(supplied, key) is None or getattr(supplied, key) == getattr(recorded, key)
                    for key in ("record_id", "task_id", "revision", "at")), "transcript differs from replay")
        if scenario.current_interaction_id is not None:
            record = next((r for r in reversed(prepared.session.history)
                           if r.task_id == task.id and r.interaction is not None), None)
            require(record is not None and record.id == scenario.current_interaction_id,
                    "current interaction identity differs from replay")
    except FixtureError:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise FixtureError(f"{scenario.id}: {exc}") from exc
