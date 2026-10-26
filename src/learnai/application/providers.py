"""Operation-scoped provider selection, validation, and lazy resource ownership."""
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from importlib.util import find_spec
from pathlib import Path
from types import MappingProxyType

from learnai.adapters.tutor.configuration import ResolvedRoleConfig
from learnai.adapters.tutor.routing import BudgetProfile, Route, resolve_route, resolve_tutor_route
from learnai.application.ports import ProviderClient, ProviderFactory, TutorDependencies
from learnai.application.tutor_router import TutorRouter
from learnai.domain.interaction import ResponseJob
from learnai.domain.turn import TurnContext
from learnai.eval.accounting import RequestLedger
from learnai.eval.ports import Judge


class ProviderRegistry:
    def __init__(self, factories: Mapping[str, ProviderFactory]):
        self._factories = dict(factories)
        for name, factory in self._factories.items():
            if name != factory.provider:
                raise ValueError(f'provider registry key does not match factory: {name}')

    def get(self, provider: str) -> ProviderFactory:
        try:
            return self._factories[provider]
        except KeyError as exc:
            raise ValueError(f'unknown provider: {provider}') from exc


def default_registry() -> ProviderRegistry:
    from learnai.adapters.tutor.anthropic.wiring import AnthropicFactory
    return ProviderRegistry({'anthropic': AnthropicFactory()})


@dataclass(frozen=True)
class OperationRoutes:
    tutors: Mapping[ResponseJob, Route]
    judge: Route | None

    def __post_init__(self) -> None:
        object.__setattr__(self, 'tutors', MappingProxyType(dict(self.tutors)))


def resolve_operation_routes(*, routes: Mapping[str, Route], contexts: Iterable[TurnContext],
                             judge_route_name: str, smoke: bool, rejudge: bool) -> OperationRoutes:
    jobs = {context.response_job for context in contexts} if not rejudge else set()
    needs_judge = bool(jobs) or rejudge
    if smoke and not rejudge:
        jobs.add(ResponseJob.NORMAL)
    return OperationRoutes({job: resolve_tutor_route(routes, job) for job in sorted(jobs, key=lambda j: j.value)},
                          resolve_route(routes, judge_route_name) if needs_judge else None)


class ProviderServices:
    def __init__(self, *, selected: OperationRoutes, registry: ProviderRegistry,
                 environment: Mapping[str, str], dependencies: TutorDependencies | None,
                 profiles: Mapping[str, BudgetProfile], prompts_root: Path, ledger: RequestLedger):
        self.selected, self.registry = selected, registry
        self._environment = dict(environment)
        self.dependencies, self.profiles, self.prompts_root = dependencies, dict(profiles), prompts_root
        self.ledger = ledger
        self._configs: dict[tuple[str, str], ResolvedRoleConfig] = {}
        self._clients: dict[str, ProviderClient] = {}
        self._keys: dict[str, str] = {}
        self._validated = False
        self._closed = False

    @property
    def resolved_configs(self) -> Mapping[tuple[str, str], ResolvedRoleConfig]:
        return MappingProxyType(deepcopy(self._configs))

    def validate(self) -> None:
        if self._validated:
            return
        roles = [('tutor', route) for route in self.selected.tutors.values()]
        if self.selected.judge is not None:
            roles.append(('judge', self.selected.judge))
        # Structural provider resolution precedes settings, package, or key checks.
        factories = {route.adapter: self.registry.get(route.adapter) for _, route in roles}
        configs, keys = {}, {}
        for role, route in roles:
            factory = factories[route.adapter]
            factory.validate_route(route, role=role)
            config = factory.resolve_config(route, role=role, profiles=self.profiles, prompts_root=self.prompts_root)
            if config.provider != route.adapter or config.role != role or config.route != route:
                raise ValueError('factory returned conflicting resolved configuration')
            configs[role, route.name] = config
            if role == 'tutor' and self.dependencies is None:
                raise ValueError('selected tutor requires TutorDependencies')
            for package in set(factory.role_dependencies[role]) | {factory.sdk_distribution}:
                try:
                    distribution(package)
                except PackageNotFoundError as exc:
                    raise ValueError(f'selected {role} requires package: {package}') from exc
            if find_spec(factory.sdk_module) is None:
                raise ValueError(f'selected provider requires SDK: {factory.sdk_module}')
            key = self._environment.get(factory.credential_env)
            if not key or not key.strip():
                raise ValueError(f'{factory.credential_env} is required for selected {role}')
            keys[route.adapter] = key
        self._configs, self._keys, self._validated = configs, keys, True

    def _client(self, provider: str) -> ProviderClient:
        if not self._validated or self._closed:
            raise RuntimeError('provider services must be validated and open')
        if provider not in self._clients:
            try:
                self._clients[provider] = self.registry.get(provider).create_client(api_key=self._keys[provider])
            except BaseException:
                self._close(suppress_errors=True)
                raise
        return self._clients[provider]

    def tutor(self, *, phase: str, scenario_id: str | None = None) -> TutorRouter:
        sink = self.ledger.sink(phase=phase, scenario_id=scenario_id)
        def create(route, context):
            config = self._configs['tutor', route.name]
            factory = self.registry.get(route.adapter)
            factory.prepare_tutor(config, context=context, dependencies=self.dependencies)
            return factory.create_tutor(config=config, client=self._client(route.adapter),
                                         dependencies=self.dependencies, trace_sink=sink)
        return TutorRouter(self.selected.tutors, create)

    def judge(self, *, scenario_id: str) -> Judge:
        route = self.selected.judge
        if route is None:
            raise ValueError('no judge selected for this operation')
        return self.registry.get(route.adapter).create_judge(config=self._configs['judge', route.name],
            client=self._client(route.adapter), trace_sink=self.ledger.sink(phase='judge', scenario_id=scenario_id))

    def __enter__(self) -> "ProviderServices":
        self.validate()
        return self

    def _close(self, *, suppress_errors: bool) -> None:
        self._closed = True
        self._keys.clear()
        self._environment.clear()
        clients, self._clients = self._clients, {}
        error = None
        for client in clients.values():
            try:
                client.close()
            except BaseException as exc:
                if error is None:
                    error = exc
        if error is not None and not suppress_errors:
            raise error

    def __exit__(self, exc_type, exc, traceback):
        self._close(suppress_errors=exc is not None)
