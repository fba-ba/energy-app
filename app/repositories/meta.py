"""Accès aux tables techniques (lots d'import, anomalies, métadonnées)."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppMetadata, DataQualityIssue, ImportBatch, utcnow


def create_batch(session: Session, source_file: str) -> ImportBatch:
    batch = ImportBatch(source_file=source_file, status="in_progress", started_at=utcnow())
    session.add(batch)
    session.flush()
    return batch


def finish_batch(
    session: Session,
    batch: ImportBatch,
    *,
    status: str,
    row_count: int,
    imported_count: int,
    duplicate_count: int,
    error: str | None = None,
) -> None:
    batch.status = status
    batch.row_count = row_count
    batch.imported_count = imported_count
    batch.duplicate_count = duplicate_count
    batch.error = error
    batch.finished_at = utcnow()
    session.add(batch)


def add_issues(session: Session, batch_id: int, issues: list[dict]) -> None:
    for issue in issues:
        session.add(
            DataQualityIssue(
                import_batch_id=batch_id,
                issue_type=issue["issue_type"],
                severity=issue.get("severity", "warning"),
                message=issue["message"],
                source_row_number=issue.get("source_row_number"),
                raw_data=issue.get("raw_data"),
            )
        )


def get_issues(session: Session, limit: int = 1000) -> list[DataQualityIssue]:
    stmt = (
        select(DataQualityIssue)
        .order_by(DataQualityIssue.created_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def set_metadata(session: Session, key: str, value: object) -> None:
    session.merge(
        AppMetadata(key=key, value=json.dumps(value, ensure_ascii=False), updated_at=utcnow())
    )


def get_metadata(session: Session, key: str) -> object | None:
    row = session.get(AppMetadata, key)
    if row is None:
        return None
    try:
        return json.loads(row.value)
    except json.JSONDecodeError:
        return row.value


# Clé technique de la formule de prix d'injection actuellement active.
ACTIVE_PRICING_FORMULA_KEY = "active_pricing_formula"


def get_active_formula_key(session: Session, default: str = "engie") -> str:
    """Retourne la clé de la formule de prix active (`"engie"` par défaut)."""
    value = get_metadata(session, ACTIVE_PRICING_FORMULA_KEY)
    if isinstance(value, str) and value:
        return value
    return default


def set_active_formula_key(session: Session, key: str) -> None:
    """Enregistre la clé de la formule de prix active."""
    set_metadata(session, ACTIVE_PRICING_FORMULA_KEY, key)
