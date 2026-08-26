"""Unités de stockage exactes.

Les calculs financiers et énergétiques sensibles sont effectués avec `Decimal`
puis stockés en entiers (millièmes de kWh et millionièmes d'euro) afin d'éviter
toute erreur d'arrondi liée aux flottants binaires. Aucun nombre n'est stocké
sous forme de chaîne formatée.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Énergie : millièmes de kWh (3 décimales).
KWH_SCALE = Decimal(1000)

# Montants / prix : millionièmes d'euro (6 décimales).
EUR_SCALE = Decimal(1_000_000)


def to_decimal(value: object) -> Decimal:
    """Convertit une valeur (float, int, str, Decimal) en Decimal propre.

    Lève `ValueError` si la valeur n'est pas un nombre exploitable.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # `str(float)` évite l'artefact binaire (ex. 0.010000000000218279 -> 0.010...).
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError(f"Nombre invalide : {value!r}") from exc
    raise TypeError(f"Valeur non convertible en Decimal : {type(value)!r}")


def kwh_to_milli(value: object) -> int:
    """kWh -> millièmes de kWh (entier, arrondi au plus proche)."""
    return int((to_decimal(value) * KWH_SCALE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def milli_to_kwh(value: object) -> Decimal:
    """millièmes de kWh -> kWh (Decimal)."""
    return to_decimal(value) / KWH_SCALE


def eur_to_micro(value: object) -> int:
    """euros -> millionièmes d'euro (entier, arrondi au plus proche)."""
    return int((to_decimal(value) * EUR_SCALE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def micro_to_eur(value: object) -> Decimal:
    """millionièmes d'euro -> euros (Decimal)."""
    return to_decimal(value) / EUR_SCALE


def mul_milli_micro(milli: object, micro: object) -> int:
    """Multiplie millièmes de kWh par millionièmes d'euro -> millionièmes d'euro."""
    kwh = milli_to_kwh(milli)
    eur = micro_to_eur(micro)
    return eur_to_micro(kwh * eur)
