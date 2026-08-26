"""Service de synchronisation des prix spot Elexys."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from app.config import Settings
from app.domain.pricing import transform_price_to_micro
from app.domain.units import eur_to_micro
from app.ingestion.elexys import ElexysClient, PricePoint
from app.logging_conf import get_logger
from app.repositories import meta
from app.repositories import prices as prices_repo
from app.repositories import readings as readings_repo

logger = get_logger("prices")


def _transform_point(point: PricePoint, settings: Settings) -> dict:
    """Convertit un point Elexys brut en enregistrement persistant (micro-unités)."""
    return {
        "timestamp_local": point.timestamp_local,
        "timestamp_utc": point.timestamp_utc,
        "price_eur_mwh_raw_micro": eur_to_micro(point.price_eur_mwh),
        "price_eur_kwh_transformed_micro": transform_price_to_micro(
            point.price_eur_mwh,
            a=Decimal(settings.price_transform_a),
            b=Decimal(settings.price_transform_b),
        ),
        "source_key": "elexys",
        "source_url": "",
        "retrieved_at": datetime.now(UTC).replace(tzinfo=None),
    }


def determine_period(session, settings: Settings) -> tuple[date, date] | None:
    """Détermine la période (from, until) à partir des données importées."""
    min_dt, max_dt = readings_repo.get_reading_time_bounds(session)
    if min_dt is None or max_dt is None:
        return None
    start = min_dt.date()
    end = max_dt.date()
    return start, end


def sync_prices(
    session,
    settings: Settings,
    from_date: date | None = None,
    until_date: date | None = None,
    refresh: bool = False,
) -> dict:
    """Récupère les prix Elexys pour la période et les enregistre (upsert).

    `from_date` / `until_date` peuvent être surchargées ; sinon elles sont
    déduites des données importées.
    """
    if from_date is None or until_date is None:
        period = determine_period(session, settings)
        if period is None:
            raise ValueError("Aucune donnée importée : impossible de déduire la période de prix.")
        if from_date is None:
            from_date = period[0]
        if until_date is None:
            until_date = period[1]

    client = ElexysClient(settings)
    outcome = client.fetch(from_date, until_date, refresh=refresh)

    if outcome.status == "erreur" or not outcome.points:
        logger.error(
            "Aucun prix Elexys récupéré",
            extra={"url": outcome.source_url, "error": outcome.error or "aucune donnée"},
        )
        return {
            "status": "erreur",
            "error": outcome.error or "Elexys n'a retourné aucun prix.",
            "count": 0,
            "source_url": outcome.source_url,
        }

    records = [_transform_point(p, settings) for p in outcome.points]
    for rec in records:
        rec["source_url"] = outcome.source_url
    prices_repo.upsert_quarter_prices(session, records)

    meta.set_metadata(
        session,
        "price_transform",
        {
            "formula": f"({settings.price_transform_a} + {settings.price_transform_b} × prix_mwh) / 1000",
            "a": settings.price_transform_a,
            "b": settings.price_transform_b,
            "source": "elexys",
            "last_url": outcome.source_url,
            "last_retrieved_at": outcome.retrieved_at.isoformat(),
        },
    )

    logger.info(
        "Prix Elexys synchronisés",
        extra={
            "url": outcome.source_url,
            "count": len(records),
            "status": outcome.status,
            "from_cache": outcome.from_cache,
        },
    )
    return {
        "status": "ok",
        "count": len(records),
        "source_url": outcome.source_url,
        "from_cache": outcome.from_cache,
    }
