"""Resolved role inputs and exact local request preparation, without SDK state."""
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from typing import Literal

from learnai.adapters.tutor.observations import _plain_json
from learnai.adapters.tutor.context import ContextView
from learnai.adapters.tutor.prompts import TutorPrompt
from learnai.adapters.tutor.routing import BudgetProfile, Route


def schema_hash(value: object) -> str:
    """Hash actual JSON schema content consistently across provider encoders."""
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


@dataclass(frozen=True, slots=True)
class ResolvedRoleConfig:
    provider: str
    api_family: str
    role: Literal['tutor', 'judge']
    route: Route
    profile: BudgetProfile
    prompt: TutorPrompt
    effective_settings: Mapping[str, object]
    schema_hashes: Mapping[str, str]
    dependency_versions: Mapping[str, str | None]
    usage_mapper_id: str
    token_counter_id: str

    def __post_init__(self) -> None:
        if self.role not in ('tutor', 'judge') or self.provider != self.route.adapter:
            raise ValueError('resolved role/provider disagrees with route')
        _plain_json(self.route.provider_options)
        _plain_json(self.effective_settings)
        object.__setattr__(self, 'route', replace(self.route, provider_options=deepcopy(dict(self.route.provider_options))))
        for name in ('effective_settings', 'schema_hashes', 'dependency_versions'):
            object.__setattr__(self, name, deepcopy(dict(getattr(self, name))))


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    payload: Mapping[str, object]
    input_units: int
    output_reservation: int
    admitted: bool
    context_view: ContextView | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, 'payload', _plain_json(self.payload))
