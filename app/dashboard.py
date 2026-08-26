"""Tableau de bord Streamlit : graphiques clés et synthèse mensuelle."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.config import Settings, get_settings
from app.db import get_session
from app.models import SpotPriceQuarterHourly
from app.repositories import aggregates as aggregates_repo
from app.services.aggregation import build_recap_rows, price_index_by_hour
from app.services.auth import is_ean_authorized
from app.services.importer import import_ores_workbook

st.set_page_config(page_title="Suivi énergétique ORES", layout="wide")


@st.cache_data(ttl=60)
def load_hourly_df() -> pd.DataFrame:
    """Charge le récap horaire complet (cumuls corrects) dans un DataFrame."""
    settings = get_settings()
    session = get_session()
    try:
        hourly_orm = aggregates_repo.get_hourly(session)
        hourly = {
            (h.site_name, h.ean_number, h.timestamp_local): {
                "site_name": h.site_name,
                "ean_number": h.ean_number,
                "timestamp_local": h.timestamp_local,
                "withdrawn_kwh_milli": h.withdrawn_kwh_milli,
                "injected_kwh_milli": h.injected_kwh_milli,
                "balance_withdrawn_minus_injected_kwh_milli": h.balance_withdrawn_minus_injected_kwh_milli,
                "energy_point_count": h.energy_point_count,
                "energy_complete": h.energy_complete,
            }
            for h in hourly_orm
        }
        prices = (
            session.query(SpotPriceQuarterHourly)
            .order_by(SpotPriceQuarterHourly.timestamp_utc)
            .all()
        )
        price_index = price_index_by_hour(
            [
                {
                    "timestamp_local": p.timestamp_local,
                    "price_eur_kwh_transformed_micro": p.price_eur_kwh_transformed_micro,
                }
                for p in prices
            ]
        )
        rows = build_recap_rows(hourly, price_index, settings.allow_incomplete_price)
    finally:
        session.close()

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in (
        "prelevee_kwh",
        "injectee_kwh",
        "solde_prel_inj",
        "cumul_net_kwh",
        "cumul_prelevee",
        "cumul_injectee",
        "cumul_injecte_eur",
        "prix_horaire_eur_kwh",
        "injecte_eur",
        "cumul_mensuel_preleve",
        "cumul_mensuel_injecte",
        "cumul_mensuel_injecte_eur",
    ):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date_heure"] = pd.to_datetime(df["date_heure"])
    df["mois"] = df["date_heure"].dt.to_period("M").astype(str)
    return df


@st.cache_data(ttl=60)
def load_monthly_df() -> pd.DataFrame:
    session = get_session()
    try:
        records = aggregates_repo.get_monthly(session)
    finally:
        session.close()
    rows = []
    for m in records:
        rows.append(
            {
                "month": m.month,
                "site_name": m.site_name,
                "ean_number": m.ean_number,
                "withdrawn_kwh": m.withdrawn_kwh_milli / 1000,
                "injected_kwh": m.injected_kwh_milli / 1000,
                "net_inj_minus_withdrawn_kwh": m.net_injected_minus_withdrawn_kwh_milli / 1000,
                "injected_value_eur": m.injected_value_eur_micro / 1_000_000,
                "average_price_eur_kwh": (
                    m.average_spot_price_eur_kwh_micro / 1_000_000
                    if m.average_spot_price_eur_kwh_micro is not None
                    else None
                ),
                "negative_price_hours": m.negative_price_hours,
                "hours_missing_energy": m.hours_with_missing_energy,
                "hours_missing_price": m.hours_with_missing_price,
            }
        )
    return pd.DataFrame(rows)


def _auth_gate(settings: Settings) -> None:
    """Bloque l'application tant que l'EAN saisi n'est pas autorisé."""
    if not settings.authorized_ean_list:
        return  # Authentification désactivée.
    if st.session_state.get("authorized", False):
        return

    st.title("Accès restreint")
    st.caption("Saisissez un numéro EAN autorisé pour accéder à l'application.")
    with st.form("auth_form"):
        ean = st.text_input("Numéro EAN")
        submitted = st.form_submit_button("Se connecter")
    if submitted:
        if is_ean_authorized(ean, settings):
            st.session_state["authorized"] = True
            st.session_state["authorized_ean"] = (ean or "").strip()
            st.rerun()
        else:
            st.error("EAN non autorisé.")
    st.stop()


