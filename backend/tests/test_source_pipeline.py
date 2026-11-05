"""T-8.1: the provider-independent half of ingestion.

US-7's behaviour through this pipeline is already covered end-to-end by
`test_ingest_api.py`. These tests pin the parts that only exist because three
providers now share it: that the sync record is written in the right order
whatever the adapter does, that a provider's own wording reaches `last_error`,
and that a Neo4j failure is reported separately from a provider failure.
"""

import uuid

import pytest
from neo4j.exceptions import ServiceUnavailable
from pydantic import BaseModel, ValidationError

from app.models import DataSource, Role, SyncStatus
from app.services.data_sources import SyncInProgress, record_sync_attempt
from app.sources.base import (
    FetchedSource,
    SourceAdapter,
    SourceError,
    SourceNotFound,
    SourceUnauthorized,
)
from app.sources.pipeline import GraphUnavailable, run_ingestion
from tests.authz import grant, make_user, make_workspace
from tests.payloads import TEST_WORKSPACE_ID

REF = "acme/widgets"


class _Strict(BaseModel):
    required: int


class FakeAdapter(SourceAdapter):
    """An adapter that fails, or succeeds, exactly where a test wants it to."""

    kind = "fake"

    def __init__(self, *, fetch_error=None, write_error=None, observe=None):
        self._fetch_error = fetch_error
        self._write_error = write_error
        self._observe = observe
        self.closed = False
        self.wrote = False

    def fetch(self) -> FetchedSource:
        if self._observe is not None:
            self._observe()
        if self._fetch_error is not None:
            raise self._fetch_error
        return FetchedSource(
            external_ref=REF,
            display_ref="Acme Widgets",
            counts={"messages": 12, "channels": 2},
            payloads={"messages": [{"id": "1"}]},
        )

    def write(self, driver, fetched, *, workspace_id) -> None:
        if self._write_error is not None:
            raise self._write_error
        self.wrote = True

    def describe(self, error: SourceError) -> str:
        if isinstance(error, SourceNotFound):
            return "the fake source is not reachable from here"
        return str(error)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def workspace(db_sessions):
    """A workspace with an OWNER, so the FKs on `data_sources` are satisfiable."""
    with db_sessions() as session:
        user = make_user(session, "owner@example.com")
        ws = make_workspace(session, "Primary", TEST_WORKSPACE_ID)
        grant(session, ws, user, Role.OWNER)
        session.commit()
        return uuid.UUID(TEST_WORKSPACE_ID), user.id


def run(session, adapter, workspace_id, user_id=None):
    return run_ingestion(
        adapter,
        None,  # the fake adapter never touches the driver
        session,
        workspace_id=workspace_id,
        external_ref=REF,
        user_id=user_id,
    )


def only_row(db_sessions) -> DataSource:
    with db_sessions() as session:
        (row,) = session.query(DataSource).all()
        return row


def test_a_successful_run_records_success_and_reports_the_counts(
    db_sessions, workspace
):
    workspace_id, user_id = workspace
    adapter = FakeAdapter()

    with db_sessions() as session:
        outcome = run(session, adapter, workspace_id, user_id)

    assert adapter.wrote
    assert outcome.counts == {"messages": 12, "channels": 2}
    # The adapter may resolve a friendlier name than the ref it was leased on.
    assert (outcome.external_ref, outcome.display_ref) == (REF, "Acme Widgets")

    row = only_row(db_sessions)
    assert (row.kind, row.external_ref) == ("fake", REF)
    assert row.status is SyncStatus.SUCCESS
    assert row.last_synced_at is not None
    assert row.last_synced_by == user_id
    assert row.last_error is None


def test_the_source_is_pending_while_the_adapter_is_fetching(db_sessions, workspace):
    """The attempt is committed before the fetch, so a run that takes minutes --
    or dies half way -- is visible as "Syncing…" rather than as nothing."""
    workspace_id, _ = workspace
    seen: list[SyncStatus] = []

    def observe():
        with db_sessions() as other:
            seen.extend(s.status for s in other.query(DataSource).all())

    with db_sessions() as session:
        run(session, FakeAdapter(observe=observe), workspace_id)

    assert seen == [SyncStatus.PENDING]
    assert only_row(db_sessions).status is SyncStatus.SUCCESS


def test_a_provider_failure_is_recorded_in_the_adapters_own_words(
    db_sessions, workspace
):
    workspace_id, _ = workspace
    adapter = FakeAdapter(fetch_error=SourceNotFound("404 for /fake/acme"))

    with db_sessions() as session:
        with pytest.raises(SourceNotFound):
            run(session, adapter, workspace_id)

    row = only_row(db_sessions)
    assert row.status is SyncStatus.FAILED
    # describe(), not str(error): the Sources page shows the same sentence the
    # request got back, not a second differently worded version of it.
    assert row.last_error == "the fake source is not reachable from here"
    # Never synced, so there is no freshness to claim.
    assert row.last_synced_at is None


def test_an_unauthorised_provider_is_recorded_and_re_raised(db_sessions, workspace):
    workspace_id, _ = workspace
    adapter = FakeAdapter(fetch_error=SourceUnauthorized("token revoked"))

    with db_sessions() as session:
        with pytest.raises(SourceUnauthorized):
            run(session, adapter, workspace_id)

    assert only_row(db_sessions).last_error == "token revoked"


def test_a_graph_outage_is_reported_separately_from_a_provider_failure(
    db_sessions, workspace
):
    """The provider was fine, so retrying the same ingestion later is the right
    move -- which is a different answer from "the provider misbehaved"."""
    workspace_id, _ = workspace
    adapter = FakeAdapter(write_error=ServiceUnavailable("no route to host"))

    with db_sessions() as session:
        with pytest.raises(GraphUnavailable):
            run(session, adapter, workspace_id)

    row = only_row(db_sessions)
    assert row.status is SyncStatus.FAILED
    assert row.last_error == "Graph database unavailable"


def test_an_unexpected_payload_shape_is_a_provider_error(db_sessions, workspace):
    workspace_id, _ = workspace
    try:
        _Strict.model_validate({})
    except ValidationError as invalid:
        adapter = FakeAdapter(write_error=invalid)

    with db_sessions() as session:
        with pytest.raises(SourceError) as raised:
            run(session, adapter, workspace_id)

    assert "unexpected payload shape" in str(raised.value)
    assert only_row(db_sessions).status is SyncStatus.FAILED


def test_a_held_lease_stops_a_second_run_without_recording_a_failure(
    db_sessions, workspace
):
    """The second caller's request never started, so it is not its failure to
    record -- overwriting the row would also erase the live run's PENDING."""
    workspace_id, _ = workspace
    with db_sessions() as session:
        record_sync_attempt(
            session, workspace_id=workspace_id, external_ref=REF, kind="fake"
        )
        session.commit()

    adapter = FakeAdapter()
    with db_sessions() as session:
        with pytest.raises(SyncInProgress):
            run(session, adapter, workspace_id)

    assert not adapter.wrote
    assert only_row(db_sessions).status is SyncStatus.PENDING


def test_the_pipeline_does_not_close_the_adapter(db_sessions, workspace):
    """Closing is the caller's job: the GitHub client is injected by a FastAPI
    dependency that owns its lifetime, so the pipeline must not shut it down."""
    workspace_id, _ = workspace
    adapter = FakeAdapter()

    with db_sessions() as session:
        run(session, adapter, workspace_id)

    assert not adapter.closed
