"""Contrôle qualité et validation de cohérence des données."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DataQualityIssue, SpotPriceQuarterHourly
from app.repositories import aggregates as aggregates_repo


def get_issues(session: Session, limit: int = 1000) -> list[dict]:
    stmt = select(DataQualityIssue).order_by(DataQualityIssue.created_at.desc()).limit(limit)
    return [
        {
            "id": i.id,
            "import_batch_id": i.import_batch_id,
            "issue_type": i.issue_type,
            "severity": i.severity,
            "message": i.message,
            "source_row_number": i.source_row_number,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in session.execute(stmt).scalars().all()
    ]


def validate(session: Session) -> dict:
    """Valide la cohérence globale et retourne un rapport structuré."""
    hourly_rows = aggregates_repo.get_hourly(session)
    monthly_rows = aggregates_repo.get_monthly(session)

    hourly_by_month: dict[tuple, dict] = defaultdict(
        lambda: {"withdrawn": 0, "injected": 0, "eur": 0}
    )
    for h in hourly_rows:
        month = h.timestamp_local.strftime("%Y-%m") + "-01"
        key = (h.site_name, h.ean_number, month)
        hourly_by_month[key]["withdrawn"] += h.withdrawn_kwh_milli
        hourly_by_month[key]["injected"] += h.injected_kwh_milli
        hourly_by_month[key]["eur"] += h.injected_value_eur_micro or 0

    reconciliations = []
    for m in monthly_rows:
        key = (m.site_name, m.ean_number, m.month)
        h = hourly_by_month.get(key)
        ok = False
        if h is not None:
            ok = (
                h["withdrawn"] == m.withdrawn_kwh_milli
                and h["injected"] == m.injected_kwh_milli
                and h["eur"] == m.injected_value_eur_micro
            )
        reconciliations.append(
            {
                "month": m.month,
                "site_name": m.site_name,
                "ean_number": m.ean_number,
                "concordant": ok,
            }
        )

    price_count = session.execute(
        select(func.count()).select_from(SpotPriceQuarterHourly)
    ).scalar_one()
    issue_count = session.execute(
        select(func.count()).select_from(DataQualityIssue)
    ).scalar_one()

    return {
        "hourly_rows": len(hourly_rows),
        "monthly_rows": len(monthly_rows),
        "price_points": price_count,
        "quality_issues": issue_count,
        "reconciliation": reconciliations,
        "all_reconciliations_ok": all(r["concordant"] for r in reconciliations),
    }
