"""T-10.1 table shape. These assertions pin the decisions, not the ORM."""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db.base import Base
from app.models import DataSource, SyncStatus


def test_data_sources_share_the_relational_metadata():
    assert DataSource.metadata is Base.metadata
    assert "data_sources" in Base.metadata.tables


def test_attempt_and_sync_timestamps_are_separate_columns():
    """A source that succeeded on Monday and failed today has to report both
    "Needs attention" and the real age of its data. One column would force the
    UI to either hide the failure or misstate the freshness."""
    columns = DataSource.__table__.c

    assert columns.last_attempted_at.nullable is False  # a row is born of an attempt
    assert columns.last_synced_at.nullable is True  # until one actually succeeds
    assert columns.last_error.nullable is True


def test_one_row_per_source_per_workspace():
    (unique,) = [
        constraint
        for constraint in DataSource.__table__.constraints
        if constraint.name == "uq_data_source_workspace_ref"
    ]
    assert [column.name for column in unique.columns] == [
        "workspace_id",
        "kind",
        "external_ref",
    ]


def test_the_syncing_member_can_be_forgotten_without_losing_the_history():
    workspace_fk = next(iter(DataSource.__table__.c.workspace_id.foreign_keys))
    user_fk = next(iter(DataSource.__table__.c.last_synced_by.foreign_keys))

    assert (workspace_fk.target_fullname, workspace_fk.ondelete) == (
        "workspaces.id",
        "CASCADE",
    )
    assert (user_fk.target_fullname, user_fk.ondelete) == ("users.id", "SET NULL")
    assert DataSource.__table__.c.last_synced_by.nullable is True


def test_postgres_schema_uses_a_sync_status_enum_and_timestamptz():
    table_sql = str(
        CreateTable(DataSource.__table__).compile(dialect=postgresql.dialect())
    )

    assert "data_source_sync_status" in table_sql
    assert "TIMESTAMP WITH TIME ZONE" in table_sql
    assert [status.value for status in SyncStatus] == ["PENDING", "SUCCESS", "FAILED"]
