"""Tests d'intégration : sélection et bascule de la formule de prix d'injection."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from app.config import Settings
from app.domain.pricing import transform_price_to_micro
from app.domain.units import eur_to_micro
from app.models import EnergyReadingRaw, SpotPriceQuarterHourly
from app.repositories import aggregates as aggregates_repo
from app.repositories import meta
from app.services.importer import rebuild_aggregates
from app.services.pricing_formula import list_formulas, set_epex_monthly_price, switch_formula


def _settings() -> Settings:
    return Settings(timezone="Europe/Brussels")


def _add_reading(session, ts: datetime, direction: str, value_milli: int, dedup: str) -> None:
    session.add(
        EnergyReadingRaw(
            site_name="SITE1",
            ean_number="EAN1",
            data_time_local=ts,
            data_time_utc=ts,
            direction=direction,
            value_kwh_milli=value_milli,
            variable_name="Consumption (A+) Totals" if direction == "withdrawal" else "Production (-A) Totals",
            raw_data_period="Minute",
            dedup_hash=dedup,
        )
    )


def _add_price(session, ts: datetime, raw_mwh: Decimal) -> None:
    """Insère un prix Elexys comme le ferait `sync_prices` (formule Engie par défaut)."""
    micro = eur_to_micro(raw_mwh)
    session.add(
        SpotPriceQuarterHourly(
            timestamp_local=ts,
            timestamp_utc=ts,
            price_eur_mwh_raw_micro=micro,
            price_eur_kwh_transformed_micro=transform_price_to_micro(raw_mwh),
            source_key="elexys",
            source_url="",
        )
    )


def _quarters(day: datetime, hour: int) -> list[datetime]:
    return [datetime(day.year, day.month, day.day, hour, m) for m in (0, 15, 30, 45)]


def test_list_formulas_default_active_is_engie(db_session):
    settings = _settings()
    formulas = list_formulas(db_session, settings)
    keys = {f["key"] for f in formulas}
    assert keys == {"engie", "bolt", "octa_plus"}
    active = [f for f in formulas if f["active"]]
    assert len(active) == 1
    assert active[0]["key"] == "engie"


def test_switch_to_bolt_retransforms_elexys_prices(db_session):
    settings = _settings()
    quarters = _quarters(datetime(2026, 7, 1), 0)
    for i, q in enumerate(quarters):
        _add_reading(db_session, q, "withdrawal", 100, dedup=f"w{i}")
        _add_price(db_session, q, Decimal("100"))
    db_session.flush()

    rebuild_aggregates(db_session, settings)
    db_session.flush()
    hourly = aggregates_repo.get_hourly(db_session)
    # Engie : (-17.3 + 0.3 × 100) / 1000 = 0.0127 €/kWh.
    assert hourly[0].spot_price_eur_kwh_micro == 12700

    result = switch_formula(db_session, settings, "bolt")
    assert result["formula"] == "bolt"
    assert meta.get_active_formula_key(db_session) == "bolt"

    hourly = aggregates_repo.get_hourly(db_session)
    # Bolt : (-20 + 1 × 100) / 1000 = 0.080 €/kWh.
    assert hourly[0].spot_price_eur_kwh_micro == 80000


def test_switch_to_octa_plus_blocked_without_epex_price(db_session):
    settings = _settings()
    quarters = _quarters(datetime(2026, 7, 1), 0)
    for i, q in enumerate(quarters):
        _add_reading(db_session, q, "withdrawal", 100, dedup=f"w{i}")
        _add_price(db_session, q, Decimal("100"))
    db_session.flush()
    rebuild_aggregates(db_session, settings)
    db_session.flush()

    with pytest.raises(ValueError, match="EPEX SPP"):
        switch_formula(db_session, settings, "octa_plus")

    # La base n'est pas modifiée : la formule active reste celle par défaut.
    assert meta.get_active_formula_key(db_session) == "engie"
    hourly = aggregates_repo.get_hourly(db_session)
    assert hourly[0].spot_price_eur_kwh_micro == 12700


def test_switch_to_octa_plus_succeeds_with_epex_price(db_session):
    settings = _settings()
    quarters = _quarters(datetime(2026, 7, 1), 0)
    for i, q in enumerate(quarters):
        _add_reading(db_session, q, "injection", 500, dedup=f"i{i}")
    db_session.flush()
    rebuild_aggregates(db_session, settings)
    db_session.flush()

    set_epex_monthly_price(db_session, "2026-07", Decimal("100"))
    db_session.flush()

    result = switch_formula(db_session, settings, "octa_plus")
    assert result["formula"] == "octa_plus"

    hourly = aggregates_repo.get_hourly(db_session)
    # Octa+ : (100 × 0,852 − 13,89) / 1000 = 0,07131 €/kWh, constant sur le mois.
    assert hourly[0].spot_price_eur_kwh_micro == 71310
    assert hourly[0].price_complete is True


def test_unknown_formula_raises(db_session):
    settings = _settings()
    with pytest.raises(ValueError, match="inconnue"):
        switch_formula(db_session, settings, "does_not_exist")


def test_invalid_month_format_rejected(db_session):
    with pytest.raises(ValueError, match="invalide"):
        set_epex_monthly_price(db_session, "2026/07", Decimal("100"))
