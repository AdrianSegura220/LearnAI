"""Explicit, strictly loaded authored items for evaluation-only replay."""
import math
from pathlib import Path
from typing import Any

import yaml

from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.domain.enums import AnswerKind, VettingLevel
from learnai.domain.ids import ItemId, SkillId, TemplateId
from learnai.domain.items import AnswerSpec, FormConstraint, Formula, Item, Provenance, Text
from learnai.eval.fixtures import FixtureError, _UniqueLoader


class EvaluationItems(GeneratorRegistry):
    """Keep authored lookup separate from generated practice suggestions."""

    def __init__(self, items: dict[str, Item], source_content: str) -> None:
        super().__init__(QUADRATICS_TEMPLATES)
        self.authored = items
        self.source_content = source_content

    def instantiate(self, template_id: TemplateId, seed: int) -> Item:
        if template_id in self.authored:
            if type(seed) is not int or seed != 0:
                raise FixtureError('authored evaluation items require seed 0')
            return self.authored[template_id]
        return super().instantiate(template_id, seed)


def _record(value: Any, keys: tuple[str, ...], where: str) -> dict:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise FixtureError(f'{where}: expected fields {sorted(keys)}')
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FixtureError('expected nonblank text')
    return value


def _texts(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise FixtureError('expected a list of text values')
    return tuple(_text(entry) for entry in value)


def load_authored_items(path: Path) -> EvaluationItems:
    content = path.read_text(encoding='utf-8')
    try:
        raw = yaml.load(content, Loader=_UniqueLoader)
    except yaml.YAMLError as exc:
        raise FixtureError(f'invalid authored YAML: {exc}') from exc
    raw = _record(raw, ('version', 'items'), 'authored catalogue')
    if type(raw['version']) is not int or raw['version'] != 1:
        raise FixtureError('authored version must be 1')
    if not isinstance(raw['items'], list) or not raw['items']:
        raise FixtureError('authored items must be a nonempty list')
    items = {}
    for entry in raw['items']:
        entry = _record(entry, ('id', 'skill_id', 'statement', 'answer', 'worked_steps', 'difficulty'), 'item')
        item_id, skill = _text(entry['id']), _text(entry['skill_id'])
        if not item_id.startswith('eval.authored.'):
            raise FixtureError('authored ids must start with eval.authored.')
        if item_id in items:
            raise FixtureError(f'duplicate authored id: {item_id}')
        difficulty = entry['difficulty']
        if type(difficulty) not in (int, float) or not math.isfinite(difficulty):
            raise FixtureError('difficulty must be finite numeric data')
        if not isinstance(entry['statement'], list) or not entry['statement']:
            raise FixtureError('statement must be a nonempty block list')
        blocks = []
        for block in entry['statement']:
            if not isinstance(block, dict) or set(block) not in ({'text'}, {'formula'}):
                raise FixtureError('statement block requires exactly text or formula')
            key = next(iter(block))
            blocks.append((Text if key == 'text' else Formula)(_text(block[key])))
        answer = _record(entry['answer'], ('expression', 'kind', 'form_constraints', 'label'), 'answer')
        if not isinstance(answer['kind'], str) or answer['kind'] not in AnswerKind.__members__:
            raise FixtureError('unknown answer kind')
        spec = AnswerSpec(_text(answer['expression']), tuple(FormConstraint(c) for c in _texts(answer['form_constraints'])),
                          AnswerKind[answer['kind']],
                          None if answer['label'] is None else _text(answer['label']))
        items[item_id] = Item(ItemId(item_id), SkillId(skill), Provenance.authored(), tuple(blocks), spec,
                              _texts(entry['worked_steps']), float(difficulty), VettingLevel.HUMAN_REVIEWED)
    return EvaluationItems(items, content)
