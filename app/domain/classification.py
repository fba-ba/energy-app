"""Classification des variables énergie en prélèvement / injection."""

from __future__ import annotations

import unicodedata
from enum import StrEnum


class Direction(StrEnum):
    WITHDRAWAL = "withdrawal"  # prélèvement
    INJECTION = "injection"  # injection


def _strip_accents(value: str) -> str:
    """Retire les accents pour une comparaison insensible aux diacritiques."""
    normalized = unicodedata.normalize("NFD", value)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def normalize_label(value: str | None) -> str:
    """Normalise un libellé : minuscules, sans accents, sans espaces superflus."""
    if value is None:
        return ""
    return _strip_accents(value.casefold()).strip()


def classify_direction(variable_name: str | None) -> Direction | None:
    """Classe une variable en prélèvement ou injection (insensible à la casse et aux accents).

    - contient « consumption » ou « energie prelevee » -> prélèvement ;
    - contient « production » ou « energie injectee » -> injection ;
    - sinon `None` (anomalie).
    """
    label = normalize_label(variable_name)
    if not label:
        return None
    if "consumption" in label or label == "energie prelevee":
        return Direction.WITHDRAWAL
    if "production" in label or label == "energie injectee":
        return Direction.INJECTION
    return None


def is_totals(variable_name: str | None) -> bool:
    """Indique si la variable est un registre « Totals » (énergie totale).

    NB : les registres « totals rate N » contiennent aussi le mot « totals » mais
    sont des composantes tarifaires : ils sont donc exclus.
    """
    label = normalize_label(variable_name)
    return "totals" in label and "rate" not in label


def is_rate(variable_name: str | None) -> bool:
    """Indique si la variable est un registre tarifaire `rate N`."""
    label = normalize_label(variable_name)
    return "rate" in label


def is_day_period(row_period: str | None) -> bool:
    """Indique si la ligne est un agrégat journalier (à exclure du récap horaire)."""
    return normalize_label(row_period) == "day"
