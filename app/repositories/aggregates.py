"""Accès aux agrégats horaires et mensuels (`energy_hourly`, `monthly_totals`)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import EnergyHourly, MonthlyTotal


def replace_hourly(session: Session, rows: list[dict]) -> None:
    """Remplace l'intégralité de `energy_hourly` par `rows`."""
    session.execute(delete(EnergyHourly))
    if rows:
        session.execute(EnergyHourly.__table__.insert(), rows)


def replace_monthly(session: Session, rows: list[dict]) -> None:
    """Remplace l'intégralité de `monthly_totals` par `rows`."""
    session.execute(delete(MonthlyTotal))
    if rows:
        session.execute(MonthlyTotal.__table__.insert(), rows)


def get_hourly(
    session: Session,
    site_name: str | None = None,
    ean_number: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[EnergyHourly]:
    stmt = select(EnergyHourly)
    if site_name:
        stmt = stmt.where(EnergyHourly.site_name == site_name)
    if ean_number:
        stmt = stmt.where(EnergyHourly.ean_number == ean_number)
    if start:
        stmt = stmt.where(EnergyHourly.timestamp_utc >= start)
    if end:
        stmt = stmt.where(EnergyHourly.timestamp_utc < end)
    stmt = stmt.order_by(EnergyHourly.timestamp_utc)
    return list(session.execute(stmt).scalars().all())


def get_monthly(
    session: Session,
    site_name: str | None = None,
    ean_number: str | None = None,
    month: str | None = None,
) -> list[MonthlyTotal]:
    stmt = select(MonthlyTotal)
    if site_name:
        stmt = stmt.where(MonthlyTotal.site_name == site_name)
    if ean_number:
        stmt = stmt.where(MonthlyTotal.ean_number == ean_number)
    if month:
        stmt = stmt.where(MonthlyTotal.month == month)
    stmt = stmt.order_by(MonthlyTotal.month)
    return list(session.execute(stmt).scalars().all())


def get_distinct_sites(session: Session) -> list[tuple[str, str]]:
    """Retourne les couples (site_name, ean_number) distincts."""
    stmt = (
        select(EnergyHourly.site_name, EnergyHourly.ean_number)
        .distinct()
        .order_by(EnergyHourly.site_name)
    )
    return [(s, e) for s, e in session.execute(stmt).all()]
