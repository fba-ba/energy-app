"""Agrégation : relevés quart-horaires -> heures -> cumuls -> totaux mensuels.

Toutes les règles de calcul reproduisent la feuille `Récap` du classeur ORES :
- solde = prélevé - injecté ;
- cumul net = somme cumulée de (injecté - prélevé) ;
- injecté (EUR) = injectée (kWh) × prix horaire (€/kWh) ;
- cumuls globaux partitionnés par site/EAN, cumuls mensuels remis à zéro au
  changement de mois ;
- règle de précédence : registre « Totals » si présent, sinon somme des rates.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.domain.classification import is_totals
from app.domain.datetime import floor_to_hour
from app.domain.pricing import QUARTERS_PER_HOUR, build_hourly_price
from app.domain.units import micro_to_eur, milli_to_kwh, mul_milli_micro

# Ordre exact des 21 colonnes (clés techniques -> libellés français).
RECAP_COLUMNS: list[tuple[str, str]] = [
    ("date_heure", "Date-Heure"),
    ("prelevee_kwh", "Prélevée (kWh)"),
    ("injectee_kwh", "Injectée (kWh)"),
    ("solde_prel_inj", "Solde (Prél-Inj)"),
    ("label_heure", "Label Heure"),
    ("cumul_net_kwh", "Cumul Net (kWh)"),
    ("cumul_prelevee", "Cumul Prélevée"),
    ("cumul_injectee", "Cumul Injectée"),
    ("prelevee_kwh_copie", "Prélevée (kWh) [copie]"),
    ("injectee_kwh_copie", "Injectée (kWh) [copie]"),
    ("cumul_net_copie", "Cumul Net [copie]"),
    ("cumul_prelevee_copie", "Cumul Prélevée [copie]"),
    ("cumul_injectee_copie", "Cumul Injectée [copie]"),
    ("label_axe_x", "Label Axe X"),
    ("cumul_injecte_eur", "Cumul Injecté (EUR)"),
    ("cle_prix", "Clé Prix"),
    ("prix_horaire_eur_kwh", "Prix Horaire (€/kWh)"),
    ("injecte_eur", "Injecté (EUR)"),
    ("cumul_mensuel_preleve", "Cumul mensuel prélevé (kWh)"),
    ("cumul_mensuel_injecte", "Cumul mensuel injecté (kWh)"),
    ("cumul_mensuel_injecte_eur", "Cumul mensuel injecté (EUR)"),
]

RECAP_TECHNICAL_KEYS = [key for key, _ in RECAP_COLUMNS]
RECAP_FRENCH_LABELS = [label for _, label in RECAP_COLUMNS]


def _interval_readings(readings: list[dict]) -> list[dict]:
    """Conserve uniquement les enregistrements d'intervalle (RawDataPeriod = Minute)."""
    return [
        r
        for r in readings
        if (r.get("raw_data_period") or "").strip().casefold() == "minute"
        and r.get("data_time_local") is not None
    ]


def aggregate_quarterly(readings: list[dict]) -> dict[tuple, dict]:
    """Applique la règle de précédence par (site, EAN, quart d'heure, direction).

    Retourne `{(site, ean, quart_local): {'withdrawn_milli': int, 'injected_milli': int}}`.
    """
    buckets: dict[tuple, dict] = defaultdict(
        lambda: {
            "withdrawal": {"totals": [], "rates": []},
            "injection": {"totals": [], "rates": []},
        }
    )
    for r in _interval_readings(readings):
        key = (r["site_name"], r["ean_number"], r["data_time_local"])
        direction = r["direction"]
        value = r["value_kwh_milli"]
        if value is None:
            continue
        if is_totals(r.get("variable_name")):
            buckets[key][direction]["totals"].append(value)
        else:
            buckets[key][direction]["rates"].append(value)

    result: dict[tuple, dict] = {}
    for key, dirs in buckets.items():
        result[key] = {
            "withdrawn_milli": _precedence(dirs["withdrawal"]),
            "injected_milli": _precedence(dirs["injection"]),
        }
    return result


def _precedence(register: dict) -> int:
    totals = register["totals"]
    rates = register["rates"]
    if totals:
        return sum(totals)
    return sum(rates)


