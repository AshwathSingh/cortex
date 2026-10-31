"""Database-level guarantees behind custom roles (US-21 review follow-ups).

The SQLite fixtures used elsewhere cannot show these: SQLite ignores FOR UPDATE and
skips foreign keys unless asked. The first test turns foreign keys on so the
cross-workspace rule is checked everywhere; the rest run against a real PostgreSQL
in a throwaway database and are skipped when none is reachable
(``docker compose up -d postgres``).
"""

import threading
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.base import Base
from app.models import Role, User, Workspace, WorkspaceMembership, WorkspaceRole
from app.services.roles import RoleChoice, RoleError, assign_role

BACKEND = Path(__file__).resolve().parents[1]


# --- cross-workspace roles: runs on SQLite with foreign keys enforced -----------


def test_membership_cannot_use_a_role_from_another_workspace_sqlite():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON")
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as s:
            a, b = Workspace(name="A"), Workspace(name="B")
            user = User(email="u@example.com", password_hash=None)
            s.add_all([a, b, user])
            s.flush()
            role_in_b = WorkspaceRole(workspace_id=b.id, name="R", permissions=[])
            s.add(role_in_b)
            s.commit()  # setup must survive the rollback below
            s.add(
                WorkspaceMembership(
                    user_id=user.id, workspace_id=a.id, custom_role_id=role_in_b.id
                )
            )
            with pytest.raises(IntegrityError):
                s.flush()
            s.rollback()

            # The same role in its own workspace is fine.
            s.add(
                WorkspaceMembership(
                    user_id=user.id, workspace_id=b.id, custom_role_id=role_in_b.id
                )
            )
            s.flush()
    finally:
        engine.dispose()


# --- PostgreSQL scratch databases -------------------------------------------


def _admin_engine() -> Engine:
    return create_engine(settings.database_url, isolation_level="AUTOCOMMIT")


@pytest.fixture
def scratch_url(monkeypatch) -> Iterator[str]:
    """A fresh empty database on the dev server; dropped afterwards. Never touches
    the dev database itself."""
    name = f"cortex_test_{uuid.uuid4().hex[:12]}"
    admin = _admin_engine()
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except (OperationalError, OSError) as e:
        admin.dispose()
        pytest.skip(f"PostgreSQL not available (docker compose up -d postgres): {e}")
    url = make_url(settings.database_url).set(database=name)
    rendered = url.render_as_string(hide_password=False)
    monkeypatch.setattr(settings, "database_url", rendered)  # alembic/env.py reads it
    try:
        yield rendered
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _alembic() -> Config:
    # No ini file: loading one would reconfigure logging for the whole test run.
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


@pytest.fixture
def pg(scratch_url) -> Iterator[Engine]:
    command.upgrade(_alembic(), "head")
    engine = create_engine(scratch_url)
    yield engine
    engine.dispose()


def _workspace_with_users(engine: Engine, owners: int) -> tuple[uuid.UUID, list[uuid.UUID]]:
    with Session(engine) as s:
        ws = Workspace(name="W")
        s.add(ws)
        users = [User(email=f"o{i}@example.com", password_hash=None) for i in range(owners)]
        s.add_all(users)
        s.flush()
        for u in users:
            s.add(WorkspaceMembership(user_id=u.id, workspace_id=ws.id, role=Role.OWNER))
        s.commit()
        return ws.id, [u.id for u in users]


def test_postgres_rejects_role_from_another_workspace(pg):
    with Session(pg) as s:
        a, b = Workspace(name="A"), Workspace(name="B")
        user = User(email="u@example.com", password_hash=None)
        s.add_all([a, b, user])
        s.flush()
        role_in_b = WorkspaceRole(workspace_id=b.id, name="R", permissions=[])
        s.add(role_in_b)
        s.flush()
        s.add(
            WorkspaceMembership(
                user_id=user.id, workspace_id=a.id, custom_role_id=role_in_b.id
            )
        )
        with pytest.raises(IntegrityError):
            s.flush()


