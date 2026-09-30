"""Shared helpers for db insert and session modules.

Generic database/DSN utilities and patch extraction.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from .models import AnalysisScope

_PATCH_RE = re.compile(r"(\d+\.\d+)")


def extract_patch(game_version: str | None) -> str | None:
    if not game_version:
        return None
    m = _PATCH_RE.search(game_version)
    return m.group(1) if m else None


def _looks_like_postgres(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith(("postgresql://", "postgres://")) or (
        "dbname=" in stripped and "=" in stripped
    )


def _sqlalchemy_url(dsn: str) -> str:
    if dsn.startswith("postgresql://"):
        return "postgresql+psycopg://" + dsn.removeprefix("postgresql://")
    if dsn.startswith("postgres://"):
        return "postgresql+psycopg://" + dsn.removeprefix("postgres://")
    return dsn


def existing_match_ids_from_table_models(table_models: dict[str, Any]):
    """Return a ``(session) -> set[str]`` reader of stored match ids.

    Reads ``match_id`` from normalized ``raw_matches``, used by ingestion to
    skip matches already stored.
    """
    match_model = table_models.get("raw_matches")
    match_id_column = getattr(match_model, "match_id", None)
    if match_id_column is None:
        return lambda session: set()

    def existing_match_ids(session: Any) -> set[str]:
        return {
            match_id
            for (match_id,) in session.query(match_id_column).distinct().all()
        }

    return existing_match_ids


# ===========================================================================
# Analytics builders (build_query_tables.py)
# Keep ambiguous display-name aggregates out of the published item rankings.
# Raw identities and exact item-slot facts remain available for validation.
# ===========================================================================


def discard_ambiguous_item_stats(session: Session, scope: AnalysisScope) -> set[str]:
    """Exclude multi-identity item names consistently across analytics batches.

    Args:
        session: Writer session holding the analysis scope transaction lock.
        scope: Analysis scope whose exact patch/set catalogue defines identities.

    Returns:
        Display names to omit from item-stat contributions for this batch.
    """
    import logging
    from sqlalchemy import delete, func, select
    from .models import ItemMetadata, ItemStatQueryTable

    names = set(session.scalars(
        select(ItemMetadata.item_name)
        .where(ItemMetadata.patch == scope.patch,
               ItemMetadata.tft_set_number == scope.tft_set_number)
        .group_by(ItemMetadata.item_name)
        .having(func.count() > 1)
    ))
    if names:
        # Catalogue-wide detection is independent of match order and batch size.
        # A newly discovered alias also removes earlier, now-partial rankings.
        session.execute(delete(ItemStatQueryTable).where(
            ItemStatQueryTable.scope_id == scope.scope_id,
            ItemStatQueryTable.item_name.in_(names),
        ))
        logging.getLogger('db.build_query_tables').warning(
            'Skipping item rankings for %d ambiguous display names in patch=%s set=%s: %s; '
            'raw items and item-slot facts are preserved',
            len(names), scope.patch, scope.tft_set_number, ', '.join(sorted(names)),
        )
    return names
