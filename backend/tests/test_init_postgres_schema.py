import pytest

from scripts import init_postgres_schema


def test_main_disposes_engine_when_schema_inspection_fails(monkeypatch):
    disposed = []

    def fail_inspection(_engine):
        raise RuntimeError("inspection failed")

    monkeypatch.setattr(init_postgres_schema, "get_engine", object)
    monkeypatch.setattr(init_postgres_schema, "inspect", fail_inspection)
    monkeypatch.setattr(init_postgres_schema, "dispose_engine", lambda: disposed.append(True))

    with pytest.raises(RuntimeError, match="inspection failed"):
        init_postgres_schema.main()

    assert disposed == [True]