def test_postgres_role_in_use_cannot_be_deleted_but_workspace_delete_cascades(pg):
    with Session(pg) as s:
        ws = Workspace(name="W")
        user = User(email="u@example.com", password_hash=None)
        s.add_all([ws, user])
        s.flush()
        role = WorkspaceRole(workspace_id=ws.id, name="R", permissions=[])
        s.add(role)
        s.flush()
        s.add(
            WorkspaceMembership(
                user_id=user.id, workspace_id=ws.id, custom_role_id=role.id
            )
        )
        s.commit()
        ws_id, role_id = ws.id, role.id

    with Session(pg) as s:
        with pytest.raises(IntegrityError):
            s.execute(text("DELETE FROM workspace_roles WHERE id = :i"), {"i": role_id})
            s.commit()

    # US-05 depends on this: deleting the workspace removes its roles and members
    # together without tripping the role foreign key mid-cascade.
    with Session(pg) as s:
        s.execute(text("DELETE FROM workspaces WHERE id = :i"), {"i": ws_id})
        s.commit()
        assert s.scalar(text("SELECT count(*) FROM workspace_roles")) == 0
        assert s.scalar(text("SELECT count(*) FROM workspace_memberships")) == 0


# --- last-owner protection under real concurrency ---------------------------


def _demote(engine, ws_id, actor_id, target_id, barrier, results, slot):
    """What the PATCH route does: load the caller's membership, then assign."""
    with Session(engine) as s:
        actor = s.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == ws_id,
                WorkspaceMembership.user_id == actor_id,
            )
        )
        barrier.wait(timeout=10)  # both transactions are open before either assigns
        try:
            assign_role(
                s,
                workspace_id=ws_id,
                actor=actor,
                target_user_id=target_id,
                choice=RoleChoice(builtin=Role.VIEWER),
            )
            s.commit()
            results[slot] = "ok"
        except RoleError as e:
            s.rollback()
            results[slot] = e.status_code


