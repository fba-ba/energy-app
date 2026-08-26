"""Accès aux prix spot quart-horaires (`spot_prices_quarter_hourly`)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import SpotPriceQuarterHourly


def upsert_quarter_prices(session: Session, prices: list[dict]) -> int:
    """Insère ou met à jour les prix quart-horaires (upsert sur horodatage + source).

    Retourne le nombre de lignes affectées.
    """
    if not prices:
        return 0
    stmt = sqlite_insert(SpotPriceQuarterHourly.__table__)
    stmt = stmt.on_conflict_do_update(
        index_elements=["timestamp_utc", "source_key"],
        set_={
            "price_eur_mwh_raw_micro": stmt.excluded.price_eur_mwh_raw_micro,
            "price_eur_kwh_transformed_micro": stmt.excluded.price_eur_kwh_transformed_micro,
            "source_url": stmt.excluded.source_url,
            "retrieved_at": stmt.excluded.retrieved_at,
            "timestamp_local": stmt.excluded.timestamp_local,
        },
    )
    result = session.connection().execute(stmt, prices)
    return result.rowcount or 0


def get_prices_between(
    session: Session, start_utc: datetime, end_utc: datetime
) -> list[SpotPriceQuarterHourly]:
    """Retourne les prix dont `timestamp_utc` est dans [start_utc, end_utc[."""
    stmt = (
        select(SpotPriceQuarterHourly)
        .where(SpotPriceQuarterHourly.timestamp_utc >= start_utc)
        .where(SpotPriceQuarterHourly.timestamp_utc < end_utc)
        .order_by(SpotPriceQuarterHourly.timestamp_utc)
    )
    return list(session.execute(stmt).scalars().all())


def count_prices(session: Session) -> int:
    return len(session.execute(select(SpotPriceQuarterHourly.id)).scalars().all())
