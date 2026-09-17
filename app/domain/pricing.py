"""Transformation et agrégation des prix spot Elexys."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.domain.units import EUR_SCALE, to_decimal

# Nombre attendu de quarts d'heure par heure.
QUARTERS_PER_HOUR = 4


def transform_price_eur_kwh(
    price_eur_mwh: object,
    a: Decimal = Decimal("-17.3"),
    b: Decimal = Decimal("0.3"),
) -> Decimal:
    """Applique la formule du classeur : prix_kwh = (a + b × prix_mwh) / 1000."""
    raw = to_decimal(price_eur_mwh)
    return (a + b * raw) / Decimal(1000)


def transform_price_to_micro(
    price_eur_mwh: object,
    a: Decimal = Decimal("-17.3"),
    b: Decimal = Decimal("0.3"),
) -> int:
    """Prix Elexys (€/MWh) -> prix transformé (€/kWh) en millionièmes d'euro."""
    eur_kwh = transform_price_eur_kwh(price_eur_mwh, a, b)
    return int((eur_kwh * EUR_SCALE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class HourlyPrice:
    """Prix horaire calculé à partir des quarts d'heure transformés.

    `official_micro` est `None` si l'heure est incomplète et que la tolérance
    est désactivée ; `average_available_micro` conserve la moyenne disponible.
    """

    point_count: int
    complete: bool
    official_micro: int | None
    average_available_micro: int | None


def build_hourly_price(
    quarter_micros: list[int],
    allow_incomplete: bool = False,
) -> HourlyPrice:
    """Moyenne arithmétique des prix quart-horaires transformés (en micro-euros).

    - 4 quarts d'heure -> prix officiel = moyenne, `complete = True`.
    - Moins de 4 -> moyenne disponible dans `average_available_micro`,
      `complete = False`, et `official_micro = None` sauf tolérance explicite.
    - Aucun quart d'heure -> tout à `None`, `point_count = 0`.
    """
    count = len(quarter_micros)
    if count == 0:
        return HourlyPrice(point_count=0, complete=False, official_micro=None, average_available_micro=None)

    total = sum(Decimal(m) for m in quarter_micros)
    average = int((total / Decimal(count)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    complete = count == QUARTERS_PER_HOUR
    official = average if (complete or allow_incomplete) else None
    return HourlyPrice(
        point_count=count,
        complete=complete,
        official_micro=official,
        average_available_micro=average,
    )


@dataclass(frozen=True)
class PricingFormulaDef:
    """Définition d'une formule de calcul du prix d'injection.

    `requires` indique la source de données nécessaire :
    - `"elexys_quarter_hourly"` : prix Elexys quart-horaire, transformé puis moyenné par heure ;
    - `"monthly_index"` : indice (`index_key`) saisi manuellement une fois par
      mois, transformé et appliqué de façon constante à toutes les heures du mois.
    """

    key: str
    label: str
    requires: str
    a: Decimal
    b: Decimal
    description: str
    # Renseignés uniquement quand `requires == "monthly_index"" : indice mensuel
    # saisi manuellement (clé technique, libellé et lien de référence).
    index_key: str | None = None
    index_label: str | None = None
    index_source_url: str | None = None


# Registre des formules disponibles (clé -> définition). L'ordre est celui
# proposé dans les listes déroulantes de l'interface et de l'API.
PRICING_FORMULAS: dict[str, PricingFormulaDef] = {
    "engie": PricingFormulaDef(
        key="engie",
        label="Engie",
        requires="elexys_quarter_hourly",
        a=Decimal("-17.3"),
        b=Decimal("0.3"),
        description="(-17,3 + 0,3 × prix Elexys €/MWh) / 1000",
    ),
    "bolt": PricingFormulaDef(
        key="bolt",
        label="Bolt",
        requires="elexys_quarter_hourly",
        a=Decimal("-20"),
        b=Decimal("1"),
        description="(-20 + 1 × prix Elexys €/MWh) / 1000",
    ),
    "octa_plus": PricingFormulaDef(
        key="octa_plus",
        label="Octa+",
        requires="monthly_index",
        a=Decimal("-13.89"),
        b=Decimal("0.852"),
        description="(EPEX SPP mensuel × 0,852 − 13,89 €/MWh) / 1000",
        index_key="epex_spp",
        index_label="EPEX SPP",
    ),
    "total_energie": PricingFormulaDef(
        key="total_energie",
        label="TotalEnergie",
        requires="monthly_index",
        a=Decimal("-0.625"),
        b=Decimal("0.0235"),
        description="(BELPEXM mensuel × 0,0235 − 0,625 €/MWh) / 1000",
        index_key="belpexm",
        index_label="BELPEXM",
        index_source_url="https://www.mega.be/fr/energie/indexation-de-nos-produits-variables",
    ),
}

DEFAULT_FORMULA_KEY = "engie"


def resolve_formula(key: str, settings: Any = None) -> PricingFormulaDef:
    """Retourne la définition de la formule `key`.

    Pour « Engie », les paramètres `a`/`b` peuvent être surchargés par la
    configuration (`PRICE_TRANSFORM_A` / `PRICE_TRANSFORM_B`), ce qui conserve
    la rétrocompatibilité avec le comportement historique de l'application.
    """
    if key not in PRICING_FORMULAS:
        raise ValueError(f"Formule de prix inconnue : {key!r}")
    formula = PRICING_FORMULAS[key]
    if key == "engie" and settings is not None:
        formula = PricingFormulaDef(
            key=formula.key,
            label=formula.label,
            requires=formula.requires,
            a=Decimal(settings.price_transform_a),
            b=Decimal(settings.price_transform_b),
            description=formula.description,
        )
    return formula


def transform_raw_mwh_micro_to_kwh_micro(raw_mwh_micro: int, a: Decimal, b: Decimal) -> int:
    """Prix brut (millionièmes d'€/MWh) -> prix transformé (millionièmes d'€/kWh)."""
    raw_mwh = Decimal(raw_mwh_micro) / EUR_SCALE
    return transform_price_to_micro(raw_mwh, a, b)


def build_hourly_price_from_monthly(
    index_mwh_micro: int | None,
    formula: PricingFormulaDef,
) -> HourlyPrice:
    """Prix horaire dérivé d'un indice mensuel unique (formules Octa+, TotalEnergie...).

    Constant sur tout le mois. `None` si l'indice mensuel requis est manquant
    (jamais remplacé par zéro).
    """
    if index_mwh_micro is None:
        return HourlyPrice(point_count=0, complete=False, official_micro=None, average_available_micro=None)
    micro = transform_raw_mwh_micro_to_kwh_micro(index_mwh_micro, formula.a, formula.b)
    return HourlyPrice(point_count=1, complete=True, official_micro=micro, average_available_micro=micro)
