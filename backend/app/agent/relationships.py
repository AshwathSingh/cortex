"""T-23.1 / T-23.3: the relationship schema, the questions, and the routing rules.

All question wording lives here (one place to audit and edit) and all decisions
are plain functions, so the routing table is testable without Jev or Neo4j.

Jev answers Noul questions; the *decision* -- which type wins, where the edge
goes -- is made here in code, per the TypeSafe guidance.
"""

from dataclasses import dataclass
from typing import Literal

#: The Neo4j relationship type for agent edges. Manual ones are
#: ``MANUAL_RELATIONSHIP``; both carry the human-facing ``relationship_type``.
AGENT_EDGE_TYPE = "AGENT_RELATIONSHIP"
SOURCE_AGENT = "connection_agent"

Route = Literal["active", "pending_review", "discard"]


@dataclass(frozen=True)
class RelationshipSpec:
    directional: bool
    #: ``{a}`` is the edge's source, ``{b}`` its target. Phrased as one concrete,
    #: observable judgment, naming the state paths (see the TypeSafe skill).
    question: str


# Reuses the vocabulary the manual feature started (RELATED_TO). Order breaks
# ties: a more specific type listed first wins over a vaguer one at equal odds.
RELATIONSHIP_TYPES: dict[str, RelationshipSpec] = {
    "IMPLEMENTS": RelationshipSpec(True, "Does `{a}` implement, build, or fix what `{b}` describes or requests?"),
    "DEPENDS_ON": RelationshipSpec(True, "Does the work in `{a}` depend on, or is it blocked by, the work in `{b}`?"),
    "DECIDED_IN": RelationshipSpec(True, "Was the decision or requirement behind `{a}` made or recorded in `{b}`?"),
    "REFERENCES": RelationshipSpec(True, "Does `{a}` explicitly mention or link to the work described in `{b}`?"),
    "RELATED_TO": RelationshipSpec(False, "Do `artifact_a` and `artifact_b` concern the same feature, problem, or topic?"),
}


def build_questions() -> dict[str, str]:
    """Question id -> instructions. Directional types are asked both ways (``:ab``
    means artifact_a is the source), because the pair is only analysed once."""
    questions: dict[str, str] = {}
    for name, spec in RELATIONSHIP_TYPES.items():
        if spec.directional:
            questions[f"{name}:ab"] = spec.question.format(a="artifact_a", b="artifact_b")
            questions[f"{name}:ba"] = spec.question.format(a="artifact_b", b="artifact_a")
        else:
            questions[f"{name}:ab"] = spec.question
    return questions


def route(confidence: float, threshold: float, review_floor: float) -> Route:
    """The team's three-way rule; both boundaries are inclusive."""
    if confidence >= threshold:
        return "active"
    if confidence >= review_floor:
        return "pending_review"
    return "discard"


@dataclass(frozen=True)
class Verdict:
    relationship_type: str
    a_is_source: bool
    confidence: float


#: A more specific type wins over a vaguer one scoring within this of the top.
#: Without it, the catch-all RELATED_TO (nearly always high) would beat the
#: precise answer (seen in the live smoke test: RELATED_TO 0.98 vs IMPLEMENTS 0.95).
SPECIFICITY_MARGIN = 0.05


def best_verdict(nouls: dict[str, float]) -> Verdict | None:
    """The (type, direction) to record for a pair, or None.

    One edge per pair keeps the canvas readable. Candidates within
    ``SPECIFICITY_MARGIN`` of the top probability compete on specificity
    (``RELATIONSHIP_TYPES`` order), then on probability.
    """
    options = [
        Verdict(name, suffix == "ab", nouls[f"{name}:{suffix}"])
        for name in RELATIONSHIP_TYPES
        for suffix in ("ab", "ba")
        if f"{name}:{suffix}" in nouls
    ]
    if not options:
        return None
    top = max(v.confidence for v in options)
    close = [v for v in options if v.confidence >= top - SPECIFICITY_MARGIN]
    return max(close, key=lambda v: (-list(RELATIONSHIP_TYPES).index(v.relationship_type), v.confidence))


def dedup_key(workspace_id: str, a_key: str, b_key: str, relationship_type: str) -> str:
    """``workspace + type + the pair``; the pair is unordered unless the type is
    directional, so one edge cannot appear twice with its ends swapped."""
    if RELATIONSHIP_TYPES[relationship_type].directional:
        pair = (a_key, b_key)
    else:
        pair = tuple(sorted((a_key, b_key)))
    return "|".join((workspace_id, relationship_type, *pair))


Action = Literal["create", "update", "promote", "skip"]


def decide_upsert(existing_status: str | None, routed: Route) -> Action:
    """What to do given the pair's current edge (if any) and where Jev's answer routes.

    A rejected edge is never touched (a user said no); an active edge is never
    downgraded, so only a still-active verdict refreshes it; a pending edge
    that now clears the threshold is promoted.
    """
    if routed == "discard":
        return "skip"
    if existing_status is None:
        return "create"
    if existing_status == "rejected":
        return "skip"
    if existing_status == "active":
        return "update" if routed == "active" else "skip"
    # pending_review
    return "promote" if routed == "active" else "update"
