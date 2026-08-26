"""Tests d'export : ordre exact des 21 colonnes du récap horaire."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal

from app.services.aggregation import RECAP_COLUMNS, RECAP_FRENCH_LABELS
from app.services.exports import export_recap_csv, recap_to_public_rows

EXPECTED_LABELS = [
    "Date-Heure",
    "Prélevée (kWh)",
    "Injectée (kWh)",
    "Solde (Prél-Inj)",
    "Label Heure",
    "Cumul Net (kWh)",
    "Cumul Prélevée",
    "Cumul Injectée",
    "Prélevée (kWh) [copie]",
    "Injectée (kWh) [copie]",
    "Cumul Net [copie]",
    "Cumul Prélevée [copie]",
    "Cumul Injectée [copie]",
    "Label Axe X",
    "Cumul Injecté (EUR)",
    "Clé Prix",
    "Prix Horaire (€/kWh)",
    "Injecté (EUR)",
    "Cumul mensuel prélevé (kWh)",
    "Cumul mensuel injecté (kWh)",
    "Cumul mensuel injecté (EUR)",
]


def test_21_columns_in_exact_order():
    assert len(RECAP_COLUMNS) == 21
    assert RECAP_FRENCH_LABELS == EXPECTED_LABELS


def _sample_row() -> dict:
    ts = datetime(2026, 6, 17, 21, 0)
    return {
        "date_heure": ts,
        "prelevee_kwh": Decimal("0.010"),
        "injectee_kwh": Decimal("2.430"),
        "solde_prel_inj": Decimal("-2.420"),
        "label_heure": "17/6 21h",
        "cumul_net_kwh": Decimal("2.420"),
        "cumul_prelevee": Decimal("0.010"),
        "cumul_injectee": Decimal("2.430"),
        "prelevee_kwh_copie": Decimal("0.010"),
        "injectee_kwh_copie": Decimal("2.430"),
        "cumul_net_copie": Decimal("2.420"),
        "cumul_prelevee_copie": Decimal("0.010"),
        "cumul_injectee_copie": Decimal("2.430"),
        "label_axe_x": "21h",
        "cumul_injecte_eur": Decimal("0.075092"),
        "cle_prix": "17/06/2026|21u00",
        "prix_horaire_eur_kwh": Decimal("0.030902"),
        "injecte_eur": Decimal("0.075092"),
        "cumul_mensuel_preleve": Decimal("0.010"),
        "cumul_mensuel_injecte": Decimal("2.430"),
        "cumul_mensuel_injecte_eur": Decimal("0.075092"),
    }


def test_csv_header_and_row():
    csv_text = export_recap_csv([_sample_row()])
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    assert header == EXPECTED_LABELS
    row = next(reader)
    assert row[0] == "2026-06-17T21:00:00"
    assert row[15] == "17/06/2026|21u00"


def test_public_rows_labels():
    public = recap_to_public_rows([_sample_row()])[0]
    assert list(public.keys()) == EXPECTED_LABELS
    assert public["Prélevée (kWh)"] == 0.010
