"""Tests de transformation et d'agrégation des prix."""

from __future__ import annotations

from decimal import Decimal

from app.domain.pricing import build_hourly_price, transform_price_eur_kwh, transform_price_to_micro
from app.domain.units import micro_to_eur


def test_price_transformation_reference():
    # 165.13 €/MWh doit produire 0.032239 €/kWh.
    result = transform_price_eur_kwh(Decimal("165.13"))
    assert result == Decimal("0.032239")


def test_price_transformation_to_micro():
    assert transform_price_to_micro(Decimal("165.13")) == 32239


def test_hourly_average_of_four_quarters():
    # Quarts du 31/07/2026 23:00 -> moyenne 0.03352 €/kWh.
    micros = [32239, 32908, 33457, 35476]
    hp = build_hourly_price(micros)
    assert hp.complete is True
    assert hp.point_count == 4
    assert hp.official_micro == 33520
    assert micro_to_eur(hp.official_micro) == Decimal("0.033520")


def test_negative_price_preserved():
    micros = [-1000, -2000, -3000, -4000]  # prix négatifs
    hp = build_hourly_price(micros)
    assert hp.complete is True
    assert hp.official_micro < 0


def test_incomplete_hour_no_official_price():
    hp = build_hourly_price([100, 200, 300], allow_incomplete=False)
    assert hp.complete is False
    assert hp.point_count == 3
    assert hp.official_micro is None
    assert hp.average_available_micro == 200


def test_incomplete_hour_with_tolerance():
    hp = build_hourly_price([100, 200, 300], allow_incomplete=True)
    assert hp.official_micro == 200
    assert hp.complete is False


def test_empty_hour():
    hp = build_hourly_price([])
    assert hp.point_count == 0
    assert hp.official_micro is None
    assert hp.average_available_micro is None
