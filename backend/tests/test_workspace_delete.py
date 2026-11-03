"""US-05 T-5.1 / T-5.2: deleting a workspace across Postgres and Neo4j."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from neo4j.exceptions import ServiceUnavailable
from sqlalchemy import select, text

from app.api.workspaces import get_neo4j
from app.db.base import Base
from app.github.mapper import write_graph
from app.graph.queries import delete_workspace_graph
from app.main import app
from app.models import (
    WORKSPACE_DELETING,
    DataSource,
    InviteStatus,
    Role,
    SyncStatus,
    Workspace,
    WorkspaceInvite,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.security import hash_invite_token
from tests.authz import authenticate, grant, make_user, make_workspace
from tests.payloads import (
    TEST_REPO,
    TEST_WORKSPACE_ID as A,
    TEST_WORKSPACE_ID_B as B,
    issue,
    pull_request,
    user,
)

ALICE = user(1, "alice")


def seed_graph(driver, workspace_id, repo=TEST_REPO):
    write_graph(
        driver, repo, [pull_request(1, ALICE)], [issue(2, ALICE)], workspace_id=workspace_id
    )


@pytest.fixture
def world(api_db, graph):
    """Workspaces A and B, each with members, a custom role, an invite, a data
    source and graph nodes. `owner` owns both; `editor` is an editor on A."""
    client, sessions = api_db
    with sessions() as s:
        owner = make_user(s, "owner@example.com")
        editor = make_user(s, "editor@example.com")
        for ws_id, name in ((A, "Alpha"), (B, "Beta")):
            ws = make_workspace(s, name, ws_id)
            grant(s, ws, owner, Role.OWNER)
            role = WorkspaceRole(workspace_id=ws.id, name="Reviewer", permissions=[])
            s.add(role)
            s.flush()
            s.add(
                WorkspaceInvite(
                    workspace_id=ws.id,
                    email="x@example.com",
                    token_hash=hash_invite_token(f"tok-{name}"),
                    custom_role_id=role.id,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                    status=InviteStatus.PENDING,
                )
            )
            s.add(
                DataSource(
                    workspace_id=ws.id,
                    kind="github",
                    external_ref=f"o/{name}",
                    status=SyncStatus.SUCCESS,
                    last_attempted_at=datetime.now(timezone.utc),
                )
            )
        grant(s, s.get(Workspace, uuid.UUID(A)), editor, Role.EDITOR)
        s.commit()
        users = {"owner": owner, "editor": editor}
    seed_graph(graph.driver, A, "cortex-test/a")
    seed_graph(graph.driver, B, "cortex-test/b")
    app.dependency_overrides[get_neo4j] = lambda: graph.driver
    yield client, sessions, users, graph
    app.dependency_overrides.pop(get_neo4j, None)


def as_(world, who):
    client, sessions, users, _ = world
    client.cookies.clear()
    authenticate(client, sessions, users[who])
    return client


def rows(sessions, workspace_id):
    """How many Postgres rows each workspace-scoped table holds for the workspace."""
    ws = uuid.UUID(workspace_id)
    with sessions() as s:
        return {
            "workspaces": s.scalar(text("SELECT count(*) FROM workspaces WHERE id=:w"), {"w": ws.hex}),
            "memberships": len(s.scalars(select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == ws)).all()),
            "invites": len(s.scalars(select(WorkspaceInvite).where(WorkspaceInvite.workspace_id == ws)).all()),
            "roles": len(s.scalars(select(WorkspaceRole).where(WorkspaceRole.workspace_id == ws)).all()),
            "sources": len(s.scalars(select(DataSource).where(DataSource.workspace_id == ws)).all()),
        }


def graph_total(graph, ws):
    return graph._one("MATCH (n {workspace_id: $ws}) RETURN count(n)", ws=ws)


# --- T-5.1: Postgres cascade --------------------------------------------------


def test_owner_deletes_workspace_everything_in_it_goes_and_the_other_stays(world):
    _, sessions, _, graph = world
    before_b = rows(sessions, B)
    nodes_b = graph_total(graph, B)
    assert nodes_b > 0 and graph_total(graph, A) > 0

    r = as_(world, "owner").delete(f"/api/workspaces/{A}")
    assert r.status_code == 204 and r.content == b""

    assert set(rows(sessions, A).values()) == {0}
    assert graph_total(graph, A) == 0
    assert rows(sessions, B) == before_b  # workspace B untouched...
    assert graph_total(graph, B) == nodes_b  # ...in both stores


def test_non_owner_cannot_delete_and_nothing_is_touched(world):
    _, sessions, _, graph = world
    before, nodes = rows(sessions, A), graph_total(graph, A)
    r = as_(world, "editor").delete(f"/api/workspaces/{A}")
    assert r.status_code == 403 and "workspace.delete" in r.json()["detail"]
    assert rows(sessions, A) == before and graph_total(graph, A) == nodes
    with sessions() as s:
        assert s.get(Workspace, uuid.UUID(A)).status == "active"


def test_unauthenticated_delete_is_401(world):
    client = world[0]
    client.cookies.clear()
    assert client.delete(f"/api/workspaces/{A}").status_code == 401


def test_deleted_workspace_is_gone_for_its_former_members(world):
    as_(world, "owner").delete(f"/api/workspaces/{A}")
    editor = as_(world, "editor")
    assert editor.get(f"/api/workspaces/{A}").status_code == 403
    assert editor.get(f"/api/workspaces/{A}/members").status_code == 403
    assert editor.get(f"/api/workspaces/{A}/graph").status_code == 403
    assert A not in [w["id"] for w in editor.get("/api/workspaces").json()]


# --- failure and resume ------------------------------------------------------


class FlakyDriver:
    """Fails the first `failures` Neo4j sessions, then behaves like the real one."""

    def __init__(self, real, failures):
        self.real, self.failures = real, failures

    def session(self, *a, **kw):
        if self.failures > 0:
            self.failures -= 1
            raise ServiceUnavailable("simulated Neo4j outage")
        return self.real.session(*a, **kw)


def test_neo4j_failure_hides_workspace_and_retry_finishes_the_delete(world):
    _, sessions, _, graph = world
    flaky = FlakyDriver(graph.driver, failures=1)
    app.dependency_overrides[get_neo4j] = lambda: flaky

    r = as_(world, "owner").delete(f"/api/workspaces/{A}")
    assert r.status_code == 500 and "try deleting it again" in r.json()["detail"]
    assert "Neo4j" not in r.text and "simulated" not in r.text  # no internals leaked

    # Not half-alive: marked, nothing deleted yet, and invisible to every user.
    with sessions() as s:
        assert s.get(Workspace, uuid.UUID(A)).status == WORKSPACE_DELETING
    assert rows(sessions, A)["memberships"] == 2
    assert as_(world, "editor").get(f"/api/workspaces/{A}").status_code == 403
    assert A not in [w["id"] for w in as_(world, "owner").get("/api/workspaces").json()]

    # Re-running resumes and completes.
    assert as_(world, "owner").delete(f"/api/workspaces/{A}").status_code == 204
    assert set(rows(sessions, A).values()) == {0}
    assert graph_total(graph, A) == 0


def test_repeating_a_finished_delete_does_not_error(world):
    assert as_(world, "owner").delete(f"/api/workspaces/{A}").status_code == 204
    # The owner's membership is gone with the workspace, so this is the same 403
    # any request for a workspace that no longer exists gets.
    assert as_(world, "owner").delete(f"/api/workspaces/{A}").status_code == 403


def test_deleting_workspace_cannot_be_written_to(world):
    """A sync or invite accept that lands after the mark must not add data."""
    client, sessions, users, graph = world
    app.dependency_overrides[get_neo4j] = lambda: FlakyDriver(graph.driver, failures=99)
    as_(world, "owner").delete(f"/api/workspaces/{A}")  # leaves it 'deleting'

    from app.services.invites import accept_invite
    from app.services.roles import NotFound
    from app.services.workspaces import lock_active_workspace

    with sessions() as s:
        assert lock_active_workspace(s, uuid.UUID(A)) is False
        assert lock_active_workspace(s, uuid.UUID(B)) is True
        newcomer = make_user(s, "late@example.com")
        s.add(
            WorkspaceInvite(
                workspace_id=uuid.UUID(A),
                email="late@example.com",
                token_hash=hash_invite_token("late"),
                role=Role.VIEWER,
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                status=InviteStatus.PENDING,
            )
        )
        s.commit()
        with pytest.raises(NotFound):
            accept_invite(s, token="late", user=newcomer)
        s.rollback()
        # the claim was rolled back with it: the invite is still pending, no member added
        assert s.scalar(
            select(WorkspaceInvite.status).where(WorkspaceInvite.token_hash == hash_invite_token("late"))
        ) is InviteStatus.PENDING


# --- schema guard -------------------------------------------------------------


def test_every_foreign_key_to_workspaces_cascades():
    """If someone adds a table pointing at workspaces without ON DELETE CASCADE,
    deleting a workspace would start failing in production; catch it here."""
    offenders = [
        f"{table.name}.{fk.parent.name}"
        for table in Base.metadata.sorted_tables
        for fk in table.foreign_keys
        if fk.column.table.name == "workspaces" and fk.ondelete != "CASCADE"
    ]
    assert offenders == []


# --- T-5.2: Neo4j cascade -----------------------------------------------------


def test_graph_delete_removes_nodes_and_edges_in_batches_and_only_this_workspace(graph):
    seed_graph(graph.driver, A, "cortex-test/a")
    seed_graph(graph.driver, B, "cortex-test/b")
    edges_b = graph._one(
        "MATCH ({workspace_id: $w})-[r]->({workspace_id: $w}) RETURN count(r)", w=B
    )
    nodes_a = graph_total(graph, A)
    assert nodes_a >= 4 and edges_b > 0

    removed = delete_workspace_graph(graph.driver, A, batch_size=2)  # forces several batches

    assert removed == nodes_a and graph_total(graph, A) == 0
    assert graph._one("MATCH ()-[r]-() WHERE r.workspace_id = $w RETURN count(r)", w=A) == 0
    assert graph_total(graph, B) > 0
    assert graph._one(
        "MATCH ({workspace_id: $w})-[r]->({workspace_id: $w}) RETURN count(r)", w=B
    ) == edges_b


def test_graph_delete_is_idempotent_and_sweeps_unknown_labels(graph):
    seed_graph(graph.driver, A)
    with graph.driver.session() as s:  # a node the known-label pass would miss
        s.run("CREATE (:SomethingNew {workspace_id: $w})", w=A).consume()
    assert delete_workspace_graph(graph.driver, A) >= 5
    assert graph_total(graph, A) == 0
    assert delete_workspace_graph(graph.driver, A) == 0  # re-running is a no-op


# --- an in-flight sync cannot outlive the delete ------------------------------


def test_sync_that_finishes_after_the_workspace_was_marked_writes_nothing(world):
    import httpx

    from app.api.ingest import get_github_client
    from app.github.client import GitHubClient

    client, sessions, users, graph = world
    from app.api.ingest import get_neo4j as ingest_neo4j

    app.dependency_overrides[ingest_neo4j] = lambda: graph.driver
    nodes_before = graph_total(graph, A)

    def handler(request: httpx.Request) -> httpx.Response:
        # The owner starts a delete while GitHub is still being fetched.
        with sessions() as s:
            s.execute(text("UPDATE workspaces SET status='deleting' WHERE id=:w"), {"w": uuid.UUID(A).hex})
            s.commit()
        return httpx.Response(200, json=[] if request.url.path.endswith("/pulls") else [])

    gh = GitHubClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    app.dependency_overrides[get_github_client] = lambda: gh
    try:
        r = as_(world, "owner").post(
            "/api/ingest/github",
            json={"repo_url": "https://github.com/cortex-test/late", "workspace_id": A},
        )
    finally:
        app.dependency_overrides.pop(get_github_client, None)
        app.dependency_overrides.pop(ingest_neo4j, None)

    assert r.status_code == 409 and "being deleted" in r.json()["detail"]
    assert graph_total(graph, A) == nodes_before  # nothing was (re)created


# --- real Postgres: cascade, locking, migration ------------------------------

import threading  # noqa: E402
import time  # noqa: E402

from sqlalchemy.orm import Session  # noqa: E402

from tests.test_roles_integrity import pg, scratch_url  # noqa: E402,F401  (fixtures)


def _pg_workspace(engine):
    with Session(engine) as s:
        ws = Workspace(name="W", id=uuid.UUID(A))
        owner = make_user(s, "pgowner@example.com")
        s.add(ws)
        s.flush()
        grant(s, ws, owner, Role.OWNER)
        role = WorkspaceRole(workspace_id=ws.id, name="R", permissions=[])
        s.add(role)
        s.flush()
        s.add(
            WorkspaceInvite(
                workspace_id=ws.id,
                email="i@example.com",
                token_hash=hash_invite_token("pgtok"),
                custom_role_id=role.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                status=InviteStatus.PENDING,
            )
        )
        s.add(
            DataSource(
                workspace_id=ws.id,
                kind="github",
                external_ref="o/r",
                status=SyncStatus.SUCCESS,
                last_attempted_at=datetime.now(timezone.utc),
            )
        )
        s.commit()


def test_postgres_cascade_removes_every_dependent_row(pg, graph):
    from app.services.workspaces import delete_workspace

    _pg_workspace(pg)
    seed_graph(graph.driver, A)
    with Session(pg) as s:
        delete_workspace(s, graph.driver, uuid.UUID(A))
    with Session(pg) as s:
        for table in (
            "workspaces",
            "workspace_memberships",
            "workspace_roles",
            "workspace_invites",
            "data_sources",
        ):
            assert s.scalar(text(f"SELECT count(*) FROM {table}")) == 0, table
        assert s.scalar(text("SELECT count(*) FROM users")) == 1  # people are not deleted
    assert graph_total(graph, A) == 0


def test_postgres_delete_waits_for_an_in_flight_writer_then_blocks_new_ones(pg):
    """The writer holds the shared workspace lock while it writes; the delete's
    mark must wait for it, and a writer arriving afterwards must be turned away."""
    from app.services.workspaces import lock_active_workspace, mark_deleting

    _pg_workspace(pg)
    ws = uuid.UUID(A)
    events: list[str] = []
    writer_has_lock = threading.Event()

    def writer():
        with Session(pg) as s:
            assert lock_active_workspace(s, ws)
            writer_has_lock.set()
            time.sleep(1.0)  # "writing to the graph"
            events.append("writer-done")
            s.commit()

    def deleter():
        writer_has_lock.wait()
        with Session(pg) as s:
            mark_deleting(s, ws)
            events.append("marked")

    threads = [threading.Thread(target=writer), threading.Thread(target=deleter)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert events == ["writer-done", "marked"], events
    with Session(pg) as s:
        assert lock_active_workspace(s, ws) is False


def test_postgres_migration_13_marks_existing_workspaces_active(scratch_url):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    from sqlalchemy import create_engine

    from app.config import settings

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    engine = create_engine(scratch_url)
    old = settings.database_url
    settings.database_url = scratch_url
    try:
        command.upgrade(cfg, "20261029_12")
        with engine.begin() as c:
            c.execute(text("INSERT INTO workspaces (id, name) VALUES (:i, 'old')"), {"i": uuid.uuid4()})
        command.upgrade(cfg, "head")
        with engine.connect() as c:
            assert c.scalar(text("SELECT status FROM workspaces")) == "active"
        with pytest.raises(Exception):
            with engine.begin() as c:
                c.execute(text("UPDATE workspaces SET status='bogus'"))
        command.downgrade(cfg, "20261029_12")
    finally:
        settings.database_url = old
        engine.dispose()
