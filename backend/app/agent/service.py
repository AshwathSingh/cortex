"""T-23.2 / T-23.3 / T-23.6: the Connection Agent run.

    artifact ingested -> sweep the workspace for artifacts whose content has not
    been analysed -> for each: pre-filter candidates (cheap, same workspace) ->
    ask Jev once per pair (all relationship types in one request) -> pick the
    best type -> route by confidence -> upsert through the mutation layer.

Failure isolation: a Jev failure marks only that artifact ``failed`` (logged
without content or secrets) and the sweep moves on, so nothing here can fail an
ingestion, and a later sweep or the retry endpoint picks the artifact up again.
Edges are upserted by ``dedup_key``, so re-running is safe.
"""

import hashlib
import logging
from contextlib import nullcontext, ExitStack
from dataclasses import dataclass

from app.agent import relationships as rel
from app.agent.candidates import Artifact, explicit_references, find_candidates
from app.graph import mutations
from app.jev import JevError

logger = logging.getLogger(__name__)

STATE_BODY_KEYS = ("type", "title", "body", "author", "created")


def content_hash(artifact: Artifact) -> str:
    return hashlib.sha256(artifact.text.encode()).hexdigest()


def _state_item(a: Artifact) -> dict:
    # Only what a person would look at to judge the relationship (human test).
    item = {"type": a.label, "title": a.title, "text": a.body or "(no text)"}
    if a.author:
        item["author"] = a.author
    if a.created_at:
        item["created"] = a.created_at
    return item


def _evidence(
    v: rel.Verdict, source: Artifact, target: Artifact, refs: list[str], model: str
) -> str:
    text = (
        f"Jev judged that '{source.title}' {v.relationship_type.replace('_', ' ').lower()} "
        f"'{target.title}' (probability {v.confidence:.0%}, model {model})."
    )
    return text + (" Explicit references: " + "; ".join(refs) + "." if refs else "")


@dataclass
class RunSummary:
    analysed: int = 0
    failed: int = 0
    created: int = 0
    pending: int = 0
    updated: int = 0


class ConnectionAgent:
    def __init__(
        self,
        store,
        jev,
        driver,
        *,
        threshold: float,
        review_floor: float,
        max_candidates: int,
        write_guard_factory=None,
    ):
        self.write_guard_factory = write_guard_factory
        self.store, self.jev, self.driver = store, jev, driver
        self.threshold, self.review_floor, self.max_candidates = (
            threshold,
            review_floor,
            max_candidates,
        )

    def run(self, workspace_id: str) -> RunSummary:
        summary = RunSummary()
        write_guard = (
            self.write_guard_factory(workspace_id)
            if self.write_guard_factory
            else nullcontext
        )
        with ExitStack() as resources:
            close = getattr(write_guard, "close", None)
            if close:
                resources.callback(close)
            pool = self.store.fetch_artifacts(workspace_id)
            todo = [a for a in pool if a.analysis_hash != content_hash(a)]
            seen: set[frozenset[str]] = set()
            for artifact in todo:
                with write_guard():
                    mutations.set_analysis_status(
                        self.driver, workspace_id, artifact.key, "running"
                    )
                try:
                    for other in find_candidates(artifact, pool, self.max_candidates):
                        pair = frozenset((artifact.key, other.key))
                        if pair in seen:
                            continue
                        seen.add(pair)
                        self._analyse_pair(
                            workspace_id,
                            artifact,
                            other,
                            summary,
                            write_guard=write_guard,
                        )
                except JevError as error:
                    summary.failed += 1
                    logger.error(
                        "connection analysis failed workspace=%s artifact=%s error=%s",
                        workspace_id,
                        artifact.key,
                        type(error).__name__,
                    )
                    with write_guard():
                        mutations.set_analysis_status(
                            self.driver,
                            workspace_id,
                            artifact.key,
                            "failed",
                            error=f"{type(error).__name__}: {str(error)[:200]}",
                        )
                    continue
                summary.analysed += 1
                with write_guard():
                    mutations.set_analysis_status(
                        self.driver,
                        workspace_id,
                        artifact.key,
                        "done",
                        content_hash=content_hash(artifact),
                    )
            return summary

    def _analyse_pair(
        self,
        ws: str,
        a: Artifact,
        b: Artifact,
        summary: RunSummary,
        *,
        write_guard=nullcontext,
    ) -> None:
        if self.store.pair_blocked(ws, a.key, b.key):
            return
        result = self.jev.ask_nouls(
            workspace_id=ws,
            item_workspace_ids=(a.workspace_id, b.workspace_id),
            state={"artifact_a": _state_item(a), "artifact_b": _state_item(b)},
            questions=rel.build_questions(),
        )
        verdict = rel.best_verdict(result.nouls)
        if verdict is None:
            return
        routed = rel.route(verdict.confidence, self.threshold, self.review_floor)
        source, target = (a, b) if verdict.a_is_source else (b, a)
        dedup = rel.dedup_key(ws, source.key, target.key, verdict.relationship_type)
        # Looked up by endpoints, not by this dedup key: re-analysis can predict
        # a different type (or direction) than last time, and the old edge's
        # dedup_key -- which embeds its *old* type -- would never match the new
        # one, leaving it to create a duplicate beside the stale edge.
        existing = self.store.existing_edge_for_pair(ws, a.key, b.key)
        action = rel.decide_upsert(existing[1] if existing else None, routed)
        if action == "skip":
            if routed == "discard":
                logger.debug("discarded low-confidence pair workspace=%s", ws)
            return
        refs = explicit_references(a, b)
        evidence = _evidence(verdict, source, target, refs, result.model)
        if action == "create":
            with write_guard():
                created = mutations.create_agent_edge(
                    self.driver,
                    ws,
                    source_key=source.key,
                    target_key=target.key,
                    relationship_type=verdict.relationship_type,
                    dedup=dedup,
                    status=routed,
                    confidence=verdict.confidence,
                    evidence=evidence,
                    model_version=result.model,
                    explicit_refs=refs,
                )
            if created:
                summary.created += routed == "active"
                summary.pending += routed == "pending_review"
            return
        assert existing is not None  # "update" / "promote" only come from a hit above
        with write_guard():
            if existing[2] == verdict.relationship_type:
                mutations.update_agent_edge(
                    self.driver,
                    ws,
                    edge_id=existing[0],
                    confidence=verdict.confidence,
                    evidence=evidence,
                    model_version=result.model,
                    explicit_refs=refs,
                    promote=action == "promote",
                )
            else:
                mutations.retype_agent_edge(
                    self.driver,
                    ws,
                    old_edge_id=existing[0],
                    source_key=source.key,
                    target_key=target.key,
                    relationship_type=verdict.relationship_type,
                    dedup=dedup,
                    status=routed,
                    confidence=verdict.confidence,
                    evidence=evidence,
                    model_version=result.model,
                    explicit_refs=refs,
                )
        summary.updated += 1
