"""Transformation et agrégation des prix spot Elexys."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

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