def _race(engine, ws_id, calls) -> list:
    barrier = threading.Barrier(len(calls))
    results: list = [None] * len(calls)
    threads = [
        threading.Thread(
            target=_demote, args=(engine, ws_id, actor, target, barrier, results, i)
        )
        for i, (actor, target) in enumerate(calls)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(not t.is_alive() for t in threads), "deadlock or hang"
    return results


def _owner_count(engine, ws_id) -> int:
    with Session(engine) as s:
        return s.scalar(
            text(
                "SELECT count(*) FROM workspace_memberships "
                "WHERE workspace_id = :w AND role = 'OWNER'"
            ),
            {"w": ws_id},
        )


@pytest.mark.parametrize("attempt", range(5))
def test_two_owners_demoting_themselves_at_once_leaves_one(pg, attempt):
    ws_id, (a, b) = _workspace_with_users(pg, 2)
    results = _race(pg, ws_id, [(a, a), (b, b)])
    assert sorted(map(str, results)) == ["409", "ok"], results
    assert _owner_count(pg, ws_id) == 1


@pytest.mark.parametrize("attempt", range(5))
def test_two_owners_demoting_each_other_at_once_leaves_one(pg, attempt):
    ws_id, (a, b) = _workspace_with_users(pg, 2)
    results = _race(pg, ws_id, [(a, b), (b, a)])
    # Exactly one wins. The loser is refused either because it was the last owner
    # (409) or because the winner already demoted it (403) -- never both succeed.
    assert results.count("ok") == 1, results
    assert [r for r in results if r != "ok"][0] in (403, 409), results
    assert _owner_count(pg, ws_id) == 1


# --- migrations with existing data ------------------------------------------


def _insert_workspace_and_members(engine):
    ids = {k: uuid.uuid4() for k in ("ws", "ws2", "owner", "editor", "viewer", "role")}
    with engine.begin() as c:
        for key in ("owner", "editor", "viewer"):
            c.execute(
                text("INSERT INTO users (id, email) VALUES (:i, :e)"),
                {"i": ids[key], "e": f"{key}@example.com"},
            )
        for key in ("ws", "ws2"):
            c.execute(
                text("INSERT INTO workspaces (id, name) VALUES (:i, :n)"),
                {"i": ids[key], "n": key},
            )
        for key, role in (("owner", "OWNER"), ("editor", "EDITOR"), ("viewer", "VIEWER")):
            c.execute(
                text(
                    "INSERT INTO workspace_memberships (id, user_id, workspace_id, role) "
                    "VALUES (:m, :u, :w, :r)"
                ),
                {"m": uuid.uuid4(), "u": ids[key], "w": ids["ws"], "r": role},
            )
    return ids


def _roles_by_email(engine) -> dict:
    with engine.connect() as c:
        return {
            email: role
            for email, role in c.execute(
                text(
                    "SELECT u.email, m.role::text "
                    "FROM workspace_memberships m JOIN users u ON u.id = m.user_id"
                )
            )
        }


def test_migrations_upgrade_and_downgrade_with_existing_memberships(scratch_url):
    cfg = _alembic()
    command.upgrade(cfg, "20261008_08")
    engine = create_engine(scratch_url)
    try:
        ids = _insert_workspace_and_members(engine)
        before = _roles_by_email(engine)
        assert before["editor@example.com"] == "EDITOR"

        # Existing memberships survive both upgrades untouched.
        command.upgrade(cfg, "head")
        after = _roles_by_email(engine)
        assert after == before

        # Hand a member a custom role, then take the schema back down.
        with engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO workspace_roles (id, workspace_id, name, permissions) "
                    "VALUES (:r, :w, 'Reviewer', '[]')"
                ),
                {"r": ids["role"], "w": ids["ws"]},
            )
            c.execute(
                text(
                    "UPDATE workspace_memberships SET role = NULL, custom_role_id = :r "
                    "WHERE user_id = :u"
                ),
                {"r": ids["role"], "u": ids["viewer"]},
            )

        command.downgrade(cfg, "20261008_08")
        down = _roles_by_email(engine)
        assert down["owner@example.com"] == "OWNER"
        assert down["editor@example.com"] == "EDITOR"
        # No built-in role to fall back to: least privilege.
        assert down["viewer@example.com"] == "VIEWER"
        with engine.connect() as c:
            tables = {
                r[0]
                for r in c.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                )
            }
        assert "workspace_roles" not in tables

        # ...and back up again over the downgraded data.
        command.upgrade(cfg, "head")
        assert _roles_by_email(engine)["viewer@example.com"] == "VIEWER"
    finally:
        engine.dispose()


def test_composite_key_migration_refuses_existing_cross_workspace_rows(scratch_url):
    cfg = _alembic()
    command.upgrade(cfg, "20261018_09")
    engine = create_engine(scratch_url)
    try:
        ids = _insert_workspace_and_members(engine)
        with engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO workspace_roles (id, workspace_id, name, permissions) "
                    "VALUES (:r, :w, 'Foreign', '[]')"
                ),
                {"r": ids["role"], "w": ids["ws2"]},
            )
            # Possible under migration 09's single-column key: a role of ws2 on ws.
            c.execute(
                text(
                    "UPDATE workspace_memberships SET role = NULL, custom_role_id = :r "
                    "WHERE user_id = :u"
                ),
                {"r": ids["role"], "u": ids["viewer"]},
            )
        with pytest.raises(IntegrityError):
            command.upgrade(cfg, "head")
    finally:
        engine.dispose()


# --- invites (US-03 T-1.1) ---------------------------------------------------


def _invite(ws_id, email, status="PENDING", role="EDITOR", custom_role_id=None):
    return {
        "i": uuid.uuid4(),
        "w": ws_id,
        "e": email,
        "h": uuid.uuid4().hex + uuid.uuid4().hex,
        "r": None if custom_role_id else role,
        "c": custom_role_id,
        "s": status,
    }


_INSERT_INVITE = text(
    "INSERT INTO workspace_invites "
    "(id, workspace_id, email, token_hash, role, custom_role_id, expires_at, status) "
    "VALUES (:i, :w, :e, :h, :r, :c, now() + interval '1 day', :s)"
)


