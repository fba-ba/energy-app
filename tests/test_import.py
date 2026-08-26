"""Tests d'import Excel (analyse et idempotence)."""

from __future__ import annotations

from datetime import datetime

import openpyxl
import pytest

from app.config import Settings
from app.ingestion.excel import parse_workbook
from app.repositories.readings import bulk_insert_readings

HEADER = [
    "SourceId", "SiteName", "SourceName", "EanNumber", "MeterNumber",
    "RawDataPeriod", "DataTime", "Unit", "Conso", "VariableName", "Granularity",
    "-", "Aggregation", "Year", "Month", "Day", "Hour", "Minute", "Second",
    "DayOfWeek", "WeekNumber", "RawDataPeriodFrequency",
]


def _write_workbook(path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(HEADER)
    rows = [
        # 4 quarts d'heure de prélèvement (Totals) le 2026-07-01 00:00.
        [1957860, "2742_510040811_1_", "1LGZ0569904403", "541449060018867111", None,
         "Minute", datetime(2026, 7, 1, 0, 0), "Kilowatt-hour", 0.351,
         "Consumption (A+) Totals", "Raw", None, "Raw", 2026, 7, 1, 0, 0, 0, 3, 27, 15],
        [1957860, "2742_510040811_1_", "1LGZ0569904403", "541449060018867111", None,
         "Minute", datetime(2026, 7, 1, 0, 15), "Kilowatt-hour", 0.000,
         "Consumption (A+) Totals", "Raw", None, "Raw", 2026, 7, 1, 0, 15, 0, 3, 27, 15],
        # Une ligne journalière (doit être exclue du récap horaire).
        [1957860, "2742_510040811_1_", "1LGZ0569904403", "541449060018867111", None,
         "Day", datetime(2026, 7, 1, 0, 0), "Kilowatt-hour", 1.326,
         "Consumption (+A) rate 1", "Raw", None, "Raw", 2026, 7, 1, 0, 0, 0, 3, 27, 1],
        # Une ligne avec valeur invalide -> anomalie.
        [1957860, "2742_510040811_1_", "1LGZ0569904403", "541449060018867111", None,
         "Minute", datetime(2026, 7, 1, 0, 30), "Kilowatt-hour", "N/A",
         "Production (+A) Totals", "Raw", None, "Raw", 2026, 7, 1, 0, 30, 0, 3, 27, 15],
    ]
    for r in rows:
        ws.append(r)
    wb.save(path)


def test_parse_workbook_and_direction(tmp_path):
    path = tmp_path / "sample.xlsx"
    _write_workbook(path)
    settings = Settings(timezone="Europe/Brussels", max_file_size_bytes=10_000_000)
    result = parse_workbook(path, settings)

    assert result.row_count == 4
    # 3 relevés exploitables, 1 anomalie (valeur non numérique).
    assert len(result.readings) == 3
    assert len(result.issues) == 1
    assert result.issues[0]["issue_type"] == "valeur_invalide"

    by_period = {(r["raw_data_period"], r["direction"]) for r in result.readings}
    assert ("Minute", "withdrawal") in by_period
    assert ("Day", "withdrawal") in by_period


def test_second_import_is_idempotent(tmp_path, db_session):
    path = tmp_path / "sample.xlsx"
    _write_workbook(path)
    settings = Settings(timezone="Europe/Brussels", max_file_size_bytes=10_000_000)
    readings = parse_workbook(path, settings).readings

    inserted, duplicates = bulk_insert_readings(db_session, readings, import_batch_id=None)
    assert inserted == len(readings)
    assert duplicates == 0

    inserted2, duplicates2 = bulk_insert_readings(db_session, readings, import_batch_id=None)
    assert inserted2 == 0
    assert duplicates2 == len(readings)


def test_validate_rejects_missing_file(tmp_path):
    settings = Settings(timezone="Europe/Brussels")
    with pytest.raises(ValueError, match="n'existe pas"):
        parse_workbook(tmp_path / "absent.xlsx", settings)
