"""Sélection, validation et bascule de la formule de calcul du prix d'injection.

Trois formules sont proposées (Engie, Bolt, Octa+). Changer de formule
recalcule immédiatement tous les agrégats (`energy_hourly`, `monthly_totals`)
mais est refusé si les données nécessaires (prix Elexys ou prix EPEX SPP
mensuel) sont incomplètes pour la période déjà importée : la base n'est alors
pas modifiée.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.config import Settings
from app.domain.pricing import PRICING_FORMULAS, PricingFormulaDef, resolve_formula
from app.domain.units import eur_to_micro
from app.logging_conf import get_logger
from app.repositories import aggregates as aggregates_repo
from app.repositories import meta
from app.repositories import prices as prices_repo

logger = get_logger("pricing_formula")

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_MONTH_FIRST_DAY_RE = re.compile(r"^\d{4}-\d{2}-01$")


def list_formulas(session, settings: Settings) -> list[dict]:
    """Retourne les formules disponibles (avec la formule active marquée)."""
    active_key = meta.get_active_formula_key(session)
    return [
        {
            "key": f.key,
            "label": f.label,
            "description": f.description,
            "requires": f.requires,
            "active": f.key == active_key,
        }
        for f in PRICING_FORMULAS.values()
    ]


def get_active_formula(session, settings: Settings) -> PricingFormulaDef:
    """Retourne la définition de la formule actuellement active."""
    return resolve_formula(meta.get_active_formula_key(session), settings)


def validate_formula_inputs(session, formula: PricingFormulaDef) -> dict:
    """Vérifie que les données nécessaires à `formula` sont disponibles.

    Ne bloque jamais s'il n'y a encore aucune donnée horaire importée (rien à
    recalculer). Sinon, exige un prix EPEX SPP mensuel pour chaque mois
    couvert (Octa+) ou au moins un prix Elexys enregistré (Engie/Bolt).
    """
    months = aggregates_repo.get_distinct_months(session)
    if not months:
        return {"ok": True, "missing_months": [], "message": "Aucune donnée horaire à recalculer."}

    if formula.requires == "epex_monthly":
        available = set(prices_repo.get_epex_monthly_index(session).keys())
        missing = sorted(m for m in months if m not in available)
        if missing:
            return {
                "ok": False,
                "missing_months": missing,
                "message": (
                    "Prix EPEX SPP mensuel manquant pour : " + ", ".join(missing)
                    + ". Encodez-le avant de changer de formule."
                ),
            }
        return {"ok": True, "missing_months": [], "message": "OK"}

    if prices_repo.count_prices(session) == 0:
        return {
            "ok": False,
            "missing_months": months,
            "message": "Aucun prix Elexys disponible : synchronisez les prix avant de changer de formule.",
        }
    return {"ok": True, "missing_months": [], "message": "OK"}


def switch_formula(session, settings: Settings, formula_key: str) -> dict:
    """Change la formule active et reconstruit tous les agrégats.

    Lève `ValueError` (base non modifiée) si la formule est inconnue ou si des
    données requises sont manquantes.
    """
    if formula_key not in PRICING_FORMULAS:
        raise ValueError(f"Formule de prix inconnue : {formula_key!r}")

    formula = resolve_formula(formula_key, settings)
    validation = validate_formula_inputs(session, formula)
    if not validation["ok"]:
        raise ValueError(validation["message"])

    if formula.requires == "elexys_quarter_hourly":
        # Les prix Elexys quart-horaires bruts sont conservés ; seule leur
        # transformation (a, b) change avec la nouvelle formule.
        prices_repo.retransform_all(session, formula.a, formula.b)

    meta.set_active_formula_key(session, formula_key)

    from app.services.importer import rebuild_aggregates  # import tardif : évite un cycle

    result = rebuild_aggregates(session, settings)
    session.flush()
    logger.info("Formule de prix changée", extra={"formula": formula_key, **result})
    return {"formula": formula_key, "rebuild": result}


def _normalize_month(month: str) -> str:
    month = (month or "").strip()
    if _MONTH_RE.fullmatch(month):
        return f"{month}-01"
    if _MONTH_FIRST_DAY_RE.fullmatch(month):
        return month
    raise ValueError(f"Mois invalide (attendu YYYY-MM) : {month!r}")


def set_epex_monthly_price(session, month: str, price_eur_mwh: Decimal | float | str) -> dict:
    """Encode le prix EPEX SPP mensuel (mois au format `YYYY-MM` ou `YYYY-MM-01`)."""
    normalized_month = _normalize_month(month)
    micro = eur_to_micro(price_eur_mwh)
    prices_repo.upsert_epex_monthly_price(session, normalized_month, micro)
    session.flush()
    logger.info("Prix EPEX SPP mensuel enregistré", extra={"month": normalized_month})
    return {"month": normalized_month, "price_eur_mwh": str(price_eur_mwh)}
