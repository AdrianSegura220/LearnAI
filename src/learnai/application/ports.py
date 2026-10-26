"""SDK-free provider construction contracts."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TYPE_CHECKING

from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.configuration import PreparedRequest, ResolvedRoleConfig
from learnai.adapters.tutor.observations import TraceSink
from learnai.adapters.tutor.routing import BudgetProfile, Route
from learnai.domain.ids import MisconceptionId
from learnai.domain.ports import Tutor
from learnai.domain.skills import Misconception
from learnai.domain.turn import TurnContext
from learnai.eval.ports import Judge

if TYPE_CHECKING:
    from learnai.eval.judge import JudgePacket


@dataclass(frozen=True)
class TutorDependencies:
    items: GeneratorRegistry
    catalogue: Mapping[MisconceptionId, Misconception]


class ProviderClient(Protocol):
    def close(self) -> None: ...


class ProviderFactory(Protocol):
    provider: str
    api_family: str
    credential_env: str
    sdk_distribution: str
    sdk_module: str
    usage_mapper_id: str
    schema_ids: Mapping[str, str]
    role_dependencies: Mapping[str, tuple[str, ...]]

    def validate_route(self, route: Route, *, role: str) -> None: ...
    def resolve_config(self, route: Route, *, role: str,
                       profiles: Mapping[str, BudgetProfile], prompts_root: Path) -> ResolvedRoleConfig: ...
    def prepare_tutor(self, config: ResolvedRoleConfig, *, context: TurnContext,
                      dependencies: TutorDependencies) -> PreparedRequest: ...
    def prepare_judge(self, config: ResolvedRoleConfig, *, packet: JudgePacket) -> PreparedRequest: ...
    def create_client(self, *, api_key: str) -> ProviderClient: ...
    def create_tutor(self, *, config: ResolvedRoleConfig, client: ProviderClient,
                     dependencies: TutorDependencies, trace_sink: TraceSink) -> Tutor: ...
    def create_judge(self, *, config: ResolvedRoleConfig, client: ProviderClient,
                     trace_sink: TraceSink) -> Judge: ...