def aggregate_hourly(quarterly: dict[tuple, dict]) -> dict[tuple, dict]:
    """Somme les quarts d'heure par (site, EAN, heure locale de début)."""
    hour_buckets: dict[tuple, dict] = defaultdict(
        lambda: {"withdrawn_milli": 0, "injected_milli": 0, "quarters": set()}
    )
    for (site, ean, ts), values in quarterly.items():
        hour = floor_to_hour(ts)
        key = (site, ean, hour)
        hour_buckets[key]["withdrawn_milli"] += values["withdrawn_milli"]
        hour_buckets[key]["injected_milli"] += values["injected_milli"]
        hour_buckets[key]["quarters"].add(ts)

    result: dict[tuple, dict] = {}
    for key, b in hour_buckets.items():
        count = len(b["quarters"])
        result[key] = {
            "site_name": key[0],
            "ean_number": key[1],
            "timestamp_local": key[2],
            "withdrawn_kwh_milli": b["withdrawn_milli"],
            "injected_kwh_milli": b["injected_milli"],
            "balance_withdrawn_minus_injected_kwh_milli": b["withdrawn_milli"] - b["injected_milli"],
            "energy_point_count": count,
            "energy_complete": count == QUARTERS_PER_HOUR,
        }
    return result


def price_index_by_hour(prices: list[dict]) -> dict[datetime, list[int]]:
    """Indexe les prix transformés (micro) par heure locale de début."""
    index: dict[datetime, list[int]] = defaultdict(list)
    for p in prices:
        index[floor_to_hour(p["timestamp_local"])].append(p["price_eur_kwh_transformed_micro"])
    return index


def build_recap_rows(
    hourly: dict[tuple, dict],
    price_index: dict[datetime, list[int]],
    allow_incomplete_price: bool = False,
) -> list[dict]:
    """Construit les 21 colonnes de la vue `recap_hourly` (triées, cumuls calculés)."""
    sorted_keys = sorted(hourly.keys(), key=lambda k: (k[0] or "", k[1] or "", k[2]))

    global_cumul: dict[tuple, dict] = defaultdict(
        lambda: {"net": 0, "withdrawn": 0, "injected": 0, "eur": 0}
    )
    monthly_cumul: dict[tuple, dict] = defaultdict(
        lambda: {"withdrawn": 0, "injected": 0, "eur": 0}
    )

    rows: list[dict] = []
    for key in sorted_keys:
        h = hourly[key]
        ts = h["timestamp_local"]
        site_ean = (h["site_name"], h["ean_number"])
        month_key = ts.strftime("%Y-%m")

        hourly_price = build_hourly_price(price_index.get(ts, []), allow_incomplete_price)
        official_micro = hourly_price.official_micro
        injected_value_micro = (
            mul_milli_micro(h["injected_kwh_milli"], official_micro)
            if official_micro is not None
            else None
        )

        # Cumuls globaux (partitions site/EAN).
        gc = global_cumul[site_ean]
        gc["withdrawn"] += h["withdrawn_kwh_milli"]
        gc["injected"] += h["injected_kwh_milli"]
        gc["net"] += h["injected_kwh_milli"] - h["withdrawn_kwh_milli"]
        if injected_value_micro is not None:
            gc["eur"] += injected_value_micro

        # Cumuls mensuels (remis à zéro au changement de mois).
        if monthly_cumul[site_ean].get("month") != month_key:
            monthly_cumul[site_ean] = {"month": month_key, "withdrawn": 0, "injected": 0, "eur": 0}
        mc = monthly_cumul[site_ean]
        mc["withdrawn"] += h["withdrawn_kwh_milli"]
        mc["injected"] += h["injected_kwh_milli"]
        if injected_value_micro is not None:
            mc["eur"] += injected_value_micro

        prelevee = milli_to_kwh(h["withdrawn_kwh_milli"])
        injectee = milli_to_kwh(h["injected_kwh_milli"])
        solde = milli_to_kwh(h["balance_withdrawn_minus_injected_kwh_milli"])
        prix = micro_to_eur(official_micro) if official_micro is not None else None
        injecte_eur = micro_to_eur(injected_value_micro) if injected_value_micro is not None else None

        rows.append(
            {
                "date_heure": ts,
                "prelevee_kwh": prelevee,
                "injectee_kwh": injectee,
                "solde_prel_inj": solde,
                "label_heure": _label_heure(ts),
                "cumul_net_kwh": milli_to_kwh(gc["net"]),
                "cumul_prelevee": milli_to_kwh(gc["withdrawn"]),
                "cumul_injectee": milli_to_kwh(gc["injected"]),
                "prelevee_kwh_copie": prelevee,
                "injectee_kwh_copie": injectee,
                "cumul_net_copie": milli_to_kwh(gc["net"]),
                "cumul_prelevee_copie": milli_to_kwh(gc["withdrawn"]),
                "cumul_injectee_copie": milli_to_kwh(gc["injected"]),
                "label_axe_x": _label_axe_x(ts),
                "cumul_injecte_eur": micro_to_eur(gc["eur"]),
                "cle_prix": _price_key(ts),
                "prix_horaire_eur_kwh": prix,
                "injecte_eur": injecte_eur,
                "cumul_mensuel_preleve": milli_to_kwh(mc["withdrawn"]),
                "cumul_mensuel_injecte": milli_to_kwh(mc["injected"]),
                "cumul_mensuel_injecte_eur": micro_to_eur(mc["eur"]),
                # Métadonnées internes (non exportées telles quelles).
                "site_name": h["site_name"],
                "ean_number": h["ean_number"],
                "energy_point_count": h["energy_point_count"],
                "energy_complete": h["energy_complete"],
                "price_point_count": hourly_price.point_count,
                "price_complete": hourly_price.complete,
            }
        )
    return rows


