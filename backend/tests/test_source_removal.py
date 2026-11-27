import uuid
from datetime import datetime, timezone

import pytest
from neo4j.exceptions import ServiceUnavailable
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.graph import get_neo4j
from app.github.mapper import write_graph
from app.main import app
from app.models import (
    DataSource,
    GraphComment,
    GraphCommentView,
    SourceRemoval,
    Role,
    SyncStatus,
)
from app.services.source_removal import (
    SourceChanged,
    remove_source,
    guard_target,
    indexed_channels,
)
from app.sources.pipeline import run_ingestion
from app.sources.chat_graph import (
    ChatAuthor,
    ChatChannel,
    ChatMessage,
    write_chat_graph,
)
from app.uploads.graph import prepare, write_document
from app.uploads.sections import split_into_sections
from tests.authz import sign_in_with_role, make_workspace
from tests.payloads import (
    TEST_WORKSPACE_ID as A,
    TEST_WORKSPACE_ID_B as B,
    pull_request,
    issue,
    user,
)
from tests.test_roles_integrity import pg, scratch_url  # noqa: F401
from tests.test_source_pipeline import FakeAdapter

WS = uuid.UUID(A)
URL = f"/api/workspaces/{A}/sources"


@pytest.mark.parametrize("role, expected", [(None, 401), (Role.VIEWER, 403)])
def test_unauthorized_removal_never_contacts_graph(api_db, role, expected):
    client, sessions = api_db
    if role:
        sign_in_with_role(client, sessions, A, role)

    class NoGraph:
        def session(self):
            raise AssertionError("Unauthorized graph access")

    app.dependency_overrides[get_neo4j] = lambda: NoGraph()
    try:
        assert (
            client.request(
                "DELETE", URL, json={"kind": "github", "external_ref": "o/r"}
            ).status_code
            == expected
        )
    finally:
        app.dependency_overrides.pop(get_neo4j, None)


@pytest.fixture
def world(pg, graph):
    with Session(pg) as session:
        make_workspace(session, "Removal test", A)
        make_workspace(session, "Other workspace", B)
        session.commit()
    return sessionmaker(bind=pg, expire_on_commit=False), graph


def seed_source(session, kind, ref):
    session.add(
        DataSource(
            workspace_id=WS,
            kind=kind,
            external_ref=ref,
            status=SyncStatus.SUCCESS,
            last_attempted_at=datetime.now(timezone.utc),
        )
    )
    session.commit()


def test_repository_cleanup_preserves_shared_authors_and_other_workspace(world):
    sessions, graph = world
    alice = user(1, "alice")
    write_graph(graph.driver, "o/one", [pull_request(11, alice)], [], workspace_id=A)
    write_graph(graph.driver, "o/two", [], [issue(22, alice)], workspace_id=A)
    write_graph(graph.driver, "o/one", [pull_request(11, alice)], [], workspace_id=B)
    edge = "Author:9000000000001|AUTHORED|PullRequest:9000000001011"
    with sessions() as session:
        seed_source(session, "github", "o/one")
        for key in (
            "PullRequest:9000000001011",
            edge,
            "Issue:9000000002022",
            "Author:9000000000001",
        ):
            session.add(
                GraphComment(
                    workspace_id=WS,
                    target_kind="edge" if "|" in key else "node",
                    target_key=key,
                    body="Review",
                )
            )
        session.commit()
        remove_source(session, graph.driver, WS, "github", "o/one")
        assert session.scalar(select(DataSource)) is None
        assert {c.target_key for c in session.scalars(select(GraphComment))} == {
            "Issue:9000000002022",
            "Author:9000000000001",
        }
        with pytest.raises(SourceChanged):
            guard_target(session, WS, "PullRequest:9000000001011", graph.driver)
        remove_source(session, graph.driver, WS, "github", "o/one")
    assert graph.node("PullRequest", 9000000001011) is None
    assert graph.node("Issue", 9000000002022) is not None
    assert graph.node("Author", 9000000000001) is not None
    assert graph.node("PullRequest", 9000000001011, B) is not None


