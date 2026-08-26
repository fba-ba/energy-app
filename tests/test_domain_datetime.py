"""Tests de conversion de dates Excel et de gestion du fuseau Europe/Brussels."""

from __future__ import annotations

from datetime import datetime

from app.domain.datetime import (
    EXCEL_EPOCH,
    excel_serial_to_datetime,
    floor_to_hour,
    local_to_utc,
    to_aware_brussels,
)


def test_excel_serial_conversion():
    # Convention openpyxl : le numéro de série 1 correspond au 1899-12-31.
    assert excel_serial_to_datetime(1) == datetime(1899, 12, 31)
    # 2026-06-17 vaut (2026-06-17 - 1899-12-30) jours après l'époque Excel.
    expected = datetime(2026, 6, 17)
    serial = (expected - EXCEL_EPOCH).days
    assert excel_serial_to_datetime(serial) == expected


def test_excel_serial_datetime_kept():
    dt = datetime(2026, 7, 1, 12, 30)
    assert excel_serial_to_datetime(dt) == dt


def test_brussels_summer_is_utc_plus_2():
    aware = to_aware_brussels(datetime(2026, 7, 1, 12, 0), "Europe/Brussels")
    utc = local_to_utc(aware)
    assert utc.hour == 10  # 12:00 Bruxelles = 10:00 UTC en été


def test_brussels_winter_is_utc_plus_1():
    aware = to_aware_brussels(datetime(2026, 1, 15, 12, 0), "Europe/Brussels")
    utc = local_to_utc(aware)
    assert utc.hour == 11  # 12:00 Bruxelles = 11:00 UTC en hiver


def test_floor_to_hour():
    assert floor_to_hour(datetime(2026, 6, 17, 21, 45)) == datetime(2026, 6, 17, 21, 0)


def test_dst_transition_offsets():
    # Jour de passage à l'heure d'été (29/03/2026) : +2h ; heure d'hiver : +1h.
    winter = to_aware_brussels(datetime(2026, 3, 28, 12, 0), "Europe/Brussels")
    summer = to_aware_brussels(datetime(2026, 3, 30, 12, 0), "Europe/Brussels")
    assert local_to_utc(winter).hour == 11
    assert local_to_utc(summer).hour == 10
