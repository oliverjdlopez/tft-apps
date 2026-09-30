"""Explicit additive migration for private composition experiment tables."""

from sqlalchemy import inspect
from db.models import COMPOSITION_MODELS
from db.session import engine_for, resolve_database_target


def migrate(engine):
    """Create missing experiment tables and refuse incompatible existing schemas.

    Args:
        engine: Explicit maintenance or isolated test database engine.
    """
    with engine.begin() as connection:
        inspector = inspect(connection)
        for model in COMPOSITION_MODELS:
            table = model.__table__
            if inspector.has_table(table.name):
                actual = {c["name"] for c in inspector.get_columns(table.name)}
                if actual != set(table.columns.keys()):
                    raise ValueError(f"Incompatible existing schema: {table.name}")
            else:
                table.create(connection)


def main():
    """Apply the additive migration using the configured complete app RDS target."""
    migrate(engine_for(resolve_database_target("app")))


if __name__ == "__main__":
    main()
