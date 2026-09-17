"""Modèles SQLAlchemy (persistance SQLite).

Conventions de stockage numérique (voir `app/domain/units.py`) :
- Énergies en **millièmes de kWh** (colonnes suffixées `_milli`, type INTEGER) ;
- Prix et montants en **millionièmes d'euro** (colonnes suffixées `_micro`, type INTEGER).
Aucun nombre n'est stocké sous forme de chaîne formatée.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    """Horodatage UTC courant (naïf, convention de la base)."""
    return datetime.now(UTC).replace(tzinfo=None)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_file: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(32), default="in_progress")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    readings: Mapped[list[EnergyReadingRaw]] = relationship(back_populates="batch")


class EnergyReadingRaw(Base):
    __tablename__ = "energy_readings_raw"
    __table_args__ = (
        UniqueConstraint("dedup_hash", name="uq_energy_readings_dedup_hash"),
        Index("ix_energy_readings_site_ean_time", "site_name", "ean_number", "data_time_utc"),
        Index("ix_energy_readings_import_batch", "import_batch_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    source_row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    site_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ean_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meter_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_data_period: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    variable_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    granularity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    aggregation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_data_period_frequency: Mapped[int | None] = mapped_column(Integer, nullable=True)

    data_time_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_time_local: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    data_time_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    value_kwh_milli: Mapped[int | None] = mapped_column(Integer, nullable=True)

    dedup_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    batch: Mapped[ImportBatch | None] = relationship(back_populates="readings")


class SpotPriceQuarterHourly(Base):
    __tablename__ = "spot_prices_quarter_hourly"
    __table_args__ = (
        UniqueConstraint("timestamp_utc", "source_key", name="uq_spot_prices_ts_source"),
        Index("ix_spot_prices_timestamp_local", "timestamp_local"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp_local: Mapped[datetime] = mapped_column(DateTime)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime)
    price_eur_mwh_raw_micro: Mapped[int] = mapped_column(Integer)
    price_eur_kwh_transformed_micro: Mapped[int] = mapped_column(Integer)
    source_key: Mapped[str] = mapped_column(String(64), default="elexys")
    source_url: Mapped[str] = mapped_column(String(2048), default="")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MonthlyIndexPrice(Base):
    """Indice mensuel saisi manuellement (ex. EPEX SPP pour Octa+, BELPEXM pour TotalEnergie).

    `index_key` identifie l'indice (voir `PricingFormulaDef.index_key`) ;
    plusieurs formules peuvent nécessiter des indices différents.
    """

    __tablename__ = "monthly_index_prices"
    __table_args__ = (
        UniqueConstraint("index_key", "month", name="uq_monthly_index_prices_key_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_key: Mapped[str] = mapped_column(String(32))
    month: Mapped[str] = mapped_column(String(10))  # YYYY-MM-01
    price_eur_mwh_micro: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class EnergyHourly(Base):
    __tablename__ = "energy_hourly"
    __table_args__ = (
        UniqueConstraint("site_name", "ean_number", "timestamp_utc", name="uq_energy_hourly"),
        Index("ix_energy_hourly_site_ean", "site_name", "ean_number"),
        Index("ix_energy_hourly_timestamp", "timestamp_utc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp_local: Mapped[datetime] = mapped_column(DateTime)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime)
    site_name: Mapped[str] = mapped_column(String(255))
    ean_number: Mapped[str] = mapped_column(String(64))
    withdrawn_kwh_milli: Mapped[int] = mapped_column(Integer, default=0)
    injected_kwh_milli: Mapped[int] = mapped_column(Integer, default=0)
    balance_withdrawn_minus_injected_kwh_milli: Mapped[int] = mapped_column(Integer, default=0)
    spot_price_eur_kwh_micro: Mapped[int | None] = mapped_column(Integer, nullable=True)
    injected_value_eur_micro: Mapped[int | None] = mapped_column(Integer, nullable=True)
    energy_point_count: Mapped[int] = mapped_column(Integer, default=0)
    price_point_count: Mapped[int] = mapped_column(Integer, default=0)
    energy_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    price_complete: Mapped[bool] = mapped_column(Boolean, default=False)


class MonthlyTotal(Base):
    __tablename__ = "monthly_totals"
    __table_args__ = (
        UniqueConstraint("site_name", "ean_number", "month", name="uq_monthly_totals"),
        Index("ix_monthly_totals_month", "month"),
        Index("ix_monthly_totals_site_ean", "site_name", "ean_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    month: Mapped[str] = mapped_column(String(10))  # YYYY-MM-01
    site_name: Mapped[str] = mapped_column(String(255))
    ean_number: Mapped[str] = mapped_column(String(64))
    withdrawn_kwh_milli: Mapped[int] = mapped_column(Integer, default=0)
    injected_kwh_milli: Mapped[int] = mapped_column(Integer, default=0)
    net_injected_minus_withdrawn_kwh_milli: Mapped[int] = mapped_column(Integer, default=0)
    injected_value_eur_micro: Mapped[int] = mapped_column(Integer, default=0)
    average_spot_price_eur_kwh_micro: Mapped[int | None] = mapped_column(Integer, nullable=True)
    negative_price_hours: Mapped[int] = mapped_column(Integer, default=0)
    hours_with_missing_energy: Mapped[int] = mapped_column(Integer, default=0)
    hours_with_missing_price: Mapped[int] = mapped_column(Integer, default=0)


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    __table_args__ = (Index("ix_data_quality_issues_batch", "import_batch_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    issue_type: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    message: Mapped[str] = mapped_column(Text)
    source_row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AppMetadata(Base):
    __tablename__ = "app_metadata"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
