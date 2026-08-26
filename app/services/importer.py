"""Orchestration de l'import Excel et de la reconstruction des agrégats."""

from __future__ import annotations

from pathlib import Path

from app.config import Settings, get_settings
from app.db import session_scope
from app.ingestion.excel import parse_workbook, validate_import_path
from app.logging_conf import get_logger
from app.models import EnergyReadingRaw, SpotPriceQuarterHourly
from app.repositories import aggregates as aggregates_repo
from app.repositories import meta
from app.repositories import readings as readings_repo
from app.services.aggregation import (
    aggregate_hourly,
    aggregate_quarterly,
    build_hourly_records,
    build_monthly_records,
    price_index_by_hour,
)
from app.services.prices import sync_prices
from app.services.quality import validate

logger = get_logger("importer")


def _reading_to_dict(r: EnergyReadingRaw) -> dict:
    return {
        "site_name": r.site_name,
        "ean_number": r.ean_number,
        "data_time_local": r.data_time_local,
        "data_time_utc": r.data_time_utc,
        "direction": r.direction,
        "value_kwh_milli": r.value_kwh_milli,
        "variable_name": r.variable_name,
        "raw_data_period": r.raw_data_period,
    }


def _price_to_dict(p: SpotPriceQuarterHourly) -> dict:
    return {
        "timestamp_local": p.timestamp_local,
        "price_eur_kwh_transformed_micro": p.price_eur_kwh_transformed_micro,
    }


def rebuild_aggregates(session, settings: Settings) -> dict:
    """Reconstruit `energy_hourly` et `monthly_totals` à partir des données brutes et des prix."""
    readings = [
        _reading_to_dict(r)
        for r in session.query(EnergyReadingRaw).order_by(EnergyReadingRaw.id).all()
    ]
    prices = [
        _price_to_dict(p)
        for p in session.query(SpotPriceQuarterHourly).order_by(SpotPriceQuarterHourly.timestamp_utc).all()
    ]

    quarterly = aggregate_quarterly(readings)
    hourly = aggregate_hourly(quarterly)
    price_index = price_index_by_hour(prices)
    hourly_records = build_hourly_records(hourly, price_index, settings.allow_incomplete_price)
    monthly_records = build_monthly_records(hourly_records)

    aggregates_repo.replace_hourly(session, hourly_records)
    aggregates_repo.replace_monthly(session, monthly_records)
    session.flush()

    logger.info(
        "Agrégats reconstruits",
        extra={"hours": len(hourly_records), "months": len(monthly_records)},
    )
    return {"hours": len(hourly_records), "months": len(monthly_records)}


def import_excel(
    path: str | Path,
    sheet_name: str = "Data",
    *,
    sync_prices_flag: bool = True,
    settings: Settings | None = None,
) -> dict:
    """Importe un classeur (transaction atomique, idempotent), synchronise les prix
    et reconstruit les agrégats.

    Un second import du même fichier ne crée aucun doublon (contrainte `dedup_hash`).
    """
    settings = settings or get_settings()
    resolved = validate_import_path(path, settings)
    parsed = parse_workbook(resolved, settings, sheet_name)

    with session_scope() as session:
        batch = meta.create_batch(session, str(resolved))
        inserted, duplicates = readings_repo.bulk_insert_readings(session, parsed.readings, batch.id)
        meta.add_issues(session, batch.id, parsed.issues)
        meta.finish_batch(
            session,
            batch,
            status="completed",
            row_count=parsed.row_count,
            imported_count=inserted,
            duplicate_count=duplicates,
        )
        rebuild_aggregates(session, settings)

    # Synchronisation des prix : best effort, ne fait pas échouer l'import.
    price_summary: dict = {"status": "skipped", "count": 0, "source_url": ""}
    if sync_prices_flag:
        try:
            with session_scope() as session:
                price_summary = sync_prices(session, settings)
            with session_scope() as session:
                rebuild_aggregates(session, settings)
        except Exception as exc:  # pragma: no cover - réseau
            logger.warning("Synchronisation des prix impossible", extra={"error": str(exc)})
            price_summary = {"status": "erreur", "error": str(exc), "count": 0}

    summary = {
        "source_file": str(resolved),
        "sheet_name": sheet_name,
        "row_count": parsed.row_count,
        "imported": inserted,
        "duplicates": duplicates,
        "issues": len(parsed.issues),
        "prices": price_summary,
    }
    logger.info("Import terminé", extra=summary)
    return summary


def import_ores_workbook(
    path: str | Path,
    sheet_name: str = "Data",
    settings: Settings | None = None,
) -> dict:
    """Pipeline complet de chargement d'un classeur ORES.

    Enchaîne :
      1. l'import (atomique, idempotent) ;
      2. la synchronisation des prix Elexys si nécessaire ;
      3. la reconstruction des agrégats horaires et mensuels ;
      4. la validation de cohérence.

    Retourne un dictionnaire avec `status` = ``"ok"`` ou ``"erreur"`` ainsi
    que le résumé de l'import et le rapport de validation.
    """
    settings = settings or get_settings()

    summary = import_excel(
        path,
        sheet_name=sheet_name,
        sync_prices_flag=True,
        settings=settings,
    )

    with session_scope() as session:
        report = validate(session)

    price_status = (summary.get("prices") or {}).get("status", "skipped")
    ok = price_status != "erreur" and report["all_reconciliations_ok"]

    return {
        "status": "ok" if ok else "erreur",
        "summary": summary,
        "validation": report,
    }