def test_postgres_one_pending_invite_per_workspace_and_email(pg):
    with Session(pg) as s:
        ws = Workspace(name="W")
        s.add(ws)
        s.commit()
        ws_id = ws.id
    with pg.begin() as c:  # history rows never conflict
        c.execute(_INSERT_INVITE, _invite(ws_id, "x@example.com", "ACCEPTED"))
        c.execute(_INSERT_INVITE, _invite(ws_id, "x@example.com", "REVOKED"))
        c.execute(_INSERT_INVITE, _invite(ws_id, "x@example.com", "PENDING"))
    with pytest.raises(IntegrityError):
        with pg.begin() as c:
            c.execute(_INSERT_INVITE, _invite(ws_id, "x@example.com", "PENDING"))


def test_postgres_invite_cannot_use_a_role_from_another_workspace(pg):
    with Session(pg) as s:
        a, b = Workspace(name="A"), Workspace(name="B")
        s.add_all([a, b])
        s.flush()
        role_in_b = WorkspaceRole(workspace_id=b.id, name="R", permissions=[])
        s.add(role_in_b)
        s.commit()
        a_id, b_id, role_id = a.id, b.id, role_in_b.id
    with pytest.raises(IntegrityError):
        with pg.begin() as c:
            c.execute(_INSERT_INVITE, _invite(a_id, "x@example.com", custom_role_id=role_id))
    with pg.begin() as c:
        c.execute(_INSERT_INVITE, _invite(b_id, "x@example.com", custom_role_id=role_id))


def test_postgres_workspace_delete_removes_invites_and_role_delete_cascades_them(pg):
    with Session(pg) as s:
        ws = Workspace(name="W")
        s.add(ws)
        s.flush()
        role = WorkspaceRole(workspace_id=ws.id, name="R", permissions=[])
        s.add(role)
        s.commit()
        ws_id, role_id = ws.id, role.id
    with pg.begin() as c:
        c.execute(_INSERT_INVITE, _invite(ws_id, "x@example.com", custom_role_id=role_id))
    with pg.begin() as c:  # deleting the role takes its invites with it, atomically
        c.execute(text("DELETE FROM workspace_roles WHERE id = :i"), {"i": role_id})
    with pg.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM workspace_invites")) == 0
    with pg.begin() as c:
        c.execute(text("DELETE FROM workspaces WHERE id = :i"), {"i": ws_id})
    with pg.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM workspace_roles")) == 0


