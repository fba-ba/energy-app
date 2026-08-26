"""Tests de l'analyse des prix Elexys (HTML) et intégration réelle (optionnelle)."""

from __future__ import annotations

from datetime import date

import pytest

from app.config import Settings
from app.ingestion.elexys import (
    ElexysClient,
    _extract_export_url,
    build_url,
    parse_date_token,
    parse_hour_token,
    parse_html_prices,
    parse_xlsx_prices,
)

HTML_SAMPLE = """
<html><body>
<table>
  <thead><tr><th>Date</th><th>Heure</th><th>Euro</th></tr></thead>
  <tbody>
    <tr><td>31/07/2026</td><td>23u45</td><td>165.13</td></tr>
    <tr><td>31/07/2026</td><td>23u30</td><td>167.36</td></tr>
    <tr><td>31/07/2026</td><td>23u15</td><td>169.19</td></tr>
    <tr><td>31/07/2026</td><td>23u00</td><td>175.92</td></tr>
    <tr><td>31/07/2026</td><td>22u45</td><td>—</td></tr>
  </tbody>
</table>
</body></html>
"""


def test_parse_hour_token():
    assert parse_hour_token("23u45") == (23, 45)
    assert parse_hour_token("0u00") == (0, 0)
    assert parse_hour_token("7:30") == (7, 30)
    assert parse_hour_token("23") == (23, 0)
    assert parse_hour_token("n/a") is None


def test_parse_date_token():
    assert parse_date_token("31/07/2026") == date(2026, 7, 31)


def test_parse_html_prices_skips_missing():
    settings = Settings(timezone="Europe/Brussels")
    points = parse_html_prices(HTML_SAMPLE, settings.timezone)
    # 5 lignes dont 1 sans prix exploitable -> 4 points.
    assert len(points) == 4
    assert str(points[0].price_eur_mwh) == "165.13"


def test_build_url():
    url = build_url("https://www.elexys.be/fr/insights/quarter-hourly-belpex-day-ahead-spot-be",
                    date(2026, 6, 17), date(2026, 7, 31))
    assert url.endswith("?from=2026-06-17&until=2026-07-31")


def test_extract_export_url():
    html = '<a href="/fr/insights/export/xlsx/spot_belpex_quarter_hourly_table%3Aabc123">XLSX</a>'
    assert _extract_export_url(html) == "/fr/insights/export/xlsx/spot_belpex_quarter_hourly_table%3Aabc123"


def test_parse_xlsx_prices_with_title_row():
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Quarter hourly Spot Belpex © Elexys", None, None])
    ws.append([None, None, None])
    ws.append(["Date", "Heure", "Euro"])
    ws.append(["31/07/2026", "23u45", 165.13])
    ws.append(["31/07/2026", "23u30", 167.36])
    buffer = io.BytesIO()
    wb.save(buffer)

    points = parse_xlsx_prices(buffer.getvalue(), "Europe/Brussels")
    assert len(points) == 2
    assert str(points[0].price_eur_mwh) == "165.13"


@pytest.mark.elexys_live
def test_live_elexys_fetch():
    """Test d'intégration : contacte réellement Elexys (réseau requis)."""
    settings = Settings(timezone="Europe/Brussels")
    client = ElexysClient(settings)
    outcome = client.fetch(date(2026, 6, 17), date(2026, 6, 18))
    assert outcome.status in ("ok", "cache")
    assert len(outcome.points) > 0
