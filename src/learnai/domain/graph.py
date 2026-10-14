# src/learnai/domain/graph.py
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from learnai.domain.enums import PrereqStrength
from learnai.domain.ids import SkillId
from learnai.domain.skills import PrereqEdge, Skill


class CycleError(ValueError):
    """Raised when hard prerequisite edges contain a cycle.

    Carries one offending path. The graph never breaks a cycle itself: which
    dependency is false — or whether a shared prerequisite is missing — is a
    pedagogical judgement it has no information to make. See spec §6.1, D11.
    """

    def __init__(self, cycle: tuple[SkillId, ...]) -> None:
        self.cycle = cycle
        super().__init__("hard prerequisites form a cycle: " + " -> ".join(cycle))


@dataclass(frozen=True, slots=True)
class SkillGraph:
    skills: dict[SkillId, Skill]
    _hard_in: dict[SkillId, frozenset[SkillId]]
    _soft_in: dict[SkillId, frozenset[SkillId]]
    _out: dict[SkillId, frozenset[SkillId]]

    @classmethod
    def build(cls, skills: Iterable[Skill], edges: Iterable[PrereqEdge]) -> "SkillGraph":
        by_id = {s.id: s for s in skills}
        hard_in: dict[SkillId, set[SkillId]] = defaultdict(set)
        soft_in: dict[SkillId, set[SkillId]] = defaultdict(set)
        out: dict[SkillId, set[SkillId]] = defaultdict(set)

        for e in edges:
            for sid in (e.from_skill, e.to_skill):
                if sid not in by_id:
                    raise KeyError(f"edge references unknown skill: {sid}")
            if e.strength is PrereqStrength.HARD:
                hard_in[e.to_skill].add(e.from_skill)
            else:
                soft_in[e.to_skill].add(e.from_skill)
            out[e.from_skill].add(e.to_skill)

        graph = cls(
            skills=by_id,
            _hard_in={k: frozenset(v) for k, v in hard_in.items()},
            _soft_in={k: frozenset(v) for k, v in soft_in.items()},
            _out={k: frozenset(v) for k, v in out.items()},
        )
        graph.topological_order()  # raises CycleError
        return graph

    def hard_prereqs(self, skill_id: SkillId) -> frozenset[SkillId]:
        return self._hard_in.get(skill_id, frozenset())

    def soft_prereqs(self, skill_id: SkillId) -> frozenset[SkillId]:
        return self._soft_in.get(skill_id, frozenset())

    def dependents(self, skill_id: SkillId) -> frozenset[SkillId]:
        return self._out.get(skill_id, frozenset())

    def frontier(self, learned: set[SkillId]) -> frozenset[SkillId]:
        return frozenset(
            sid
            for sid in self.skills
            if sid not in learned and self.hard_prereqs(sid) <= learned
        )

    def topological_order(self) -> tuple[SkillId, ...]:
        indegree = {sid: len(self.hard_prereqs(sid)) for sid in self.skills}
        ready = sorted(sid for sid, d in indegree.items() if d == 0)
        order: list[SkillId] = []
        while ready:
            sid = ready.pop(0)
            order.append(sid)
            for dep in sorted(self.dependents(sid)):
                if sid in self.hard_prereqs(dep):
                    indegree[dep] -= 1
                    if indegree[dep] == 0:
                        ready.append(dep)
            ready.sort()
        if len(order) != len(self.skills):
            raise CycleError(self._find_cycle(set(self.skills) - set(order)))
        return tuple(order)

    def _find_cycle(self, stuck: set[SkillId]) -> tuple[SkillId, ...]:
        """Walk backwards through hard prereqs, within the unordered skills, until one repeats.

        Every stuck skill has at least one stuck hard prereq — otherwise it would
        have been ordered — so the walk cannot dead-end and must close a loop.
        Skills merely downstream of the cycle are stuck too, but the walk leaves
        them behind. Smallest id at each choice, so the reported path is stable.
        """
        path: list[SkillId] = []
        position: dict[SkillId, int] = {}
        current = min(stuck)
        while current not in position:
            position[current] = len(path)
            path.append(current)
            current = min(self.hard_prereqs(current) & stuck)
        loop = path[position[current]:] + [current]
        return tuple(reversed(loop))  # prerequisite first, the way edges read
