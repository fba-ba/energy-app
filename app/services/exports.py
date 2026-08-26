"""Exports CSV / XLSX avec les libellés français et les formats d'affichage."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal

from app.services.aggregation import (
    RECAP_COLUMNS,
    RECAP_FRENCH_LABELS,
    RECAP_TECHNICAL_KEYS,
)

MONTHLY_COLUMNS: list[tuple[str, str]] = [
    ("month", "Mois"),
    ("site_name", "Site"),
    ("ean_number", "EAN"),
    ("withdrawn_kwh_milli", "Prélevé (kWh)"),
    ("injected_kwh_milli", "Injecté (kWh)"),
    ("net_injected_minus_withdrawn_kwh_milli", "Net (Inj-Prél) (kWh)"),
    ("injected_value_eur_micro", "Valeur injectée (EUR)"),
    ("average_spot_price_eur_kwh_micro", "Prix moyen (€/kWh)"),
    ("negative_price_hours", "Heures à prix négatif"),
    ("hours_with_missing_energy", "Heures énergie manquante"),
    ("hours_with_missing_price", "Heures prix manquant"),
]

# Index des colonnes du récap (0-based) par format d'affichage.
_KWH_FORMATS = {"Prélevée (kWh)", "Injectée (kWh)", "Solde (Prél-Inj)", "Cumul Net (kWh)",
                "Cumul Prélevée", "Cumul Injectée", "Prélevée (kWh) [copie]",
                "Injectée (kWh) [copie]", "Cumul Net [copie]", "Cumul Prélevée [copie]",
                "Cumul Injectée [copie]", "Cumul mensuel prélevé (kWh)",
                "Cumul mensuel injecté (kWh)"}
_EUR_FORMATS = {"Cumul Injecté (EUR)", "Injecté (EUR)", "Cumul mensuel injecté (EUR)"}
_PRICE_FORMATS = {"Prix Horaire (€/kWh)"}


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def recap_to_public_rows(rows: list[dict]) -> list[dict]:
    """Convertit les lignes internes en lignes publiques (libellés français)."""
    out = []
    for row in rows:
        public: dict = {}
        for key, label in RECAP_COLUMNS:
            value = row.get(key)
            if key == "date_heure":
                public[label] = value.isoformat() if isinstance(value, datetime) else value
            elif isinstance(value, Decimal):
                public[label] = _as_float(value)
            else:
                public[label] = value
        out.append(public)
    return out


def _recap_value_sequence(row: dict) -> list[object]:
    return [row.get(key) for key in RECAP_TECHNICAL_KEYS]


def export_recap_csv(rows: list[dict]) -> str:
    """Export CSV du récap horaire (21 colonnes, ordre exact)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(RECAP_FRENCH_LABELS)
    for row in rows:
        values = []
        for key in RECAP_TECHNICAL_KEYS:
            value = row.get(key)
            if isinstance(value, datetime):
                values.append(value.isoformat())
            elif isinstance(value, Decimal):
                values.append("" if value is None else format(float(value), "f"))
            elif value is None:
                values.append("")
            else:
                values.append(value)
        writer.writerow(values)
    return buffer.getvalue()


def export_recap_xlsx(rows: list[dict]) -> bytes:
    """Export XLSX du récap horaire avec formats d'affichage (3 déc. kWh, 2 déc. €)."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Récap"
    ws.append(RECAP_FRENCH_LABELS)

    for row in rows:
        values = []
        for key in RECAP_TECHNICAL_KEYS:
            value = row.get(key)
            values.append(value if isinstance(value, (datetime, str)) or value is None else _as_float(value))
        ws.append(values)

    for col_idx, (_, label) in enumerate(RECAP_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx)
        if label in _KWH_FORMATS:
            cell.number_format = "0.000"
        elif label in _EUR_FORMATS:
            cell.number_format = "0.00"
        elif label in _PRICE_FORMATS:
            cell.number_format = "0.000000"
        for r in range(2, len(rows) + 2):
            if label in (*_KWH_FORMATS, *_EUR_FORMATS, *_PRICE_FORMATS):
                ws.cell(row=r, column=col_idx).number_format = cell.number_format

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def monthly_to_public_rows(records: list[dict]) -> list[dict]:
    """Convertit les totaux mensuels en lignes publiques (libellés français)."""
    out = []
    for rec in records:
        public = {
            "Mois": rec["month"],
            "Site": rec["site_name"],
            "EAN": rec["ean_number"],
            "Prélevé (kWh)": float(rec["withdrawn_kwh_milli"]) / 1000,
            "Injecté (kWh)": float(rec["injected_kwh_milli"]) / 1000,
            "Net (Inj-Prél) (kWh)": float(rec["net_injected_minus_withdrawn_kwh_milli"]) / 1000,
            "Valeur injectée (EUR)": (
                float(rec["injected_value_eur_micro"]) / 1_000_000
            ),
            "Prix moyen (€/kWh)": (
                float(rec["average_spot_price_eur_kwh_micro"]) / 1_000_000
                if rec["average_spot_price_eur_kwh_micro"] is not None
                else None
            ),
            "Heures à prix négatif": rec["negative_price_hours"],
            "Heures énergie manquante": rec["hours_with_missing_energy"],
            "Heures prix manquant": rec["hours_with_missing_price"],
        }
        out.append(public)
    return out


def export_monthly_csv(records: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    labels = [label for _, label in MONTHLY_COLUMNS]
    writer.writerow(labels)
    for rec in monthly_to_public_rows(records):
        writer.writerow([rec.get(label) for label in labels])
    return buffer.getvalue()


def export_monthly_xlsx(records: list[dict]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Synthèse mensuelle"
    labels = [label for _, label in MONTHLY_COLUMNS]
    ws.append(labels)
    for rec in monthly_to_public_rows(records):
        ws.append([rec.get(label) for label in labels])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
