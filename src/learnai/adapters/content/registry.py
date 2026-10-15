# src/learnai/adapters/content/registry.py
import random
from collections.abc import Iterable

from learnai.adapters.content.types import GeneratedProblem, TemplateSpec
from learnai.domain.enums import VettingLevel
from learnai.domain.ids import ItemId, SkillId, TemplateId
from learnai.domain.items import AnswerSpec, Item, Provenance


class GeneratorRegistry:
    """An ItemSource backed by deterministic parameterised generators."""

    def __init__(self, specs: Iterable[TemplateSpec]) -> None:
        self._by_id: dict[TemplateId, TemplateSpec] = {s.id: s for s in specs}
        self._by_skill: dict[SkillId, list[TemplateSpec]] = {}
        for spec in self._by_id.values():
            self._by_skill.setdefault(spec.skill_id, []).append(spec)

    def all_templates(self) -> tuple[TemplateSpec, ...]:
        return tuple(self._by_id.values())

    def templates_for(self, skill_id: SkillId) -> tuple[TemplateSpec, ...]:
        return tuple(self._by_skill.get(skill_id, ()))

    def instantiate_raw(self, template_id: TemplateId, seed: int) -> GeneratedProblem:
        spec = self._by_id[template_id]
        return spec.generate(random.Random(f"{template_id}:{seed}"))

    def instantiate(self, template_id: TemplateId, seed: int) -> Item:
        spec = self._by_id[template_id]
        problem = self.instantiate_raw(template_id, seed)
        return Item(
            id=ItemId(f"{template_id}#{seed}"),
            skill_id=spec.skill_id,
            provenance=Provenance.generated(template_id, seed),
            statement=problem.statement,
            answer_spec=AnswerSpec(
                expression=problem.answer,
                form_constraints=problem.form_constraints,
                kind=problem.kind,
                label=problem.label,
            ),
            worked_steps=problem.worked_steps,
            difficulty=spec.difficulty,
            vetting_level=VettingLevel.MACHINE_VERIFIED,
        )

    def next_item(self, skill_id: SkillId, target_difficulty: float, seed: int) -> Item:
        candidates = self.templates_for(skill_id)
        if not candidates:
            raise KeyError(f"no template registered for skill {skill_id}")
        chosen = min(candidates, key=lambda s: abs(s.difficulty - target_difficulty))
        return self.instantiate(chosen.id, seed)