def _render_import_tab(settings: Settings) -> None:
    """Onglet de chargement d'un nouveau fichier ORES."""
    st.subheader("Charger un nouveau fichier ORES")
    st.caption(
        "Le chargement déclenche l'import, la récupération des prix Elexys si nécessaire, "
        "la mise à jour des agrégats puis la validation de cohérence."
    )
    uploaded = st.file_uploader("Classeur ORES (.xlsx / .xlsm)", type=["xlsx", "xlsm"])
    sheet_name = st.text_input("Feuille à importer", value="Data")

    if uploaded is not None and st.button("Charger le fichier", type="primary"):
        suffix = Path(uploaded.name).suffix or ".xlsx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded.getvalue())
            target = tmp.name
        try:
            with st.spinner("Import en cours (fichier, prix, agrégats, validation)…"):
                result = import_ores_workbook(target, sheet_name=sheet_name, settings=settings)
        except Exception as exc:  # noqa: BLE001 - message utilisateur
            st.error(f"FAILED — {exc}")
        else:
            if result.get("status") == "ok":
                load_hourly_df.clear()
                load_monthly_df.clear()
                st.session_state["import_success"] = True
                st.session_state["import_result"] = result
                st.rerun()
            else:
                st.error("FAILED — l'opération n'a pas abouti (voir détails).")
                with st.expander("Détails de l'opération"):
                    st.json(result)
        finally:
            Path(target).unlink(missing_ok=True)


