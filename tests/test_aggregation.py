"""Tests d'agrégation : quarts d'heure -> heures -> cumuls -> totaux mensuels."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.services.aggregation import (
    aggregate_hourly,
    aggregate_quarterly,
    build_hourly_records,
    build_monthly_records,
    build_recap_rows,
    price_index_by_hour,
)

from .conftest import make_reading


def _quarters(day: datetime, hour: int) -> list[datetime]:
    return [
        datetime(day.year, day.month, day.day, hour, 0),
        datetime(day.year, day.month, day.day, hour, 15),
        datetime(day.year, day.month, day.day, hour, 30),
        datetime(day.year, day.month, day.day, hour, 45),
    ]


def test_four_quarters_aggregate_to_hour():
    readings = []
    for q in _quarters(datetime(2026, 7, 1), 7):
        readings.append(make_reading(ts=q, direction="withdrawal", value_milli=100))
    quarterly = aggregate_quarterly(readings)
    hourly = aggregate_hourly(quarterly)
    key = ("2742_510040811_1_", "541449060018867111", datetime(2026, 7, 1, 7, 0))
    assert hourly[key]["withdrawn_kwh_milli"] == 400
    assert hourly[key]["energy_point_count"] == 4
    assert hourly[key]["energy_complete"] is True


def test_rate1_plus_rate2_without_double_count():
    ts = datetime(2026, 7, 1, 0, 0)
    readings = [
        make_reading(ts=ts, direction="withdrawal", value_milli=351, variable="Consumption (A+) Totals"),
        make_reading(ts=ts, direction="withdrawal", value_milli=100, variable="Consumption (+A) totals rate 1"),
        make_reading(ts=ts, direction="withdrawal", value_milli=251, variable="Consumption (+A) totals rate 2"),
    ]
    quarterly = aggregate_quarterly(readings)
    key = ("2742_510040811_1_", "541449060018867111", ts)
    # La valeur Totals prime : pas de double comptage des rates.
    assert quarterly[key]["withdrawn_milli"] == 351


def test_rate_fallback_when_no_totals():
    ts = datetime(2026, 7, 1, 0, 0)
    readings = [
        make_reading(ts=ts, direction="injection", value_milli=100, variable="Production (-A) totals rate 1"),
        make_reading(ts=ts, direction="injection", value_milli=250, variable="Production (-A) totals rate 2"),
    ]
    quarterly = aggregate_quarterly(readings)
    key = ("2742_510040811_1_", "541449060018867111", ts)
    assert quarterly[key]["injected_milli"] == 350


def test_reference_hour_17_juin_21h():
    day = datetime(2026, 6, 17)
    hour = 21
    readings = []
    for i, q in enumerate(_quarters(day, hour)):
        readings.append(make_reading(ts=q, direction="withdrawal", value_milli=[2, 3, 2, 3][i]))
        readings.append(make_reading(ts=q, direction="injection", value_milli=[600, 610, 610, 610][i]))
    quarterly = aggregate_quarterly(readings)
    hourly = aggregate_hourly(quarterly)

    # 4 prix dont la moyenne (micro) vaut 30901.75 -> arrondi 30902 (0.030902 €/kWh).
    price_index = price_index_by_hour(
        [
            {"timestamp_local": q, "price_eur_kwh_transformed_micro": v}
            for q, v in zip(_quarters(day, hour), [30900, 30901, 30902, 30904], strict=True)
        ]
    )
    rows = build_recap_rows(hourly, price_index)
    row = rows[0]

    assert row["prelevee_kwh"] == Decimal("0.010")
    assert row["injectee_kwh"] == Decimal("2.430")
    assert row["solde_prel_inj"] == Decimal("-2.420")
    assert row["prix_horaire_eur_kwh"] == Decimal("0.030902")
    assert row["injecte_eur"] == Decimal("0.075092")
    assert row["cumul_net_kwh"] == Decimal("2.420")
    assert row["cle_prix"] == "17/06/2026|21u00"


def test_monthly_cumul_resets_at_month_change():
    readings = [
        make_reading(ts=datetime(2026, 6, 30, 23, 0), direction="injection", value_milli=1000),
        make_reading(ts=datetime(2026, 7, 1, 0, 0), direction="injection", value_milli=2000),
    ]
    quarterly = aggregate_quarterly(readings)
    hourly = aggregate_hourly(quarterly)
    rows = build_recap_rows(hourly, {})
    june = next(r for r in rows if r["date_heure"].month == 6)
    july = next(r for r in rows if r["date_heure"].month == 7)
    assert june["cumul_mensuel_injecte"] == Decimal("1.000")
    # Le cumul mensuel de juillet repart de zéro (pas 1 + 2).
    assert july["cumul_mensuel_injecte"] == Decimal("2.000")
    # Le cumul global, lui, continue.
    assert july["cumul_injectee"] == Decimal("3.000")


def test_monthly_totals_match_hourly_flows():
    readings = []
    for i in range(4):
        readings.append(
            make_reading(ts=datetime(2026, 7, 1, 0, i * 15), direction="withdrawal", value_milli=100 + i)
        )
    for i in range(4):
        readings.append(
            make_reading(ts=datetime(2026, 7, 2, 0, i * 15), direction="withdrawal", value_milli=200 + i)
        )
    quarterly = aggregate_quarterly(readings)
    hourly = aggregate_hourly(quarterly)
    hourly_records = build_hourly_records(hourly, {})
    monthly_records = build_monthly_records(hourly_records)

    month = monthly_records[0]
    assert month["withdrawn_kwh_milli"] == sum(h["withdrawn_kwh_milli"] for h in hourly_records)
    assert month["injected_kwh_milli"] == sum(h["injected_kwh_milli"] for h in hourly_records)


def test_true_zero_vs_missing_point():
    # Une heure avec 4 quarts présents (dont des zéros) est « complète » et vaut 0.
    day = datetime(2026, 7, 1)
    readings = [make_reading(ts=q, direction="withdrawal", value_milli=0) for q in _quarters(day, 3)]
    quarterly = aggregate_quarterly(readings)
    hourly = aggregate_hourly(quarterly)
    key = ("2742_510040811_1_", "541449060018867111", datetime(2026, 7, 1, 3, 0))
    assert hourly[key]["withdrawn_kwh_milli"] == 0
    assert hourly[key]["energy_complete"] is True
