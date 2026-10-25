"""Evaluator-only references from versioned fixtures, content and verified keys."""
from collections.abc import Mapping
from hashlib import sha256

from learnai.domain.enums import Verdict
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import MisconceptionId
from learnai.domain.items import Item
from learnai.domain.ports import Verifier
from learnai.domain.skills import Misconception
from learnai.eval.artifacts import encode
from learnai.eval.fixtures import Scenario
from learnai.eval.judge import JudgeReference
from learnai.eval.manifest import canonical_json


def build_reference(scenario: Scenario, *, item: Item, graph: SkillGraph,
                    catalogue: Mapping[MisconceptionId, Misconception], verifier: Verifier) -> JudgeReference:
    """No candidate text is accepted here. Missing curated reasoning stays empty."""
    answer = verifier.key_submission(item.answer_spec)
    answer.check_shape(item.answer_spec.kind)
    if verifier.check_answer(answer, item.answer_spec).verdict is not Verdict.CORRECT:
        raise ValueError(f'{scenario.id}: generated reference answer did not verify')
    skill = graph.skills[item.skill_id]
    material = {'scenario': encode(scenario), 'item': encode(item), 'notes': skill.teaching_notes,
                'misconceptions': [encode(catalogue[key]) for key in skill.misconception_ids]}
    digest = sha256(canonical_json(material).encode('utf-8')).hexdigest()
    return JudgeReference(answer, scenario.reference_reasoning, f'versioned-inputs:sha256:{digest}',
                          skill.teaching_notes,
                          tuple(catalogue[key].description for key in skill.misconception_ids),
                          scenario.evaluation_criteria)