def build_hourly_records(
    hourly: dict[tuple, dict],
    price_index: dict[datetime, list[int]],
    allow_incomplete_price: bool = False,
) -> list[dict]:
    """Construit les enregistrements à persister dans `energy_hourly`."""
    records = []
    for _, h in sorted(
        hourly.items(), key=lambda item: (item[0][0] or "", item[0][1] or "", item[0][2])
    ):
        ts = h["timestamp_local"]
        hourly_price = build_hourly_price(price_index.get(ts, []), allow_incomplete_price)
        official_micro = hourly_price.official_micro
        injected_value_micro = (
            mul_milli_micro(h["injected_kwh_milli"], official_micro)
            if official_micro is not None
            else None
        )
        records.append(
            {
                "timestamp_local": ts,
                "timestamp_utc": _local_to_utc_naive(ts),
                "site_name": h["site_name"],
                "ean_number": h["ean_number"],
                "withdrawn_kwh_milli": h["withdrawn_kwh_milli"],
                "injected_kwh_milli": h["injected_kwh_milli"],
                "balance_withdrawn_minus_injected_kwh_milli": h["balance_withdrawn_minus_injected_kwh_milli"],
                "spot_price_eur_kwh_micro": official_micro,
                "injected_value_eur_micro": injected_value_micro,
                "energy_point_count": h["energy_point_count"],
                "price_point_count": hourly_price.point_count,
                "energy_complete": h["energy_complete"],
                "price_complete": hourly_price.complete,
            }
        )
    return records


def build_monthly_records(hourly_records: list[dict]) -> list[dict]:
    """Agrège les flux horaires en totaux mensuels (somme des flux, pas des cumuls)."""
    grouped: dict[tuple, dict] = defaultdict(
        lambda: {
            "withdrawn": 0,
            "injected": 0,
            "eur": 0,
            "price_sum": 0,
            "price_count": 0,
            "negative_price_hours": 0,
            "missing_energy": 0,
            "missing_price": 0,
        }
    )
    for h in hourly_records:
        month = h["timestamp_local"].strftime("%Y-%m") + "-01"
        key = (h["site_name"], h["ean_number"], month)
        g = grouped[key]
        g["withdrawn"] += h["withdrawn_kwh_milli"]
        g["injected"] += h["injected_kwh_milli"]
        if h["injected_value_eur_micro"] is not None:
            g["eur"] += h["injected_value_eur_micro"]
        if not h["energy_complete"]:
            g["missing_energy"] += 1
        if h["spot_price_eur_kwh_micro"] is None:
            g["missing_price"] += 1
        else:
            g["price_sum"] += h["spot_price_eur_kwh_micro"]
            g["price_count"] += 1
            if h["spot_price_eur_kwh_micro"] < 0:
                g["negative_price_hours"] += 1

    records = []
    for (site, ean, month), g in sorted(grouped.items()):
        avg_price = (
            int(round(g["price_sum"] / g["price_count"])) if g["price_count"] else None
        )
        records.append(
            {
                "month": month,
                "site_name": site,
                "ean_number": ean,
                "withdrawn_kwh_milli": g["withdrawn"],
                "injected_kwh_milli": g["injected"],
                "net_injected_minus_withdrawn_kwh_milli": g["injected"] - g["withdrawn"],
                "injected_value_eur_micro": g["eur"],
                "average_spot_price_eur_kwh_micro": avg_price,
                "negative_price_hours": g["negative_price_hours"],
                "hours_with_missing_energy": g["missing_energy"],
                "hours_with_missing_price": g["missing_price"],
            }
        )
    return records


def _local_to_utc_naive(ts: datetime) -> datetime:
    """Convertit une heure locale (naïve Europe/Brussels) en UTC naïf."""
    if ts.tzinfo is None:
        from app.config import get_settings

        ts = ts.replace(tzinfo=ZoneInfo(get_settings().timezone))
    return ts.astimezone(UTC).replace(tzinfo=None)


def _label_heure(ts: datetime) -> str:
    return f"{ts.day}/{ts.month} {ts.hour}h"


def _label_axe_x(ts: datetime) -> str:
    if ts.hour == 0:
        return f"{ts.day}/{ts.month}\n{ts.hour}h"
    return f"{ts.hour}h"


def _price_key(ts: datetime) -> str:
    return f"{ts:%d/%m/%Y}|{ts.hour}u00"
