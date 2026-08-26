"""Accès aux relevés bruts (`energy_readings_raw`)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import EnergyReadingRaw, utcnow


def bulk_insert_readings(
    session: Session,
    readings: list[dict],
    import_batch_id: int | None = None,
) -> tuple[int, int]:
    """Insère des relevés de façon idempotente.

    Retourne `(insérés, doublons)` en s'appuyant sur la contrainte unique
    `dedup_hash` (INSERT ... ON CONFLICT DO NOTHING).
    """
    if not readings:
        return (0, 0)
    now = utcnow()
    payload = [
        {**r, "import_batch_id": import_batch_id, "created_at": now}
        for r in readings
    ]
    stmt = sqlite_insert(EnergyReadingRaw.__table__).on_conflict_do_nothing(
        index_elements=["dedup_hash"]
    )
    result = session.connection().execute(stmt, payload)
    inserted = result.rowcount or 0
    return (inserted, len(payload) - inserted)


def get_reading_time_bounds(session: Session) -> tuple[datetime | None, datetime | None]:
    """Retourne (min, max) de `data_time_local` (heure locale Europe/Brussels).

    Les prix Elexys étant datés en heure locale, la période de récupération
    est déduite des horodatages locaux (et non UTC, sinon le dernier jour est
    amputé lors du décalage horaire).
    """
    stmt = select(
        func.min(EnergyReadingRaw.data_time_local),
        func.max(EnergyReadingRaw.data_time_local),
    )
    return session.execute(stmt).one()


def count_readings(session: Session) -> int:
    """Nombre total de relevés bruts."""
    return session.execute(select(func.count()).select_from(EnergyReadingRaw)).scalar_one()


def get_directions_bounds(session: Session) -> list[dict]:
    """Retourne les bornes par direction (pour la détection des prix manquants)."""
    stmt = (
        select(
            EnergyReadingRaw.direction,
            func.min(EnergyReadingRaw.data_time_utc),
            func.max(EnergyReadingRaw.data_time_utc),
        )
        .where(EnergyReadingRaw.data_time_utc.is_not(None))
        .group_by(EnergyReadingRaw.direction)
    )
    return [{"direction": d, "min": mn, "max": mx} for d, mn, mx in session.execute(stmt).all()]
