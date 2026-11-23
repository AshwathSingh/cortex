"""T-23.2: the ``ArtifactIngested`` trigger.

``emit_artifact_ingested`` is called after an ingestion has committed. It only
queues work on a small background pool and returns, so ingestion never waits for
(or fails because of) the agent. One run per workspace at a time; a request that
arrives mid-run is coalesced into one follow-up run.

shortcut: in-process pool and locks, so a multi-worker deployment can run two
sweeps of one workspace at once (edges still dedupe by key); swap for a real
queue when the app scales out.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from app.config import settings
from app.db.neo4j_driver import get_driver

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="connection-agent")
_guard = threading.Lock()
_running: set[str] = set()
_rerun: set[str] = set()
_agent_factory = None  # set by ``configure``; None means the agent is disabled


def configure(factory) -> None:
    """``factory(driver) -> ConnectionAgent`` (None disables the agent)."""
    global _agent_factory
    _agent_factory = factory


def default_factory(driver):
    from app.services.source_removal import SourceRemovalFence
    from app.agent.service import ConnectionAgent
    from app.agent.store import Neo4jStore
    from app.jev import JevClient

    jev = JevClient(
        settings.jev_api_key.get_secret_value(),
        base_url=settings.jev_base_url,
        model=settings.jev_model,
        timeout_ms=settings.jev_timeout_ms,
        max_retries=settings.jev_max_retries,
    )
    return ConnectionAgent(
        Neo4jStore(driver),
        jev,
        driver,
        threshold=settings.connection_agent_confidence_threshold,
        review_floor=settings.connection_agent_review_floor,
        max_candidates=settings.connection_agent_max_candidates,
        write_guard_factory=lambda ws: SourceRemovalFence(ws).write,
    )


def emit_artifact_ingested(workspace_id) -> None:
    """Queue analysis for a workspace. Never raises."""
    if _agent_factory is None:
        return
    ws = str(workspace_id)
    try:
        _pool.submit(_run, ws)
    except Exception:
        logger.exception("could not queue connection analysis workspace=%s", ws)


def _run(ws: str) -> None:
    with _guard:
        if ws in _running:
            _rerun.add(ws)
            return
        _running.add(ws)
    try:
        while True:
            agent = _agent_factory(get_driver())
            try:
                summary = agent.run(ws)
                logger.info("connection analysis done workspace=%s %s", ws, summary)
            finally:
                close = getattr(agent.jev, "close", None)
                if close:
                    close()
            with _guard:
                if ws not in _rerun:
                    _running.discard(ws)
                    return
                _rerun.discard(ws)
    except Exception as error:
        from app.services.source_removal import SourceChanged

        if isinstance(error, SourceChanged):
            logger.info(
                "connection analysis cancelled after source change workspace=%s", ws
            )
        else:
            logger.exception("connection analysis crashed workspace=%s", ws)
        with _guard:
            _running.discard(ws)
            rerun = ws in _rerun
            _rerun.discard(ws)
        if rerun:
            emit_artifact_ingested(ws)
