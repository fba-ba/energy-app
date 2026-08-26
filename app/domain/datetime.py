"""Gestion des dates/heures : numéros de série Excel et fuseau Europe/Brussels."""

from __future__ import annotations

import datetime as dt
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Époque Excel : le numéro de série 1 correspond au 1900-01-01.
# openpyxl utilise la convention 1899-12-30 (compatible avec le bogue 1900).
EXCEL_EPOCH = datetime(1899, 12, 30)


def excel_serial_to_datetime(value: object) -> datetime | None:
    """Convertit un numéro de série Excel (float) en datetime naïf.

    Retourne `None` si la valeur n'est pas exploitable.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, dt.date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, (int, float)):
        try:
            return EXCEL_EPOCH + timedelta(days=float(value))
        except (OverflowError, ValueError):
            return None
    return None


def to_aware_brussels(value: object, timezone_name: str = "Europe/Brussels") -> datetime | None:
    """Attache le fuseau local à un datetime naïf (heure « murale » locale)."""
    naive = excel_serial_to_datetime(value)
    if naive is None:
        return None
    tz = ZoneInfo(timezone_name)
    return naive.replace(tzinfo=tz)


def local_to_utc(value: datetime) -> datetime | None:
    """Convertit un datetime conscient (heure locale) en UTC conscient."""
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("Datetime naïf : impossible de convertir en UTC sans fuseau.")
    return value.astimezone(dt.UTC)


def floor_to_hour(value: datetime) -> datetime:
    """Retourne le début d'heure (heure murale) d'un datetime local naïf."""
    return value.replace(minute=0, second=0, microsecond=0)


def hour_bucket(value: datetime) -> datetime:
    """Regroupe un horodatage local dans son heure de début."""
    return value.replace(minute=0, second=0, microsecond=0)


def add_hours_aware(value: datetime, hours: int) -> datetime:
    """Ajoute `hours` heures à un datetime conscient en respectant le fuseau."""
    return value + timedelta(hours=hours)