@pytest.mark.parametrize("kind", ["slack", "discord"])
def test_single_channel_removal_keeps_sibling_channel_and_shared_author(world, kind):
    sessions, graph = world
    prefix = kind + "/"
    write_chat_graph(
        graph.driver,
        workspace_id=A,
        kind=kind,
        source_ref="team",
        channels=[
            ChatChannel(prefix + "one", "one"),
            ChatChannel(prefix + "two", "two"),
        ],
        authors=[ChatAuthor(prefix + "alice", "alice")],
        messages=[
            ChatMessage(
                prefix + "m1",
                prefix + "one",
                "First",
                "https://example.com/1",
                "2026-11-17",
                prefix + "alice",
            ),
            ChatMessage(
                prefix + "m2",
                prefix + "two",
                "Second",
                "https://example.com/2",
                "2026-11-17",
                prefix + "alice",
            ),
        ],
    )
    with sessions() as session:
        seed_source(session, kind, "team")
        remove_source(session, graph.driver, WS, kind, "team", prefix + "one")
        assert [
            c["name"] for c in indexed_channels(session, graph.driver, WS, kind, "team")
        ] == ["two"]
        assert graph.node("Author", prefix + "alice") is not None
        assert session.scalar(select(DataSource)) is not None
        remove_source(session, graph.driver, WS, kind, "team")
        assert graph.node("Author", prefix + "alice") is None


def test_upload_removal_matches_casefolded_document_identity(world):
    sessions, graph = world
    doc = prepare("PRD.txt", b"Hello", "text", split_into_sections("Hello"))
    write_document(graph.driver, doc, workspace_id=A)
    with sessions() as session:
        seed_source(session, "upload", "PRD.txt")
        seed_source(session, "upload", "prd.txt")
        remove_source(session, graph.driver, WS, "upload", "prd.txt")
        assert graph.node("Document", doc.node_id) is None
        assert list(session.scalars(select(DataSource))) == []


def test_retry_after_graph_commit_sql_failure_removes_original_comments(
    world, monkeypatch
):
    from app.graph import mutations

    events = []
    monkeypatch.setattr(mutations, "_listeners", [events.append])
    sessions, graph = world
    write_graph(
        graph.driver, "o/one", [pull_request(11, user(1, "alice"))], [], workspace_id=A
    )
    with sessions() as session:
        seed_source(session, "github", "o/one")
        session.add(
            GraphComment(
                workspace_id=WS,
                target_kind="node",
                target_key="PullRequest:9000000001011",
                body="Remove me",
            )
        )
        session.commit()
        original = session.commit
        commits = 0

        def fail_second_commit():
            nonlocal commits
            commits += 1
            if commits == 2:
                raise RuntimeError("Simulated SQL outage after graph commit")
            original()

        monkeypatch.setattr(session, "commit", fail_second_commit)
        with pytest.raises(RuntimeError):
            remove_source(session, graph.driver, WS, "github", "o/one")
        session.rollback()
        assert graph.node("PullRequest", 9000000001011) is None
        assert session.scalar(select(SourceRemoval)).pending
        assert [event.action for event in events] == ["source.graph_removed"]
        monkeypatch.setattr(session, "commit", original)
        remove_source(session, graph.driver, WS, "github", "o/one")
        assert session.scalar(select(GraphComment)) is None
        assert not session.scalar(select(SourceRemoval)).pending
        assert [event.action for event in events] == [
            "source.graph_removed",
            "source.removed",
        ]


@pytest.mark.parametrize("fetch_fails", [False, True])
def test_removal_during_fetch_cannot_recreate_source_or_failure_record(
    world, fetch_fails
):
    from app.sources.base import SourceNotFound

    sessions, graph = world

    def during_fetch():
        with sessions() as removal:
            remove_source(removal, graph.driver, WS, "fake", "acme/widgets")

    adapter = FakeAdapter(
        observe=during_fetch,
        fetch_error=SourceNotFound("gone") if fetch_fails else None,
    )
    with sessions() as session:
        with pytest.raises(SourceChanged):
            run_ingestion(
                adapter,
                graph.driver,
                session,
                workspace_id=WS,
                external_ref="acme/widgets",
            )
        session.rollback()
        assert not adapter.wrote
        assert session.scalar(select(DataSource)) is None


@pytest.mark.parametrize("role", [Role.OWNER, Role.EDITOR])
def test_authorized_api_removes_source_and_retries_safely(api_db, graph, role):
    client, sessions = api_db
    sign_in_with_role(client, sessions, A, role)
    write_graph(graph.driver, "o/remove", [], [], workspace_id=A)
    with sessions() as session:
        seed_source(session, "github", "o/remove")
    app.dependency_overrides[get_neo4j] = lambda: graph.driver
    try:
        payload = {"kind": "github", "external_ref": "o/remove"}
        assert client.request("DELETE", URL, json=payload).status_code == 204
        assert client.request("DELETE", URL, json=payload).status_code == 204
        assert client.get(URL).json() == []
    finally:
        app.dependency_overrides.pop(get_neo4j, None)


