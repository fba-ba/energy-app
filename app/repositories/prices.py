"""Accès aux prix spot quart-horaires (`spot_prices_quarter_hourly`) et aux
prix EPEX SPP mensuels (`epex_spp_monthly`)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import bindparam, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import EpexMonthlyPrice, SpotPriceQuarterHourly


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


def retransform_all(session: Session, a: Decimal, b: Decimal) -> int:
    """Recalcule `price_eur_kwh_transformed_micro` pour toutes les lignes à
    partir du prix brut (`price_eur_mwh_raw_micro`), utilisé lors d'un
    changement de formule de prix. Retourne le nombre de lignes mises à jour.
    """
    from app.domain.pricing import transform_raw_mwh_micro_to_kwh_micro

    rows = session.execute(
        select(SpotPriceQuarterHourly.id, SpotPriceQuarterHourly.price_eur_mwh_raw_micro)
    ).all()
    if not rows:
        return 0
    updates = [
        {"row_id": row_id, "value": transform_raw_mwh_micro_to_kwh_micro(raw, a, b)}
        for row_id, raw in rows
    ]
    session.execute(
        SpotPriceQuarterHourly.__table__.update()
        .where(SpotPriceQuarterHourly.id == bindparam("row_id"))
        .values(price_eur_kwh_transformed_micro=bindparam("value")),
        updates,
    )
    return len(updates)


def upsert_epex_monthly_price(session: Session, month: str, price_eur_mwh_micro: int) -> None:
    """Insère ou met à jour le prix EPEX SPP mensuel (mois au format YYYY-MM-01)."""
    stmt = sqlite_insert(EpexMonthlyPrice.__table__).values(
        month=month, price_eur_mwh_micro=price_eur_mwh_micro
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["month"],
        set_={"price_eur_mwh_micro": stmt.excluded.price_eur_mwh_micro},
    )
    session.connection().execute(stmt)


def get_epex_monthly_prices(session: Session) -> list[EpexMonthlyPrice]:
    """Retourne tous les prix EPEX SPP mensuels, triés par mois."""
    stmt = select(EpexMonthlyPrice).order_by(EpexMonthlyPrice.month)
    return list(session.execute(stmt).scalars().all())


def get_epex_monthly_index(session: Session) -> dict[str, int]:
    """Retourne `{'YYYY-MM': price_eur_mwh_micro}` pour un accès rapide par mois."""
    return {p.month[:7]: p.price_eur_mwh_micro for p in get_epex_monthly_prices(session)}