def main() -> None:
    settings = get_settings()
    _auth_gate(settings)

    st.title("Suivi énergétique ORES / Elexys")

    if st.session_state.get("import_success"):
        st.success("SUCCESSFULL — import, prix, agrégats et validation terminés.")
        result = st.session_state.get("import_result")
        if result:
            with st.expander("Détails de l'opération"):
                st.json(result)
        st.session_state["import_success"] = False
        st.session_state["import_result"] = None

    hourly = load_hourly_df()
    monthly = load_monthly_df()

    tab_recap, tab_monthly, tab_import = st.tabs(
        ["Récap horaire", "Synthèse mensuelle", "Importer un fichier ORES"]
    )

    with tab_import:
        _render_import_tab(settings)

    if hourly.empty:
        with tab_recap:
            st.info(
                "Aucune donnée. Importez d'abord un fichier ORES via l'onglet "
                "« Importer un fichier ORES »."
            )
        return

    sites = sorted(hourly["site_name"].dropna().unique().tolist())
    selected_site = st.sidebar.selectbox("Site", ["Tous"] + sites)
    eans = sorted(hourly["ean_number"].dropna().unique().tolist())
    selected_ean = st.sidebar.selectbox("EAN", ["Tous"] + eans)

    min_date = hourly["date_heure"].min().date()
    max_date = hourly["date_heure"].max().date()
    date_range = st.sidebar.date_input(
        "Plage de dates", value=(min_date, max_date), min_value=min_date, max_value=max_date
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date, end_date = min_date, max_date

    months = sorted(hourly["mois"].unique().tolist())
    selected_month = st.sidebar.selectbox("Mois", ["Tous"] + months)

    # Filtrage.
    df = hourly[
        (hourly["date_heure"] >= pd.Timestamp(start_date))
        & (hourly["date_heure"] <= pd.Timestamp(end_date) + pd.Timedelta(hours=23))
    ]
    if selected_site != "Tous":
        df = df[df["site_name"] == selected_site]
    if selected_ean != "Tous":
        df = df[df["ean_number"] == selected_ean]

    with tab_recap:
        st.subheader("1. Courbes horaires prélèvement / injection")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["date_heure"], y=df["prelevee_kwh"], name="Prélevée (kWh)", mode="lines"))
        fig.add_trace(go.Scatter(x=df["date_heure"], y=df["injectee_kwh"], name="Injectée (kWh)", mode="lines"))
        fig.update_layout(height=380, xaxis_title="Heure", yaxis_title="kWh")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("2. Énergie cumulée")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["date_heure"], y=df["cumul_prelevee"], name="Cumul prélevé", mode="lines"))
        fig.add_trace(go.Scatter(x=df["date_heure"], y=df["cumul_injectee"], name="Cumul injecté", mode="lines"))
        fig.add_trace(go.Scatter(x=df["date_heure"], y=df["cumul_net_kwh"], name="Cumul net", mode="lines"))
        fig.update_layout(height=380, xaxis_title="Heure", yaxis_title="kWh")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("5. Prix de rachat et injection")
        fig = go.Figure()

        buyback = df["prix_horaire_eur_kwh"]
        neg_y = buyback.where(buyback < 0)
        fig.add_trace(
            go.Scatter(
                x=df["date_heure"], y=df["prix_horaire_eur_kwh"],
                name="Prix de rachat (€/kWh)", mode="lines",
                line=dict(color="#2ca02c"),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df["date_heure"], y=neg_y,
                name="Prix de rachat < 0", mode="lines",
                line=dict(color="red"), showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df["date_heure"], y=df["injectee_kwh"],
                name="Injection (kWh)", mode="lines", yaxis="y2",
                line=dict(color="#ADD8E6"),
            )
        )
        fig.add_hline(y=0, line=dict(color="black", width=2))
        fig.update_layout(
            height=380,
            yaxis=dict(title="€/kWh"),
            yaxis2=dict(title="kWh", overlaying="y", side="right"),
        )
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("6. Profil moyen par heure")
        profil = df.groupby(df["date_heure"].dt.hour)[["prelevee_kwh", "injectee_kwh"]].mean()
        fig = go.Figure()
        fig.add_trace(go.Bar(x=profil.index, y=profil["prelevee_kwh"], name="Prélevée moyenne"))
        fig.add_trace(go.Bar(x=profil.index, y=profil["injectee_kwh"], name="Injectée moyenne"))
        fig.update_layout(height=380, xaxis_title="Heure (0-23)", yaxis_title="kWh", barmode="group")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Données horaires")
        show = df[
            [
                "date_heure", "prelevee_kwh", "injectee_kwh", "solde_prel_inj",
                "prix_horaire_eur_kwh", "injecte_eur", "energy_point_count", "price_point_count",
            ]
        ].copy()
        show = show.rename(
            columns={
                "date_heure": "Date-Heure",
                "prelevee_kwh": "Prélevée (kWh)",
                "injectee_kwh": "Injectée (kWh)",
                "solde_prel_inj": "Solde (Prél-Inj)",
                "prix_horaire_eur_kwh": "Prix de rachat (€/kWh)",
                "injecte_eur": "Injecté (EUR)",
                "energy_point_count": "Points énergie",
                "price_point_count": "Points prix",
            }
        )
        st.dataframe(show, use_container_width=True)

    with tab_monthly:
        st.subheader("Synthèse mensuelle")

        mdf = monthly
        if selected_site != "Tous":
            mdf = mdf[mdf["site_name"] == selected_site]
        if selected_ean != "Tous":
            mdf = mdf[mdf["ean_number"] == selected_ean]
        if selected_month != "Tous":
            mdf = mdf[mdf["month"] == selected_month + "-01"]

        if not mdf.empty:
            total_w = mdf["withdrawn_kwh"].sum()
            total_i = mdf["injected_kwh"].sum()
            total_v = mdf["injected_value_eur"].sum()
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Prélèvement (kWh)", f"{total_w:,.3f}")
            c2.metric("Injection (kWh)", f"{total_i:,.3f}")
            c3.metric("Solde net (kWh)", f"{total_i - total_w:,.3f}")
            c4.metric("Valeur injectée (€)", f"{total_v:,.2f}")
            avg = mdf["average_price_eur_kwh"].mean()
            c5.metric("Prix moyen (€/kWh)", f"{avg:.6f}" if pd.notna(avg) else "—")

            if selected_month != "Tous":
                prev = monthly[monthly["month"] == (pd.Period(selected_month, freq="M") - 1).strftime("%Y-%m") + "-01"]
                if not prev.empty:
                    delta_w = total_w - prev["withdrawn_kwh"].sum()
                    st.caption(
                        f"vs mois précédent : prélèvement {delta_w:+,.3f} kWh "
                        f"({delta_w / prev['withdrawn_kwh'].sum() * 100:+.1f} %)"
                        if prev["withdrawn_kwh"].sum() else "vs mois précédent : non calculable"
                    )

            st.dataframe(mdf, use_container_width=True)

        st.subheader("3. Énergie mensuelle")
        m_all = monthly
        if selected_site != "Tous":
            m_all = m_all[m_all["site_name"] == selected_site]
        if selected_ean != "Tous":
            m_all = m_all[m_all["ean_number"] == selected_ean]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=m_all["month"], y=m_all["withdrawn_kwh"], name="Prélevé"))
        fig.add_trace(go.Bar(x=m_all["month"], y=m_all["injected_kwh"], name="Injecté"))
        fig.update_layout(height=380, barmode="group", xaxis_title="Mois", yaxis_title="kWh")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("4. Valeur de l'injection")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=m_all["month"], y=m_all["injected_value_eur"], name="Valeur injectée (€)"))
        fig.update_layout(height=380, xaxis_title="Mois", yaxis_title="EUR")
        st.plotly_chart(fig, use_container_width=True)


if __name__ == "__main__":
    main()