def test_postgres_removal_waits_for_graph_writer(world):
    import threading
    from app.services.workspaces import lock_active_workspace

    sessions, graph = world
    started, finished = threading.Event(), threading.Event()
    failures = []

    def remove():
        try:
            with sessions() as session:
                started.set()
                remove_source(session, graph.driver, WS, "github", "o/r")
        except Exception as error:
            failures.append(error)
        finally:
            finished.set()

    with sessions() as writer:
        assert lock_active_workspace(writer, WS)
        worker = threading.Thread(target=remove)
        worker.start()
        assert started.wait(2)
        assert not finished.wait(0.15)
        write_graph(
            graph.driver, "o/r", [pull_request(11, user(1))], [], workspace_id=A
        )
        writer.commit()
    worker.join(5)
    assert finished.is_set() and not failures
    assert graph.node("PullRequest", 9000000001011) is None


def test_upload_deleted_while_parsing_cannot_write_or_record_failure(
    api_db, graph, monkeypatch
):
    import app.api.uploads as uploads

    client, sessions = api_db
    sign_in_with_role(client, sessions, A, Role.OWNER)
    extract = uploads.extract_document

    def removing_extract(filename, data):
        with sessions() as session:
            remove_source(session, graph.driver, WS, "upload", filename)
        return extract(filename, data)

    monkeypatch.setattr(uploads, "extract_document", removing_extract)
    app.dependency_overrides[uploads.get_neo4j] = lambda: graph.driver
    try:
        response = client.post(
            f"/api/workspaces/{A}/uploads",
            files={"file": ("race.txt", b"Test data", "text/plain")},
        )
        assert response.status_code == 409
        with sessions() as session:
            assert session.scalar(select(DataSource)) is None
    finally:
        app.dependency_overrides.pop(uploads.get_neo4j, None)


@pytest.mark.parametrize("status", ["active", "pending_review", "rejected"])
def test_removal_cleans_agent_edges_evidence_and_attached_comments(world, status):
    from app.graph.mutations import create_agent_edge
    from app.agent.store import Neo4jStore

    sessions, graph = world
    write_graph(
        graph.driver, "o/remove", [pull_request(11, user(1))], [], workspace_id=A
    )
    write_graph(graph.driver, "o/keep", [], [issue(22, user(1))], workspace_id=A)
    source, target = "PullRequest:9000000001011", "Issue:9000000002022"
    edge = f"{source}|AGENT_RELATIONSHIP|{target}"
    create_agent_edge(
        graph.driver,
        A,
        source_key=source,
        target_key=target,
        relationship_type="IMPLEMENTS",
        dedup=f"remove-{status}",
        status=status,
        confidence=0.9,
        evidence="Owned source evidence",
        model_version="test",
        explicit_refs=[],
    )
    with sessions() as session:
        seed_source(session, "github", "o/remove")
        session.add(
            GraphComment(
                workspace_id=WS, target_kind="edge", target_key=edge, body="Review"
            )
        )
        session.commit()
        remove_source(session, graph.driver, WS, "github", "o/remove")
        assert session.scalar(select(GraphComment)) is None
    assert Neo4jStore(graph.driver).list_suggestions(A) == []
    with graph.driver.session() as session:
        assert (
            session.run(
                "MATCH ()-[r:AGENT_RELATIONSHIP {workspace_id: $ws}]->() RETURN count(r) AS total",
                ws=A,
            ).single()["total"]
            == 0
        )
    assert graph.node("Issue", 9000000002022) is not None


