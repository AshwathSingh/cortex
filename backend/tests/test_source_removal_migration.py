"""Existing cleanup plans survive upgrade, downgrade and re-upgrade on PostgreSQL."""

import uuid

from alembic import command
from sqlalchemy import create_engine, text

from tests.test_roles_integrity import scratch_url, _alembic  # noqa: F401


def test_existing_removal_journals_round_trip(scratch_url):
    cfg = _alembic()
    command.upgrade(cfg, "20261117_16")
    engine = create_engine(scratch_url)
    ws, done, pending = [uuid.uuid4() for _ in range(3)]
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO workspaces (id, name) VALUES (:id, 'migration test')"
                ),
                {"id": ws},
            )
            for op, is_pending, key in [
                (done, False, "Issue:1"),
                (pending, True, "Issue:2"),
            ]:
                conn.execute(
                    text("""INSERT INTO source_removals
                    (id, workspace_id, kind, external_ref, revision, pending, targets)
                    VALUES (:id, :ws, 'github', :ref, :revision, :pending,
                    json_build_object('keys', json_build_array(CAST(:key AS text))))"""),
                    {
                        "id": op,
                        "ws": ws,
                        "ref": str(op),
                        "revision": str(op),
                        "pending": is_pending,
                        "key": key,
                    },
                )
        for iteration in range(2):
            command.upgrade(cfg, "head")
            with engine.connect() as conn:
                assert conn.execute(
                    text(
                        "SELECT source_removal_revision, source_removals_pending FROM workspaces WHERE id=:ws"
                    ),
                    {"ws": ws},
                ).one() == (2, 1)
                assert set(
                    conn.scalars(text("SELECT target_key FROM source_removal_targets"))
                ) == {"Issue:1", "Issue:2"}
                assert (
                    conn.scalar(
                        text("SELECT targets FROM source_removals WHERE id=:id"),
                        {"id": done},
                    )
                    == {}
                )
                assert conn.scalar(
                    text("SELECT targets FROM source_removals WHERE id=:id"),
                    {"id": pending},
                ) == {"keys": ["Issue:2"]}
            if iteration == 0:
                command.downgrade(cfg, "20261117_16")
                with engine.connect() as conn:
                    assert conn.scalar(
                        text("SELECT targets FROM source_removals WHERE id=:id"),
                        {"id": done},
                    ) == {"keys": ["Issue:1"]}
    finally:
        engine.dispose()