def test_postgres_concurrent_accepts_of_one_token_let_exactly_one_win(pg):
    from app.services.invites import accept_invite, create_invite

    with Session(pg) as s:
        ws = Workspace(name="W")
        owner = User(github_id=1, github_login="o", email="o@example.com")
        users = [
            User(github_id=10 + i, github_login=f"u{i}", email=f"u{i}@example.com")
            for i in range(4)
        ]
        s.add_all([ws, owner, *users])
        s.flush()
        actor = WorkspaceMembership(
            workspace_id=ws.id, user_id=owner.id, role=Role.OWNER
        )
        s.add(actor)
        s.flush()
        _, token = create_invite(
            s, workspace_id=ws.id, actor=actor, email="x@example.com", choice=None
        )
        s.commit()
        ws_id, user_ids = ws.id, [u.id for u in users]

    barrier = threading.Barrier(len(user_ids))
    outcomes: list = [None] * len(user_ids)

    def run(i, uid):
        with Session(pg) as s:
            user = s.get(User, uid)
            barrier.wait()
            try:
                accept_invite(s, token=token, user=user)
                s.commit()
                outcomes[i] = "ok"
            except RoleError as e:
                s.rollback()
                outcomes[i] = e.status_code

    threads = [
        threading.Thread(target=run, args=(i, u)) for i, u in enumerate(user_ids)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert outcomes.count("ok") == 1 and outcomes.count(409) == 3, outcomes
    with Session(pg) as s:
        count = s.scalar(
            text("SELECT count(*) FROM workspace_memberships WHERE workspace_id=:w"),
            {"w": ws_id},
        )
    assert count == 2  # owner + the single winner


def test_postgres_deleting_a_role_removes_its_invites_instead_of_failing(pg):
    from app.services.roles import delete_role

    with Session(pg) as s:
        ws = Workspace(name="W")
        s.add(ws)
        s.flush()
        role = WorkspaceRole(workspace_id=ws.id, name="R", permissions=[])
        s.add(role)
        s.flush()
        for status, email in (("PENDING", "a@example.com"), ("ACCEPTED", "b@example.com")):
            s.execute(
                _INSERT_INVITE, _invite(ws.id, email, status, custom_role_id=role.id)
            )
        s.commit()
        delete_role(s, role=role)
        s.commit()
        assert s.scalar(text("SELECT count(*) FROM workspace_invites")) == 0
        assert s.scalar(text("SELECT count(*) FROM workspace_roles")) == 0


@pytest.mark.parametrize("attempt", range(5))
def test_postgres_two_owners_removing_each_other_at_once_leaves_one(pg, attempt):
    from app.services.members import remove_member

    with Session(pg) as s:
        ws = Workspace(name="W")
        users = [
            User(github_id=100 + i, github_login=f"o{i}", email=f"o{i}@example.com")
            for i in range(2)
        ]
        s.add_all([ws, *users])
        s.flush()
        s.add_all(
            WorkspaceMembership(workspace_id=ws.id, user_id=u.id, role=Role.OWNER)
            for u in users
        )
        s.commit()
        ws_id, ids = ws.id, [u.id for u in users]

    barrier = threading.Barrier(2)
    outcomes: list = [None, None]

    def run(i, actor_id, target_id):
        with Session(pg) as s:
            actor = s.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == ws_id,
                    WorkspaceMembership.user_id == actor_id,
                )
            )
            barrier.wait()
            try:
                remove_member(
                    s, workspace_id=ws_id, actor=actor, target_user_id=target_id
                )
                s.commit()
                outcomes[i] = "ok"
            except RoleError as e:
                s.rollback()
                outcomes[i] = e.status_code

    threads = [
        threading.Thread(target=run, args=(0, ids[0], ids[1])),
        threading.Thread(target=run, args=(1, ids[1], ids[0])),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(not t.is_alive() for t in threads), "deadlock or hang"

    assert _owner_count(pg, ws_id) == 1, outcomes
    assert "ok" in outcomes


# --- review follow-ups: races around invites ---------------------------------


def _seed_workspace(pg, owners=1, extra_users=0):
    with Session(pg) as s:
        ws = Workspace(name="W")
        users = [
            User(github_id=500 + i, github_login=f"x{i}", email=f"x{i}@example.com")
            for i in range(owners + extra_users)
        ]
        s.add_all([ws, *users])
        s.flush()
        s.add_all(
            WorkspaceMembership(workspace_id=ws.id, user_id=u.id, role=Role.OWNER)
            for u in users[:owners]
        )
        s.commit()
        return ws.id, [u.id for u in users]


def test_postgres_removed_owner_cannot_create_owner_invite_from_stale_snapshot(pg):
    from app.services.invites import create_invite
    from app.services.members import remove_member
    from app.services.roles import NotPermitted

    ws_id, (o1, o2) = _seed_workspace(pg, owners=2)

    def membership(s, uid):
        return s.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == ws_id,
                WorkspaceMembership.user_id == uid,
            )
        )

    with Session(pg) as stale, Session(pg) as other:
        actor = membership(stale, o2)  # what the route's authorisation saw
        remove_member(other, workspace_id=ws_id, actor=membership(other, o1), target_user_id=o2)
        other.commit()
        with pytest.raises(NotPermitted):
            create_invite(
                stale,
                workspace_id=ws_id,
                actor=actor,
                email="x@example.com",
                choice=RoleChoice(builtin=Role.OWNER),
            )
        stale.rollback()
    with Session(pg) as s:
        assert s.scalar(text("SELECT count(*) FROM workspace_invites")) == 0


