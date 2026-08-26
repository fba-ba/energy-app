"""Vue SQL `recap_hourly` reproduisant les règles de calcul de la feuille `Récap`.

La vue expose des valeurs lisibles (kWh, €) obtenues par division des colonnes
entières (milli/micro) ; le stockage de référence reste celui des tables
(`energy_hourly`, `monthly_totals`), exact en unités entières.
"""

from __future__ import annotations

from sqlalchemy.engine import Engine

RECAP_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS recap_hourly AS
SELECT
    timestamp_local AS date_heure,
    withdrawn_kwh_milli / 1000.0 AS prelevee_kwh,
    injected_kwh_milli / 1000.0 AS injectee_kwh,
    balance_withdrawn_minus_injected_kwh_milli / 1000.0 AS solde_prel_inj,
    CAST(strftime('%d', timestamp_local) AS INTEGER) || '/' ||
        CAST(strftime('%m', timestamp_local) AS INTEGER) || ' ' ||
        CAST(strftime('%H', timestamp_local) AS INTEGER) || 'h' AS label_heure,
    SUM(injected_kwh_milli - withdrawn_kwh_milli) OVER w / 1000.0 AS cumul_net_kwh,
    SUM(withdrawn_kwh_milli) OVER w / 1000.0 AS cumul_prelevee,
    SUM(injected_kwh_milli) OVER w / 1000.0 AS cumul_injectee,
    withdrawn_kwh_milli / 1000.0 AS prelevee_kwh_copie,
    injected_kwh_milli / 1000.0 AS injectee_kwh_copie,
    SUM(injected_kwh_milli - withdrawn_kwh_milli) OVER w / 1000.0 AS cumul_net_copie,
    SUM(withdrawn_kwh_milli) OVER w / 1000.0 AS cumul_prelevee_copie,
    SUM(injected_kwh_milli) OVER w / 1000.0 AS cumul_injectee_copie,
    CASE
        WHEN CAST(strftime('%H', timestamp_local) AS INTEGER) = 0
        THEN CAST(strftime('%d', timestamp_local) AS INTEGER) || '/' ||
             CAST(strftime('%m', timestamp_local) AS INTEGER) || char(10) || '0h'
        ELSE CAST(strftime('%H', timestamp_local) AS INTEGER) || 'h'
    END AS label_axe_x,
    SUM(COALESCE(injected_value_eur_micro, 0)) OVER w / 1000000.0 AS cumul_injecte_eur,
    strftime('%d/%m/%Y|', timestamp_local) ||
        CAST(strftime('%H', timestamp_local) AS INTEGER) || 'u00' AS cle_prix,
    spot_price_eur_kwh_micro / 1000000.0 AS prix_horaire_eur_kwh,
    injected_value_eur_micro / 1000000.0 AS injecte_eur,
    SUM(withdrawn_kwh_milli) OVER m / 1000.0 AS cumul_mensuel_preleve,
    SUM(injected_kwh_milli) OVER m / 1000.0 AS cumul_mensuel_injecte,
    SUM(COALESCE(injected_value_eur_micro, 0)) OVER m / 1000000.0 AS cumul_mensuel_injecte_eur,
    site_name,
    ean_number,
    energy_point_count,
    price_point_count,
    energy_complete,
    price_complete
FROM energy_hourly
WINDOW
    w AS (PARTITION BY site_name, ean_number ORDER BY timestamp_utc),
    m AS (PARTITION BY site_name, ean_number, strftime('%Y-%m', timestamp_local) ORDER BY timestamp_utc);
"""


def create_recap_view(engine: Engine) -> None:
    """Crée la vue `recap_hourly` (idempotent)."""
    with engine.begin() as conn:
        conn.exec_driver_sql(RECAP_VIEW_SQL)
