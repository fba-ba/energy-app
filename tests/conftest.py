"""Fixtures partagées des tests."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.domain.pricing import QUARTERS_PER_HOUR


@pytest.fixture()
def db_session() -> Session:
    """Session sur une base SQLite en mémoire, schéma créé."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    import app.models  # noqa: F401  (enregistre les modèles)

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def make_reading(
    *,
    site: str = "2742_510040811_1_",
    ean: str = "000000000000000001",
    ts: datetime,
    direction: str = "withdrawal",
    value_milli: int = 0,
    variable: str = "Consumption (A+) Totals",
    period: str = "Minute",
) -> dict:
    return {
        "site_name": site,
        "ean_number": ean,
        "data_time_local": ts,
        "data_time_utc": None,
        "direction": direction,
        "value_kwh_milli": value_milli,
        "variable_name": variable,
        "raw_data_period": period,
    }


def make_price(*, ts: datetime, micro: int) -> dict:
    return {"timestamp_local": ts, "price_eur_kwh_transformed_micro": micro}


@pytest.fixture()
def quarter_hour() -> int:
    return QUARTERS_PER_HOUR
