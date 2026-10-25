"""Strict, lossless scenario loading; expected findings remain evaluator data.

The legacy positional Scenario interface is retained. Parsed answers are always
Submission objects: field boundaries come from the fixture, never from math text.
History is an ordered, current-session snapshot using the domain's public types.
It carries no authoritative engine counters or provider-private trace records.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta
from enum import Enum
import json
import math
from pathlib import Path
from typing import Any, Literal, TypeVar

import yaml

from learnai.domain.enums import Confidence, EvidenceClass, HelpRung, Verdict
from learnai.domain.history import HistoryKind, HistoryRecord
from learnai.domain.ids import ItemId, MisconceptionId, SessionId, SkillId, StudentId, TaskId, TemplateId
from learnai.domain.interaction import InteractionKind, ResponseJob, StudentInteraction, TaskProgress, WorkStatus
from learnai.domain.items import FormConstraint, Submission
from learnai.domain.turn import Proposal, ProposalKind, TranscriptEntry, TutorTurn

FAMILIES = frozenset({"ladder", "diagnosis", "leak_bait", "decline", "extra"})
CORPUS_EXPECTATIONS = frozenset({
    "expected_statement", "work_origin", "exercise_anchor", "copy_error_description",
    "expected_verdict", "expected_diagnosis", "expected_broken_transition",
    "expected_step_check", "expected_error_kinds", "expected_failed_constraints",
    "coverage_tags", "expected_progress",
})
WorkOrigin = Literal["exercise", "copy_error", "none"]
ExpectedVerdict = Literal["CORRECT", "WRONG", "MALFORMED", "NO_ANSWER", "UNCHECKED"]
ErrorKind = Literal["equivalence", "form_constraint", "copy_error", "unreadable"]


class FixtureError(ValueError):
    """A fixture is malformed or its redundant views disagree."""


@dataclass(frozen=True, slots=True)
class HistoricalAction:
    """Evaluator replay input; scripts are private drafts, not delivered history."""

    operation: Literal["submit", "ask_question", "request_help"]
    at: datetime
    task_id: TaskId
    template_id: TemplateId
    seed: int
    interaction: StudentInteraction | None = None
    confidence: Confidence | None = None
    response_job: ResponseJob = ResponseJob.NORMAL
    tutor_script: tuple[TutorTurn | None, ...] = ()


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    family: str
    skill_id: SkillId
    template_id: TemplateId
    seed: int
    permitted_rung: HelpRung
    strength: float
    is_fresh: bool
    calibration_gap: float
    prior_misconceptions: tuple[MisconceptionId, ...]
    steps: tuple[str, ...]
    answer: Submission | str | list[str]
    declined: bool = False
    transcript: tuple[TranscriptEntry, ...] = ()
    notes: str = ""
    question: str | None = None
    referenced_step: int | None = None
    work_status: WorkStatus = WorkStatus.SUBMITTED
    work_revision: int = 0
    interaction_kind: InteractionKind = InteractionKind.SUBMISSION
    response_job: ResponseJob = ResponseJob.NORMAL
    history: tuple[HistoryRecord, ...] = ()
    current_interaction_id: str | None = None
    expected_statement: str | None = None
    work_origin: WorkOrigin | None = None
    exercise_anchor: str | None = None
    copy_error_description: str | None = None
    expected_verdict: ExpectedVerdict | None = None
    expected_diagnosis: MisconceptionId | None = None
    expected_broken_transition: tuple[str, str] | None = None
    expected_step_check: bool | None = None
    expected_error_kinds: tuple[ErrorKind, ...] = ()
    expected_failed_constraints: tuple[FormConstraint, ...] = ()
    coverage_tags: tuple[str, ...] = ()
    expected_progress: TaskProgress | None = None
    reference_reasoning: tuple[str, ...] = ()
    evaluation_criteria: tuple[str, ...] = ()
    history_actions: tuple[HistoricalAction, ...] = ()
    now: datetime = datetime(2026, 1, 1, tzinfo=UTC)
    confidence: Confidence = Confidence.UNSURE
    provided_fields: frozenset[str] = field(default_factory=frozenset, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.answer, Submission):
            object.__setattr__(self, "answer", _submission(self.answer, False, "answer"))

    @property
    def provided_expectations(self) -> frozenset[str]:
        return self.provided_fields & CORPUS_EXPECTATIONS

    @property
    def student_id(self) -> StudentId:
        return StudentId("eval-student")

    @property
    def session_id(self) -> SessionId:
        return SessionId(f"eval-session:{self.id}")

    @property
    def task_id(self) -> TaskId:
        return TaskId(f"eval-task:{self.id}")

    @property
    def interaction(self) -> StudentInteraction:
        assert isinstance(self.answer, Submission)
        return StudentInteraction(self.task_id, self.work_revision, self.interaction_kind,
                                  self.work_status, self.steps, self.answer, self.question,
                                  self.referenced_step)


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise FixtureError(f"{path} must be a mapping with string keys")
    return value


def _keys(raw: Mapping[str, Any], allowed: set[str], required: set[str], path: str) -> None:
    unknown, missing = set(raw) - allowed, required - set(raw)
    if unknown:
        raise FixtureError(f"{path}: unknown fields {sorted(unknown)}")
    if missing:
        raise FixtureError(f"{path}: missing fields {sorted(missing)}")


def _text(value: Any, path: str, *, nonblank: bool = False) -> str:
    if not isinstance(value, str) or (nonblank and not value.strip()):
        raise FixtureError(f"{path} must be {'a nonblank string' if nonblank else 'a string'}")
    return value


def _optional_text(value: Any, path: str) -> str | None:
    return None if value is None else _text(value, path, nonblank=True)


def _bool(value: Any, path: str) -> bool:
    if type(value) is not bool:
        raise FixtureError(f"{path} must be a boolean")
    return value


def _integer(value: Any, path: str, *, nonnegative: bool = True) -> int:
    if type(value) is not int or (nonnegative and value < 0):
        raise FixtureError(f"{path} must be {'a nonnegative' if nonnegative else 'an'} integer")
    return value


def _number(value: Any, path: str) -> float:
    if type(value) not in (int, float):
        raise FixtureError(f"{path} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise FixtureError(f"{path} must be a finite number") from exc
    if not math.isfinite(result):
        raise FixtureError(f"{path} must be a finite number")
    return result


def _sequence(value: Any, path: str) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        raise FixtureError(f"{path} must be a list")
    return tuple(value)


def _strings(value: Any, path: str, *, nonblank: bool = False) -> tuple[str, ...]:
    return tuple(_text(v, f"{path}[{i}]", nonblank=nonblank)
                 for i, v in enumerate(_sequence(value, path)))


E = TypeVar("E", bound=Enum)


def _enum(enum_type: type[E], value: Any, path: str) -> E:
    if isinstance(value, enum_type):
        return value
    # Names and exact enum values are accepted; bool must not match IntEnum 0/1.
    if type(value) is str:
        for member in enum_type:
            if value == member.name or value == member.value:
                return member
    elif type(value) is int:
        for member in enum_type:
            if type(member.value) is int and value == member.value:
                return member
    raise FixtureError(f"{path} must name a {enum_type.__name__}")


def _choice(value: Any, choices: set[str], path: str) -> str:
    value = _text(value, path)
    if value not in choices:
        raise FixtureError(f"{path} must be one of {sorted(choices)}")
    return value


def _submission(value: Any, claims_none: bool, path: str) -> Submission:
    if isinstance(value, str):
        answer_fields = (value,)
    else:
        answer_fields = _strings(value, path)
    result = Submission(answer_fields, claims_none)
    if claims_none and result.entries:
        raise FixtureError(f"{path} cannot list values while claiming none")
    return result


def _at(value: Any, path: str) -> datetime:
    if isinstance(value, datetime):
        at = value
    else:
        try:
            at = datetime.fromisoformat(_text(value, path))
        except ValueError as exc:
            raise FixtureError(f"{path} must be an aware UTC timestamp") from exc
    if at.tzinfo is None or at.utcoffset() != timedelta(0):
        raise FixtureError(f"{path} must be an aware UTC timestamp")
    return at


def _progress(value: Any) -> TaskProgress:
    raw = _mapping(value, "expected_progress")
    names = {f.name for f in fields(TaskProgress)}
    _keys(raw, names, names, "expected_progress")
    submissions = _integer(raw["submissions"], "expected_progress.submissions")
    attempts = _integer(raw["genuine_attempts"], "expected_progress.genuine_attempts")
    declines = _integer(raw["declines"], "expected_progress.declines")
    if submissions != attempts + declines:
        raise FixtureError("expected_progress: submissions must equal genuine_attempts + declines")
    last = raw["last_checked_revision"]
    return TaskProgress(submissions, attempts, declines,
        tuple(_enum(HelpRung, r, "expected_progress.delivered_rungs")
              for r in _sequence(raw["delivered_rungs"], "expected_progress.delivered_rungs")),
        _bool(raw["independence_spent"], "expected_progress.independence_spent"),
        None if last is None else _integer(last, "expected_progress.last_checked_revision"))


def _interaction(value: Any, path: str) -> StudentInteraction:
    raw = _mapping(value, path)
    _keys(raw, {f.name for f in fields(StudentInteraction)} | {"claims_none"},
          {"task_id", "revision", "kind", "status", "steps", "answer"}, path)
    answer = raw["answer"]
    claims_none = _bool(raw.get("claims_none", False), f"{path}.claims_none")
    if isinstance(answer, Mapping):
        _keys(answer, {"fields", "claims_none"}, {"fields", "claims_none"}, f"{path}.answer")
        if "claims_none" in raw:
            raise FixtureError(f"{path}: claims_none must occur only once")
        claims_none = _bool(answer["claims_none"], f"{path}.answer.claims_none")
        answer = answer["fields"]
    reference = raw.get("referenced_step")
    question = raw.get("question")
    if question is not None:
        question = _text(question, f"{path}.question")
    try:
        return StudentInteraction(
            TaskId(_text(raw["task_id"], f"{path}.task_id", nonblank=True)),
            _integer(raw["revision"], f"{path}.revision"),
            _enum(InteractionKind, raw["kind"], f"{path}.kind"),
            _enum(WorkStatus, raw["status"], f"{path}.status"),
            _strings(raw["steps"], f"{path}.steps"),
            _submission(answer, claims_none, f"{path}.answer"), question,
            None if reference is None else _integer(reference, f"{path}.referenced_step"),
        )
    except ValueError as exc:
        raise FixtureError(f"{path}: {exc}") from exc


def _tutor_script(value: Any, path: str) -> tuple[TutorTurn | None, ...]:
    result: list[TutorTurn | None] = []
    for index, value in enumerate(_sequence(value, path)):
        if value is None:
            result.append(None)
            continue
        entry_path = f"{path}[{index}]"
        raw = _mapping(value, entry_path)
        _keys(raw, {f.name for f in fields(TutorTurn)}, {"message", "rung_used"}, entry_path)
        proposals: list[Proposal] = []
        for proposal_value in _sequence(raw.get("proposals", ()), f"{entry_path}.proposals"):
            proposal = _mapping(proposal_value, f"{entry_path}.proposals")
            _keys(proposal, {"kind", "target_skill_id"}, {"kind"}, f"{entry_path}.proposals")
            proposals.append(Proposal(_enum(ProposalKind, proposal["kind"], f"{entry_path}.proposals.kind"),
                _optional_text(proposal.get("target_skill_id"), f"{entry_path}.proposals.target_skill_id")))
        # Empty/invalid pedagogical drafts are valid replay inputs: the actual
        # engine validator, not the fixture parser, decides whether to deliver.
        result.append(TutorTurn(_text(raw["message"], f"{entry_path}.message"),
            _enum(HelpRung, raw["rung_used"], f"{entry_path}.rung_used"),
            _optional_text(raw.get("diagnosis"), f"{entry_path}.diagnosis"), tuple(proposals)))
    return tuple(result)


def _actions(value: Any, scenario: Scenario) -> tuple[HistoricalAction, ...]:
    result: list[HistoricalAction] = []
    names = {f.name for f in fields(HistoricalAction)}
    required = {"operation", "at", "task_id", "template_id", "seed"}
    identities: dict[str, tuple[str, int]] = {
        scenario.task_id: (scenario.template_id, scenario.seed),
    }
    work: dict[str, StudentInteraction] = {}
    for index, value in enumerate(_sequence(value, "history_actions")):
        path = f"history_actions[{index}]"
        raw = _mapping(value, path)
        _keys(raw, names, required, path)
        operation = _choice(raw["operation"], {"submit", "ask_question", "request_help"}, f"{path}.operation")
        at = _at(raw["at"], f"{path}.at")
        if at > scenario.now or (result and at < result[-1].at):
            raise FixtureError(f"{path}: actions must be chronological and no later than now")
        task_id = _text(raw["task_id"], f"{path}.task_id", nonblank=True)
        template_id = _text(raw["template_id"], f"{path}.template_id", nonblank=True)
        seed = _integer(raw["seed"], f"{path}.seed", nonnegative=False)
        identity = (template_id, seed)
        if task_id in identities and identities[task_id] != identity:
            raise FixtureError(f"{path}: task template/seed disagrees with previous action or scenario")
        identities[task_id] = identity
        interaction = None if raw.get("interaction") is None else _interaction(raw["interaction"], f"{path}.interaction")
        confidence = None if raw.get("confidence") is None else _enum(Confidence, raw["confidence"], f"{path}.confidence")
        job = _enum(ResponseJob, raw.get("response_job", "NORMAL"), f"{path}.response_job")
        if operation == "request_help":
            if interaction is not None:
                raise FixtureError(f"{path}: request_help uses stored work, not an interaction override")
        else:
            kind = InteractionKind.SUBMISSION if operation == "submit" else InteractionKind.TASK_QUESTION
            if interaction is None or interaction.task_id != task_id or interaction.kind is not kind:
                raise FixtureError(f"{path}: action requires a matching task and interaction kind")
            _consistent_work(work.get(task_id), interaction, path)
            work[task_id] = interaction
        if (operation == "submit") != (confidence is not None):
            raise FixtureError(f"{path}: explicit confidence is required only for submit")
        if operation != "ask_question" and job is not ResponseJob.NORMAL:
            raise FixtureError(f"{path}: only ask_question accepts a response job")
        result.append(HistoricalAction(operation, at, TaskId(task_id), TemplateId(template_id), seed,
            interaction, confidence, job, _tutor_script(raw.get("tutor_script", ()), f"{path}.tutor_script")))
    _consistent_work(work.get(scenario.task_id), scenario.interaction, "current interaction")
    return tuple(result)


def _history(value: Any, scenario: Scenario) -> tuple[HistoryRecord, ...]:
    records: list[HistoryRecord] = []
    by_id: dict[str, HistoryRecord] = {}
    tasks: dict[str, tuple[str, str]] = {}
    work: dict[str, StudentInteraction] = {}
    names = {f.name for f in fields(HistoryRecord)}
    required = {"id", "at", "student_id", "session_id", "task_id", "item_id", "skill_id", "revision", "kind"}
    student_kinds = {HistoryKind.SUBMISSION: InteractionKind.SUBMISSION,
                     HistoryKind.STUDENT_QUESTION: InteractionKind.TASK_QUESTION,
                     HistoryKind.HELP_REQUEST: InteractionKind.HELP_REQUEST}
    for index, value in enumerate(_sequence(value, "history")):
        path = f"history[{index}]"
        raw = _mapping(value, path)
        _keys(raw, names, required, path)
        record_id = _text(raw["id"], f"{path}.id", nonblank=True)
        if record_id in by_id:
            raise FixtureError(f"{path}: duplicate history id {record_id}")
        at = _at(raw["at"], f"{path}.at")
        if records and at < records[-1].at:
            raise FixtureError(f"{path}: history must be chronological")
        student_id = _text(raw["student_id"], f"{path}.student_id", nonblank=True)
        session_id = _text(raw["session_id"], f"{path}.session_id", nonblank=True)
        if student_id != scenario.student_id or session_id != scenario.session_id:
            raise FixtureError(f"{path}: history cannot override the bound student/session")
        task_id = _text(raw["task_id"], f"{path}.task_id", nonblank=True)
        item_id = _text(raw["item_id"], f"{path}.item_id", nonblank=True)
        skill_id = _text(raw["skill_id"], f"{path}.skill_id", nonblank=True)
        if task_id == scenario.task_id and skill_id != scenario.skill_id:
            raise FixtureError(f"{path}: current task skill disagrees with scenario")
        identity = (item_id, skill_id)
        if task_id in tasks and tasks[task_id] != identity:
            raise FixtureError(f"{path}: a task cannot change item or skill")
        tasks[task_id] = identity
        revision = _integer(raw["revision"], f"{path}.revision")
        kind = _enum(HistoryKind, raw["kind"], f"{path}.kind")
        interaction = None if raw.get("interaction") is None else _interaction(raw["interaction"], f"{path}.interaction")
        message = raw.get("message")
        if message is not None:
            message = _text(message, f"{path}.message", nonblank=True)
        verdict = None if raw.get("verdict") is None else _enum(Verdict, raw["verdict"], f"{path}.verdict")
        evidence = None if raw.get("evidence_class") is None else _enum(EvidenceClass, raw["evidence_class"], f"{path}.evidence_class")
        rung = None if raw.get("rung") is None else _enum(HelpRung, raw["rung"], f"{path}.rung")
        related = _strings(raw.get("related_record_ids", ()), f"{path}.related_record_ids", nonblank=True)
        if kind in student_kinds:
            if interaction is None or interaction.kind is not student_kinds[kind]:
                raise FixtureError(f"{path}: history kind requires a matching interaction")
            if interaction.task_id != task_id or interaction.revision != revision:
                raise FixtureError(f"{path}: interaction provenance disagrees with record")
            if message is not None or rung is not None or related:
                raise FixtureError(f"{path}: student records cannot carry delivered/private content")
            if kind is not HistoryKind.SUBMISSION and (verdict is not None or evidence is not None):
                raise FixtureError(f"{path}: only submissions can carry historical verdict/evidence")
            _consistent_work(work.get(task_id), interaction, path)
            work[task_id] = interaction
        else:
            if interaction is not None or message is None or rung is None or verdict is not None or evidence is not None:
                raise FixtureError(f"{path}: delivery requires message/rung and no submission data")
            if len(related) != 1 or related[0] not in by_id:
                raise FixtureError(f"{path}: delivery must link a preceding student record")
            request = by_id[related[0]]
            if request.interaction is None or (request.task_id, request.item_id, request.skill_id, request.revision) != (task_id, item_id, skill_id, revision):
                raise FixtureError(f"{path}: delivery link has inconsistent provenance")
            if (kind is HistoryKind.HELP_DELIVERED) != (request.kind is HistoryKind.HELP_REQUEST):
                raise FixtureError(f"{path}: delivery kind disagrees with request")
        record = HistoryRecord(record_id, at, StudentId(student_id), SessionId(session_id),
            TaskId(task_id), ItemId(item_id), SkillId(skill_id), revision, kind, interaction,
            message, verdict, evidence, rung, related)
        records.append(record)
        by_id[record_id] = record
    _consistent_work(work.get(scenario.task_id), scenario.interaction, "current interaction")
    if scenario.current_interaction_id is not None:
        current = by_id.get(scenario.current_interaction_id)
        if current is None or current.interaction != scenario.interaction:
            raise FixtureError("current_interaction_id must name the matching current student interaction")
        latest = next((r for r in reversed(records) if r.task_id == scenario.task_id and r.interaction is not None), None)
        if current != latest:
            raise FixtureError("current_interaction_id must name the latest current-task interaction")
    return tuple(records)


def _consistent_work(previous: StudentInteraction | None, current: StudentInteraction, path: str) -> None:
    if previous is None:
        return
    if current.revision < previous.revision:
        raise FixtureError(f"{path}: stale work revision")
    if current.revision == previous.revision and (current.steps != previous.steps or current.answer != previous.answer):
        raise FixtureError(f"{path}: changed work requires a greater revision")


def _history_transcript(records: tuple[HistoryRecord, ...]) -> tuple[TranscriptEntry, ...]:
    result: list[TranscriptEntry] = []
    for record in records:
        if record.kind is HistoryKind.HELP_REQUEST:
            continue
        interaction = record.interaction
        if interaction is not None:
            text = "\n".join((*interaction.steps, *interaction.answer.fields,
                              *((interaction.question,) if interaction.question is not None else ())))
            speaker = "student"
        else:
            assert record.message is not None
            text, speaker = record.message, "tutor"
        result.append(TranscriptEntry(speaker, text, record.id, record.task_id, record.revision, record.at))
    return tuple(result)


def _transcript(value: Any) -> tuple[TranscriptEntry, ...]:
    result: list[TranscriptEntry] = []
    names = {f.name for f in fields(TranscriptEntry)}
    for index, value in enumerate(_sequence(value, "transcript")):
        path = f"transcript[{index}]"
        raw = _mapping(value, path)
        _keys(raw, names, {"speaker", "text"}, path)
        revision = raw.get("revision")
        result.append(TranscriptEntry(
            _choice(raw["speaker"], {"student", "tutor"}, f"{path}.speaker"),
            _text(raw["text"], f"{path}.text"),
            _optional_text(raw.get("record_id"), f"{path}.record_id"),
            _optional_text(raw.get("task_id"), f"{path}.task_id"),
            None if revision is None else _integer(revision, f"{path}.revision"),
            None if raw.get("at") is None else _at(raw["at"], f"{path}.at"),
        ))
    return tuple(result)


def _match_transcript(supplied: tuple[TranscriptEntry, ...], canonical: tuple[TranscriptEntry, ...]) -> None:
    if len(supplied) != len(canonical):
        raise FixtureError("transcript disagrees with canonical history")
    for supplied_entry, canonical_entry in zip(supplied, canonical):
        if supplied_entry.speaker != canonical_entry.speaker or supplied_entry.text != canonical_entry.text:
            raise FixtureError("transcript disagrees with canonical history")
        for name in ("record_id", "task_id", "revision", "at"):
            value = getattr(supplied_entry, name)
            if value is not None and value != getattr(canonical_entry, name):
                raise FixtureError(f"transcript {name} disagrees with canonical history")


def parse_scenario(raw: Mapping[str, Any]) -> Scenario:
    """Parse exact user fields and checked provenance, without generating content.

    Learner traits seed initial state at the first historical action's time (or
    ``now`` when there is no action). They are not asserted final summaries;
    replay and the shared context builder derive the current state.
    """
    raw = _mapping(raw, "scenario")
    allowed = {f.name for f in fields(Scenario) if f.init} | {"claims_none"}
    required = {"id", "family", "skill_id", "template_id", "seed", "permitted_rung",
                "strength", "is_fresh", "calibration_gap", "prior_misconceptions", "steps", "answer"}
    _keys(raw, allowed, required, "scenario")
    kwargs: dict[str, Any] = {
        "id": _text(raw["id"], "id", nonblank=True),
        "family": _choice(raw["family"], set(FAMILIES), "family"),
        "skill_id": SkillId(_text(raw["skill_id"], "skill_id", nonblank=True)),
        "template_id": TemplateId(_text(raw["template_id"], "template_id", nonblank=True)),
        "seed": _integer(raw["seed"], "seed", nonnegative=False),
        "permitted_rung": _enum(HelpRung, raw["permitted_rung"], "permitted_rung"),
        "strength": _number(raw["strength"], "strength"),
        "is_fresh": _bool(raw["is_fresh"], "is_fresh"),
        "calibration_gap": _number(raw["calibration_gap"], "calibration_gap"),
        "prior_misconceptions": _strings(raw["prior_misconceptions"], "prior_misconceptions", nonblank=True),
        "steps": _strings(raw["steps"], "steps"),
        "answer": _submission(raw["answer"], _bool(raw.get("claims_none", False), "claims_none"), "answer"),
        "declined": _bool(raw.get("declined", False), "declined"),
        "notes": _text(raw.get("notes", ""), "notes"),
        "question": None if raw.get("question") is None else _text(raw["question"], "question"),
        "referenced_step": None if raw.get("referenced_step") is None else _integer(raw["referenced_step"], "referenced_step"),
        "work_status": _enum(WorkStatus, raw.get("work_status", "SUBMITTED"), "work_status"),
        "work_revision": _integer(raw.get("work_revision", 0), "work_revision"),
        "interaction_kind": _enum(InteractionKind, raw.get("interaction_kind", "SUBMISSION"), "interaction_kind"),
        "response_job": _enum(ResponseJob, raw.get("response_job", "NORMAL"), "response_job"),
        "current_interaction_id": _optional_text(raw.get("current_interaction_id"), "current_interaction_id"),
        "now": _at(raw.get("now", datetime(2026, 1, 1, tzinfo=UTC)), "now"),
        "confidence": _enum(Confidence, raw.get("confidence", "UNSURE"), "confidence"),
    }
    for name in ("expected_statement", "exercise_anchor", "copy_error_description", "expected_diagnosis"):
        if name in raw:
            if name == "expected_statement":
                kwargs[name] = _text(raw[name], name, nonblank=True)
            else:
                kwargs[name] = _optional_text(raw[name], name)
    for name, choices in (("work_origin", {"exercise", "copy_error", "none"}),
        ("expected_verdict", {"CORRECT", "WRONG", "MALFORMED", "NO_ANSWER", "UNCHECKED"})):
        if name in raw:
            kwargs[name] = _choice(raw[name], choices, name)
    if "expected_step_check" in raw:
        kwargs["expected_step_check"] = _bool(raw["expected_step_check"], "expected_step_check")
    if "expected_broken_transition" in raw:
        transition = raw["expected_broken_transition"]
        if transition is not None:
            transition = _strings(transition, "expected_broken_transition")
            if len(transition) != 2:
                raise FixtureError("expected_broken_transition must contain two steps")
        kwargs["expected_broken_transition"] = transition
    for name in ("expected_failed_constraints", "coverage_tags", "reference_reasoning", "evaluation_criteria"):
        if name in raw:
            kwargs[name] = _strings(raw[name], name, nonblank=True)
    if "expected_error_kinds" in raw:
        kwargs["expected_error_kinds"] = tuple(_choice(v, {"equivalence", "form_constraint", "copy_error", "unreadable"}, "expected_error_kinds")
            for v in _sequence(raw["expected_error_kinds"], "expected_error_kinds"))
    if "expected_progress" in raw:
        kwargs["expected_progress"] = _progress(raw["expected_progress"])
    origin = kwargs.get("work_origin")
    if origin == "copy_error":
        if kwargs.get("exercise_anchor") is None or kwargs.get("copy_error_description") is None:
            raise FixtureError("copy_error requires exercise_anchor and copy_error_description")
    elif kwargs.get("copy_error_description") is not None:
        raise FixtureError("copy_error_description is only valid for work_origin=copy_error")
    if origin == "exercise" and kwargs.get("exercise_anchor") is None:
        raise FixtureError("work_origin=exercise requires exercise_anchor")
    if origin == "none" and kwargs.get("exercise_anchor") is not None:
        raise FixtureError("work_origin=none cannot carry an exercise_anchor")
    result = Scenario(**kwargs)
    answer = result.answer
    assert isinstance(answer, Submission)
    if result.declined and not answer.is_blank:
        raise FixtureError("declined cannot coexist with an answer or claims_none")
    if result.interaction_kind is InteractionKind.SUBMISSION and answer.is_blank and not result.declined:
        raise FixtureError("a submission requires an answer, explicit decline, or claims_none")
    try:
        result.interaction  # Validate referenced-step bounds using the shared domain type.
    except ValueError as exc:
        raise FixtureError(str(exc)) from exc
    actions = _actions(raw.get("history_actions", ()), result)
    records = _history(raw.get("history", ()), result)
    transcript = _transcript(raw.get("transcript", ()))
    if "history" in raw:
        canonical = _history_transcript(records)
        if "transcript" in raw:
            _match_transcript(transcript, canonical)
        transcript = canonical
    object.__setattr__(result, "history_actions", actions)
    object.__setattr__(result, "history", records)
    object.__setattr__(result, "transcript", transcript)
    object.__setattr__(result, "provided_fields", frozenset(raw))
    return result


def validate_corpus_expectations(scenario: Scenario) -> None:
    """Require explicit corpus assertions; the legacy loader remains permissive.

    In particular, explicit null diagnosis/transition metadata differs from a
    missing assertion. Actual generation, verification and replay belong to the
    corpus preflight, which must compare these expectations independently.
    """
    missing = CORPUS_EXPECTATIONS - scenario.provided_expectations
    if missing:
        raise FixtureError(f"{scenario.id}: missing corpus expectations {sorted(missing)}")


def _unique_pairs(pairs: list[tuple[Any, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if not isinstance(key, str):
            raise FixtureError("mapping keys must be strings")
        if key in result:
            raise FixtureError(f"duplicate mapping key: {key}")
        result[key] = value
    return result


class _UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[str, Any]:
        if not isinstance(node, yaml.MappingNode):
            raise FixtureError("expected a YAML mapping")
        self.flatten_mapping(node)
        return _unique_pairs([(self.construct_object(key, deep=deep), self.construct_object(value, deep=deep))
                              for key, value in node.value])


def load_scenarios_dir(directory: Path) -> tuple[Scenario, ...]:
    """Load .json/.yaml/.yml files in path order, rejecting duplicate scenario ids.

    A file contains one scenario mapping or a list of scenario mappings. Other
    file suffixes are ignored. Parser failures retain their source filename.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise FixtureError(f"scenario directory does not exist: {directory}")
    result: list[Scenario] = []
    seen: set[str] = set()
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".json", ".yaml", ".yml"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
            raw = (json.loads(text, object_pairs_hook=_unique_pairs) if path.suffix.lower() == ".json"
                   else yaml.load(text, Loader=_UniqueLoader))
            entries = raw if isinstance(raw, list) else [raw]
            for entry in entries:
                scenario = parse_scenario(entry)
                if scenario.id in seen:
                    raise FixtureError(f"duplicate scenario id: {scenario.id}")
                seen.add(scenario.id)
                result.append(scenario)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise FixtureError(f"{path}: {exc}") from exc
    return tuple(result)