def test_postgres_demoted_inviter_cannot_use_stale_owner_rank(pg):
    from app.services.invites import create_invite
    from app.services.roles import NotPermitted

    ws_id, (o1, o2) = _seed_workspace(pg, owners=2)
    with Session(pg) as stale, Session(pg) as other:
        actor = stale.scalar(
            select(WorkspaceMembership).where(WorkspaceMembership.user_id == o2)
        )
        other.execute(
            text("UPDATE workspace_memberships SET role='VIEWER' WHERE user_id=:u"),
            {"u": o2},
        )
        other.commit()
        with pytest.raises(NotPermitted):
            create_invite(
                stale, workspace_id=ws_id, actor=actor, email="y@example.com", choice=None
            )


@pytest.mark.parametrize("attempt", range(5))
def test_postgres_two_invites_accepted_at_once_by_one_user_make_one_membership(pg, attempt):
    from app.services.invites import accept_invite, create_invite

    ws_id, (owner_id, guest_id) = _seed_workspace(pg, owners=1, extra_users=1)
    with Session(pg) as s:
        actor = s.scalar(
            select(WorkspaceMembership).where(WorkspaceMembership.user_id == owner_id)
        )
        tokens = [
            create_invite(
                s, workspace_id=ws_id, actor=actor, email=f"{n}@example.com", choice=None
            )[1]
            for n in ("a", "b")
        ]
        s.commit()

    barrier = threading.Barrier(2)
    outcomes: list = [None, None]

    def run(i):
        with Session(pg) as s:
            user = s.get(User, guest_id)
            barrier.wait()
            try:
                accept_invite(s, token=tokens[i], user=user)
                s.commit()
                outcomes[i] = "ok"
            except Exception as e:  # an uncaught IntegrityError is the bug
                s.rollback()
                outcomes[i] = repr(e)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert outcomes == ["ok", "ok"], outcomes
    with Session(pg) as s:
        assert s.scalar(
            text("SELECT count(*) FROM workspace_memberships WHERE user_id=:u"),
            {"u": guest_id},
        ) == 1
        assert s.scalar(
            text("SELECT count(*) FROM workspace_invites WHERE status='ACCEPTED'")
        ) == 2


@pytest.mark.parametrize("attempt", range(5))
def test_postgres_role_delete_racing_invite_creation_never_errors_or_orphans(pg, attempt):
    from app.services.invites import create_invite
    from app.services.roles import delete_role, get_custom_role

    ws_id, (owner_id,) = _seed_workspace(pg)
    with Session(pg) as s:
        role = WorkspaceRole(workspace_id=ws_id, name="R", permissions=[])
        s.add(role)
        s.commit()
        role_id = role.id

    barrier = threading.Barrier(2)
    outcomes: list = [None, None]

    def invite_side():
        with Session(pg) as s:
            actor = s.scalar(
                select(WorkspaceMembership).where(WorkspaceMembership.user_id == owner_id)
            )
            barrier.wait()
            try:
                role = get_custom_role(s, ws_id, role_id)
                create_invite(
                    s,
                    workspace_id=ws_id,
                    actor=actor,
                    email="z@example.com",
                    choice=RoleChoice(custom=role),
                )
                s.commit()
                outcomes[0] = "ok"
            except RoleError as e:  # role already deleted -> clean 404
                s.rollback()
                outcomes[0] = e.status_code
            except Exception as e:
                s.rollback()
                outcomes[0] = repr(e)

    def delete_side():
        with Session(pg) as s:
            barrier.wait()
            try:
                role = get_custom_role(s, ws_id, role_id, exclusive=True)
                delete_role(s, role=role)
                s.commit()
                outcomes[1] = "ok"
            except Exception as e:
                s.rollback()
                outcomes[1] = repr(e)

    threads = [threading.Thread(target=invite_side), threading.Thread(target=delete_side)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(not t.is_alive() for t in threads), "deadlock or hang"
    assert outcomes[1] == "ok" and outcomes[0] in ("ok", 404), outcomes
    with Session(pg) as s:  # the role is gone and nothing references it
        assert s.scalar(text("SELECT count(*) FROM workspace_roles")) == 0
        assert s.scalar(text("SELECT count(*) FROM workspace_invites")) == 0