@pytest.mark.parametrize("readd", [False, True])
def test_delayed_agent_result_is_fenced_after_source_removal(world, readd):
    from app.agent.service import ConnectionAgent
    from app.agent.store import Neo4jStore
    from app.jev.testing import FakeJev
    from app.services.source_removal import SourceRemovalFence

    sessions, graph = world
    pr = pull_request(
        11, user(1), title="Fix login failure", body="Fix login failure #22"
    )
    write_graph(graph.driver, "o/remove", [pr], [], workspace_id=A)
    write_graph(
        graph.driver,
        "o/keep",
        [],
        [issue(22, user(1), title="Login failure", body="Login failure needs fixing")],
        workspace_id=A,
    )

    def answer(state, questions):
        with sessions() as session:
            remove_source(session, graph.driver, WS, "github", "o/remove")
        if readd:
            write_graph(graph.driver, "o/remove", [pr], [], workspace_id=A)
        return {"IMPLEMENTS:ab": 0.9}

    agent = ConnectionAgent(
        Neo4jStore(graph.driver),
        FakeJev(answer),
        graph.driver,
        threshold=0.7,
        review_floor=0.4,
        max_candidates=10,
        write_guard_factory=lambda ws: SourceRemovalFence(ws, sessions),
    )
    with pytest.raises(SourceChanged):
        agent.run(A)
    with graph.driver.session() as session:
        assert (
            session.run(
                "MATCH ()-[r:AGENT_RELATIONSHIP {workspace_id: $ws}]->() RETURN count(r) AS total",
                ws=A,
            ).single()["total"]
            == 0
        )
    if readd:
        assert graph.node("PullRequest", pr["id"]).get("analysis_hash") is None


