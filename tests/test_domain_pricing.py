"""Tests de transformation et d'agrégation des prix."""

from __future__ import annotations

from decimal import Decimal

from app.domain.pricing import (
    PRICING_FORMULAS,
    build_hourly_price,
    build_hourly_price_from_monthly,
    resolve_formula,
    transform_price_eur_kwh,
    transform_price_to_micro,
    transform_raw_mwh_micro_to_kwh_micro,
)
from app.domain.units import eur_to_micro, micro_to_eur


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


def test_bolt_formula_transformation():
    formula = resolve_formula("bolt")
    # Bolt : (-20 + 1 × prix_mwh) / 1000.
    result = transform_price_eur_kwh(Decimal("165.13"), a=formula.a, b=formula.b)
    assert result == Decimal("0.14513")


def test_octa_plus_formula_transformation():
    formula = resolve_formula("octa_plus")
    # Octa+ : (EPEX SPP × 0,852 − 13,89) / 1000.
    result = transform_price_eur_kwh(Decimal("100"), a=formula.a, b=formula.b)
    assert result == Decimal("0.07131")
    assert formula.requires == "monthly_index"
    assert formula.index_key == "epex_spp"


def test_total_energie_formula_transformation():
    formula = resolve_formula("total_energie")
    # TotalEnergie : (BELPEXM × 0,0235 − 0,625) / 1000.
    result = transform_price_eur_kwh(Decimal("100"), a=formula.a, b=formula.b)
    assert result == Decimal("0.001725")
    assert formula.requires == "monthly_index"
    assert formula.index_key == "belpexm"


def test_resolve_formula_engie_uses_settings_override():
    class FakeSettings:
        price_transform_a = "-5"
        price_transform_b = "0.5"

    formula = resolve_formula("engie", FakeSettings())
    assert formula.a == Decimal("-5")
    assert formula.b == Decimal("0.5")

    # Sans settings, les valeurs par défaut du registre s'appliquent.
    default_formula = resolve_formula("engie")
    assert default_formula.a == PRICING_FORMULAS["engie"].a


def test_build_hourly_price_from_monthly_present():
    formula = resolve_formula("octa_plus")
    epex_micro = eur_to_micro(Decimal("100"))
    hp = build_hourly_price_from_monthly(epex_micro, formula)
    assert hp.point_count == 1
    assert hp.complete is True
    assert micro_to_eur(hp.official_micro) == Decimal("0.07131")


def test_build_hourly_price_from_monthly_missing():
    formula = resolve_formula("octa_plus")
    hp = build_hourly_price_from_monthly(None, formula)
    assert hp.point_count == 0
    assert hp.complete is False
    assert hp.official_micro is None


def test_transform_raw_mwh_micro_to_kwh_micro_matches_decimal_path():
    formula = resolve_formula("bolt")
    raw_micro = eur_to_micro(Decimal("165.13"))
    assert transform_raw_mwh_micro_to_kwh_micro(raw_micro, formula.a, formula.b) == transform_price_to_micro(
        Decimal("165.13"), formula.a, formula.b
    )
