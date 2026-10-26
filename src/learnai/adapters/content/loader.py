# src/learnai/adapters/content/loader.py
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from learnai.domain.enums import ConceptKind, PrereqStrength
from learnai.domain.graph import CycleError, SkillGraph
from learnai.domain.ids import ConceptId, MisconceptionId, SkillId, VerificationKind
from learnai.domain.skills import Concept, Misconception, PrereqEdge, Skill


class ContentError(ValueError):
    """Raised when a content file is structurally invalid."""


@dataclass(frozen=True, slots=True)
class LoadedCluster:
    graph: SkillGraph
    concepts: dict[ConceptId, Concept]
    misconceptions: dict[MisconceptionId, Misconception]


def parse_cluster(raw: Mapping[str, Any]) -> LoadedCluster:
    """Validate and build a cluster from already-decoded content.

    Every content rule lives here, deliberately apart from any I/O, so that
    each source runs the same checks. A source that admitted content this
    rejects would be a quiet route to a broken graph — and a Postgres reader
    that re-implemented the rules would drift from this one within a release.
    """
    subject = raw.get("subject")
    if not subject:
        raise ContentError("cluster file has no subject")

    # Which checker grades a skill is a fact about the content, so the content
    # states it. A fallback here would send any cluster that forgot the key to
    # SymPy — a history cluster graded as algebra, silently. The token stays
    # opaque: whether a verifier exists for it is the engine's check (Task 17).
    default_verification = raw.get("verification")
    if not default_verification:
        raise ContentError("cluster file has no verification kind")

    skills: list[Skill] = []
    edges: list[PrereqEdge] = []

    # Catalogues first: concepts and misconceptions are shared, so they are
    # authored once at the top level and referenced by id from any number of
    # skills. A single owner would force duplication, and duplicating a concept
    # duplicates its memory state.
    misconceptions: dict[MisconceptionId, Misconception] = {}
    for mc in raw.get("misconceptions", []):
        mid = MisconceptionId(mc["id"])
        if mid in misconceptions:
            raise ContentError(f"duplicate misconception id: {mid}")
        misconceptions[mid] = Misconception(
            id=mid,
            subject_id=subject,
            name=mc["name"],
            description=mc["description"],
            signature=mc["signature"],
        )

    concepts: dict[ConceptId, Concept] = {}
    for c in raw.get("concepts", []):
        cid = ConceptId(c["id"])
        if cid in concepts:
            raise ContentError(f"duplicate concept id: {cid}")
        concepts[cid] = Concept(
            id=cid,
            subject_id=subject,
            kind=ConceptKind(c["kind"]),
            prompt=c["prompt"],
            answer=c["answer"],
            introduced_by=SkillId(c["introduced_by"]) if c.get("introduced_by") else None,
        )

    referenced_mcs: set[MisconceptionId] = set()
    # The skills_for_concept index Slice 2 will expose; here it only validates.
    concept_users: dict[ConceptId, set[SkillId]] = defaultdict(set)
    seen_skills: set[SkillId] = set()

    for entry in raw.get("skills", []):
        sid = SkillId(entry["id"])
        # SkillGraph.build collapses duplicates last-wins (domain/graph.py), so
        # catch them here: a silent loss of a skill would corrupt the graph.
        if sid in seen_skills:
            raise ContentError(f"duplicate skill id: {sid}")
        seen_skills.add(sid)
        # May be empty: a new skill has no catalogued errors yet, and a recall
        # skill's wrong answer is not knowing rather than a false belief.
        # Diagnosis reports an unmatched error as novel (Task 8).
        mc_ids = tuple(MisconceptionId(m) for m in entry.get("misconceptions", []))
        for mid in mc_ids:
            if mid not in misconceptions:
                raise ContentError(f"{sid} references unknown misconception {mid}")
        referenced_mcs.update(mc_ids)

        concept_ids = tuple(ConceptId(c) for c in entry.get("concepts", []))
        for cid in concept_ids:
            if cid not in concepts:
                raise ContentError(f"{sid} references unknown concept {cid}")
            concept_users[cid].add(sid)

        notes = entry.get("teaching_notes")
        if not (isinstance(notes, str) and notes.strip()):
            raise ContentError(f"skill {sid} has no teaching_notes")

        skills.append(
            Skill(
                id=sid,
                subject_id=subject,
                name=entry["name"],
                can_do_statement=entry["can_do"],
                verification_kind=VerificationKind(
                    entry.get("verification", default_verification)
                ),
                concept_ids=concept_ids,
                misconception_ids=mc_ids,
                teaching_notes=notes,
            )
        )
        for pre in entry.get("prereqs", []):
            edges.append(
                PrereqEdge(
                    from_skill=SkillId(pre["skill"]),
                    to_skill=sid,
                    strength=PrereqStrength(pre["strength"]),
                )
            )

    # Sharing must not become orphaning: content nothing points at is dead weight
    # that would still be scheduled for review.
    if orphans := set(misconceptions) - referenced_mcs:
        raise ContentError(f"misconceptions referenced by no skill: {sorted(orphans)}")
    if orphans := set(concepts) - concept_users.keys():
        raise ContentError(f"concepts referenced by no skill: {sorted(orphans)}")

    # introduced_by overrides where a Learn session first teaches a concept, so
    # it must name a skill that actually uses it. This also catches a typo'd id,
    # which would otherwise sit unnoticed until Slice 3 reads the field.
    for concept in concepts.values():
        users = concept_users[concept.id]
        if concept.introduced_by is not None and concept.introduced_by not in users:
            raise ContentError(
                f"{concept.id} is introduced_by {concept.introduced_by}, which does not "
                f"use it; choose one of {sorted(users)}"
            )

    try:
        graph = SkillGraph.build(skills, edges)
    except (KeyError, CycleError) as exc:
        raise ContentError(str(exc)) from exc

    return LoadedCluster(graph=graph, concepts=concepts, misconceptions=misconceptions)


def load_cluster(path: Path) -> LoadedCluster:
    """Read a YAML cluster file. A thin wrapper; the rules are in `parse_cluster`.

    Other sources skip this entirely: an HTTP or S3 reader decodes bytes and
    calls `parse_cluster`, and a database reader builds the domain objects from
    rows without going near YAML.
    """
    return parse_cluster(yaml.safe_load(path.read_text()))
