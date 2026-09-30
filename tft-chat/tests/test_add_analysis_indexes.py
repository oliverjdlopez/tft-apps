from __future__ import annotations

from types import SimpleNamespace

from scripts import add_analysis_indexes
from db.models import Base


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Connection:
    def __init__(self):
        self.definitions: dict[str, str] = {}
        self.created: list[str] = []

    def execution_options(self, **kwargs):
        assert kwargs == {"isolation_level": "AUTOCOMMIT"}
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _statement, params):
        return _Result(self.definitions.get(params["index_name"]))

    def exec_driver_sql(self, statement):
        self.created.append(statement)
        index = next(item for item in add_analysis_indexes.ANALYSIS_INDEXES if item.name in statement)
        columns = ", ".join(index.columns)
        self.definitions[index.name] = (
            f"CREATE INDEX {index.name} ON public.{index.table} USING btree ({columns})"
        )


class _Engine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self):
        self.connection = _Connection()

    def connect(self):
        return self.connection


def test_analysis_index_migration_is_idempotent_and_concurrent() -> None:
    engine = _Engine()

    first = add_analysis_indexes.install_analysis_indexes(engine)
    second = add_analysis_indexes.install_analysis_indexes(engine)

    assert first["created"] == [index.name for index in add_analysis_indexes.ANALYSIS_INDEXES]
    assert second["created"] == []
    assert first["verified"] == second["verified"]
    assert all("CREATE INDEX CONCURRENTLY IF NOT EXISTS" in sql for sql in engine.connection.created)


def test_analysis_indexes_are_excluded_from_orm_startup_metadata() -> None:
    model_indexes = {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
    }
    assert model_indexes.isdisjoint(
        {index.name for index in add_analysis_indexes.ANALYSIS_INDEXES}
    )