def test_source_removal_audit_hooks_report_graph_and_sql_phases_once(
    world, monkeypatch
):
    from app.graph import mutations
    from app.models import SourceRemovalTarget, Workspace
    from tests.authz import make_user

    sessions, graph = world
    events = []
    monkeypatch.setattr(mutations, "_listeners", [events.append])
    write_graph(
        graph.driver, "o/audit", [pull_request(11, user(1))], [], workspace_id=A
    )
    with sessions() as session:
        seed_source(session, "github", "o/audit")
        author = make_user(session, "audit-source@example.com")
        session.flush()
        key = "PullRequest:9000000001011"
        session.add(
            GraphComment(
                workspace_id=WS,
                target_kind="node",
                target_key=key,
                body="private comment",
            )
        )
        session.add(
            GraphCommentView(
                workspace_id=WS,
                user_id=author.id,
                target_kind="node",
                target_key=key,
                last_seen_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        actor = f"user:{author.id}"
        remove_source(session, graph.driver, WS, "github", "o/audit", actor=actor)
        assert [event.action for event in events] == [
            "source.graph_removed",
            "source.removed",
        ]
        assert all(event.actor == actor for event in events)
        assert events[0].detail["operation_id"] == events[1].detail["operation_id"]
        assert key in events[0].detail["node_keys"]
        assert events[1].detail["comments_removed"] == 1
        assert events[1].detail["read_markers_removed"] == 1
        assert events[1].detail["sources_removed"] == 1
        assert "private comment" not in repr(events)
        assert session.scalar(select(SourceRemoval)).targets == {}
        assert (
            session.scalar(
                select(SourceRemovalTarget).where(SourceRemovalTarget.target_key == key)
            )
            is not None
        )
        workspace = session.get(Workspace, WS)
        assert workspace.source_removals_pending == 0
        remove_source(session, graph.driver, WS, "github", "o/audit", actor=actor)
        assert len(events) == 2, "An empty retry must not duplicate audit events"


@pytest.mark.parametrize(
    "key",
    [
        "Issue:1|RELATES_TO|Issue:2|extra",
        "Issue:1||Issue:2",
        "missing",
        "Unknown:1",
        "Issue:1|RELATES_TO|",
    ],
)
def test_target_guard_rejects_malformed_keys_before_reading_any_store(key):
    with pytest.raises(ValueError):
        guard_target(object(), WS, key, object())


def test_source_fence_reuses_one_session_and_reads_no_removal_history(world):
    from sqlalchemy import event
    from app.services.source_removal import SourceRemovalFence

    sessions, graph = world
    statements, opened = [], []
    engine = sessions.kw["bind"]

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    def factory():
        opened.append(True)
        return sessions()

    event.listen(engine, "before_cursor_execute", capture)
    try:
        fence = SourceRemovalFence(A, factory)
        try:
            for _ in range(5):
                with fence():
                    pass
        finally:
            fence.close()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(opened) == 1
    assert len(statements) == 6  # one snapshot plus one constant-size check per write
    assert all("from workspaces" in statement for statement in statements)
    assert not any("from source_removals" in statement for statement in statements)


def test_surviving_multilabel_author_keeps_its_comment(world):
    sessions, graph = world
    write_graph(
        graph.driver, "o/remove", [pull_request(11, user(1))], [], workspace_id=A
    )
    write_graph(graph.driver, "o/keep", [], [issue(22, user(1))], workspace_id=A)
    with graph.driver.session() as neo:
        # Deliberately give an unrelated label first, then add the canvas label.
        neo.run(
            "MATCH (a:Author {workspace_id: $ws}) SET a:Imported REMOVE a:Author SET a:Author",
            ws=A,
        ).consume()
    with sessions() as session:
        session.add(
            GraphComment(
                workspace_id=WS,
                target_kind="node",
                target_key="Author:9000000000001",
                body="Keep this",
            )
        )
        session.commit()
        remove_source(session, graph.driver, WS, "github", "o/remove")
        assert session.scalar(select(GraphComment)).body == "Keep this"


def test_restored_target_prunes_its_indexed_tombstone(world):
    from app.models import SourceRemovalTarget

    sessions, graph = world
    pr = pull_request(11, user(1))
    write_graph(graph.driver, "o/r", [pr], [], workspace_id=A)
    with sessions() as session:
        remove_source(session, graph.driver, WS, "github", "o/r")
        key = f"PullRequest:{pr['id']}"
        assert (
            session.scalar(
                select(SourceRemovalTarget).where(SourceRemovalTarget.target_key == key)
            )
            is not None
        )
        write_graph(graph.driver, "o/r", [pr], [], workspace_id=A)
        guard_target(session, WS, key, graph.driver)
        session.commit()
        assert (
            session.scalar(
                select(SourceRemovalTarget).where(SourceRemovalTarget.target_key == key)
            )
            is None
        )


def test_target_guard_queries_the_index_instead_of_deserializing_history(world):
    from sqlalchemy import event
    from app.models import SourceRemovalTarget

    sessions, graph = world
    with sessions() as session:
        for index in range(50):
            removal = SourceRemoval(
                workspace_id=WS,
                kind="github",
                external_ref=f"old/{index}",
                revision=str(uuid.uuid4()),
                pending=False,
                targets={},
            )
            session.add(removal)
            session.flush()
            session.add(
                SourceRemovalTarget(
                    workspace_id=WS,
                    source_removal_id=removal.id,
                    target_key=f"Issue:{index + 10000}",
                )
            )
        session.commit()
        statements = []
        engine = sessions.kw["bind"]

        def capture(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement.lower())

        event.listen(engine, "before_cursor_execute", capture)
        try:
            guard_target(session, WS, "Issue:42", object())
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert not any(
            "source_removals.targets" in statement for statement in statements
        )
        lookup = next(
            statement for statement in statements if "join source_removals" in statement
        )
        assert "source_removal_targets.target_key =" in lookup
        assert "source_removal_targets.workspace_id =" in lookup


@pytest.mark.parametrize("kind", ["slack", "discord"])
def test_pending_channel_cleanup_does_not_fail_parent_or_sibling(api_db, graph, kind):
    client, sessions = api_db
    sign_in_with_role(client, sessions, A, Role.OWNER)
    prefix = kind + "/"
    write_chat_graph(
        graph.driver,
        workspace_id=A,
        kind=kind,
        source_ref="team",
        channels=[
            ChatChannel(prefix + "one", "one"),
            ChatChannel(prefix + "two", "two"),
        ],
        authors=[],
        messages=[],
    )
    with sessions() as session:
        seed_source(session, kind, "team")
        session.add(
            SourceRemoval(
                workspace_id=WS,
                kind=kind,
                external_ref="team",
                revision=str(uuid.uuid4()),
                pending=True,
                channel_id=prefix + "one",
                targets={},
            )
        )
        session.commit()
    app.dependency_overrides[get_neo4j] = lambda: graph.driver
    try:
        response = client.get(URL)
        assert response.status_code == 200
        source = next(s for s in response.json() if s["kind"] == kind)
        assert source["status"] == "SUCCESS"
        assert source["last_error"] is None
        response = client.get(
            URL + "/channels", params={"kind": kind, "external_ref": "team"}
        )
        assert response.status_code == 200
        rows = {row["id"]: row for row in response.json()}
        assert rows[prefix + "one"]["removal_pending"] is True
        assert not rows[prefix + "two"].get("removal_pending", False)
        # The retry remains available even after the graph phase committed.
        with graph.driver.session() as gs:
            gs.run(
                "MATCH (n:Channel {workspace_id: $ws, id: $id}) DETACH DELETE n",
                ws=A,
                id=prefix + "one",
            ).consume()
        response = client.get(
            URL + "/channels", params={"kind": kind, "external_ref": "team"}
        )
        assert any(
            row["id"] == prefix + "one" and row["removal_pending"]
            for row in response.json()
        )
    finally:
        app.dependency_overrides.pop(get_neo4j, None)
