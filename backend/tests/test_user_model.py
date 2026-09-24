import uuid

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models.user import User


def test_user_table_shape():
    table = User.__table__

    assert table.primary_key.columns.keys() == ["id"]
    assert table.c.id.type.as_uuid is True
    assert table.c.email.nullable is False
    assert table.c.password_hash.nullable is True
    assert table.c.github_id.nullable is True
    assert table.c.is_active.nullable is False
    assert table.c.created_at.nullable is False
    assert table.c.updated_at.nullable is False


def test_user_defaults_are_safe_for_new_email_account():
    user = User(email="developer@example.com", password_hash="argon2id-hash")

    assert user.email == "developer@example.com"
    assert user.password_hash == "argon2id-hash"
    assert user.github_id is None
    assert user.is_active is None  # SQLAlchemy applies the default during INSERT.


def test_postgres_schema_has_case_insensitive_email_and_github_uniqueness():
    dialect = postgresql.dialect()
    table_sql = str(CreateTable(User.__table__).compile(dialect=dialect))
    index_sql = {
        index.name: str(CreateIndex(index).compile(dialect=dialect))
        for index in User.__table__.indexes
    }

    assert "UUID NOT NULL" in table_sql
    assert "TIMESTAMP WITH TIME ZONE" in table_sql
    assert "CREATE UNIQUE INDEX uq_users_email_normalized ON users (lower(email))" in index_sql[
        "uq_users_email_normalized"
    ]
    assert "CREATE UNIQUE INDEX uq_users_github_id ON users (github_id)" in index_sql[
        "uq_users_github_id"
    ]


def test_user_id_default_generates_uuid():
    default = User.__table__.c.id.default

    assert default is not None
    assert isinstance(default.arg({}), uuid.UUID)
