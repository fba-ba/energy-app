"""Import du classeur Excel ORES (feuille `Data`).

La feuille `Data` peut contenir un nombre quelconque de colonnes ; les colonnes
temporelles dérivées (Year, Month, Day, Hour, Minute, Second, DayOfWeek,
WeekNumber) sont recalculées à partir de `DataTime`. L'import est donc capable
d'enrichir une feuille brute vers le schéma canonique de 22 colonnes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import openpyxl

from app.config import Settings
from app.domain.classification import classify_direction
from app.domain.datetime import excel_serial_to_datetime, local_to_utc, to_aware_brussels
from app.domain.units import kwh_to_milli, to_decimal

# Correspondance en-têtes (normalisés) -> clés canoniques.
HEADER_MAP = {
    "sourceid": "source_id",
    "sitename": "site_name",
    "sourcename": "source_name",
    "eannumber": "ean_number",
    "meternumber": "meter_number",
    "rawdataperiod": "raw_data_period",
    "datatime": "data_time",
    "unit": "unit",
    "conso": "conso",
    "variablename": "variable_name",
    "granularity": "granularity",
    "aggregation": "aggregation",
    "rawdataperiodfrequency": "raw_data_period_frequency",
}

# Colonnes dérivées (recalculées, jamais lues en priorité).
DERIVED_HEADERS = {
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "second",
    "dayofweek",
    "weeknumber",
}


def _normalize_header(value: object) -> str:
    """Normalise un en-tête : minuscules, sans accents, sans espaces ni symboles."""
    import unicodedata

    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return "".join(c for c in text.casefold() if c.isalnum())


@dataclass
class ExcelParseResult:
    """Résultat de l'analyse d'un classeur."""

    readings: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    row_count: int = 0
    sheet_name: str = "Data"
    source_file: str = ""


def validate_import_path(path: str | Path, settings: Settings) -> Path:
    """Valide le chemin du classeur et retourne un `Path` absolu.

    Lève une `ValueError` avec un message en français si le chemin est invalide,
    trop volumineux ou hors des racines autorisées.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ValueError(f"Le fichier n'existe pas : {p}")
    if not p.is_file():
        raise ValueError(f"Le chemin n'est pas un fichier : {p}")
    if p.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ValueError(
            f"Format de fichier non pris en charge ({p.suffix}). "
            "Attendu : .xlsx ou .xlsm."
        )
    if p.stat().st_size > settings.max_file_size_bytes:
        raise ValueError(
            f"Le fichier est trop volumineux "
            f"({p.stat().st_size} octets, maximum {settings.max_file_size_bytes})."
        )
    roots = settings.allowed_import_roots
    if roots:
        resolved_roots = [r.expanduser().resolve() for r in roots]
        if not any(p == root or root in p.parents for root in resolved_roots):
            raise ValueError(
                f"Chemin non autorisé : {p}. Racines autorisées : "
                + ", ".join(str(r) for r in resolved_roots)
            )
    return p


def _read_rows(path: Path, sheet_name: str) -> tuple[list[str], list[tuple]]:
    """Lit l'en-tête et les lignes de la feuille demandée (feuille cachée acceptée)."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet_name not in wb.sheetnames:
            raise ValueError(
                f"Feuille {sheet_name!r} introuvable dans {path.name}. "
                f"Feuilles disponibles : {', '.join(wb.sheetnames)}"
            )
        ws = wb[sheet_name]
        rows = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows)
        except StopIteration:
            raise ValueError(f"La feuille {sheet_name!r} est vide.") from None
        header = [str(h) if h is not None else "" for h in header_row]
        data_rows = list(rows)
    finally:
        wb.close()
    return header, data_rows


def _build_column_map(header: list[str]) -> dict[str, int]:
    """Associe chaque clé canonique à l'index de sa colonne."""
    mapping: dict[str, int] = {}
    for idx, name in enumerate(header):
        norm = _normalize_header(name)
        if norm in DERIVED_HEADERS:
            continue  # recalculé depuis DataTime
        key = HEADER_MAP.get(norm)
        if key and key not in mapping:
            mapping[key] = idx
    return mapping


def _dedup_hash(
    source_id: object,
    source_name: object,
    ean_number: object,
    data_time_local: datetime | None,
    variable_name: object,
    raw_data_period: object,
    direction: str | None,
) -> str:
    # La source est identifiée par le numéro de série (`source_name`) quand il est
    # disponible (stable entre rapports) ; `source_id` sert de secours.
    source = str(source_name or source_id or "")
    payload = "|".join(
        [
            source,
            str(ean_number or ""),
            data_time_local.isoformat() if data_time_local else "",
            str(variable_name or ""),
            str(raw_data_period or ""),
            str(direction or ""),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_workbook(path: str | Path, settings: Settings, sheet_name: str = "Data") -> ExcelParseResult:
    """Analyse la feuille `Data` d'un classeur et produit relevés normalisés + anomalies."""
    resolved = validate_import_path(path, settings)
    header, rows = _read_rows(resolved, sheet_name)
    col = _build_column_map(header)

    result = ExcelParseResult(
        row_count=len(rows),
        sheet_name=sheet_name,
        source_file=str(resolved),
    )

    for row_number, row in enumerate(rows, start=2):  # ligne 1 = en-tête
        def get(key: str, *, row: tuple = row, col: dict = col) -> object:
            idx = col.get(key)
            return row[idx] if idx is not None and idx < len(row) else None

        variable_name = get("variable_name")
        conso = get("conso")
        unit = get("unit")
        raw_data_time = get("data_time")
        direction = classify_direction(variable_name)

        # --- Anomalies : horodatage, unité, valeur, direction inexploitables ---
        local_dt = excel_serial_to_datetime(raw_data_time)
        if local_dt is None:
            result.issues.append(
                _issue("horodatage_manquant", "Ligne sans horodatage exploitable.",
                       row_number, row, severity="error")
            )
            continue
        if direction is None:
            result.issues.append(
                _issue("variable_inconnue",
                       f"Variable non reconnue : {variable_name!r}.", row_number, row)
            )
            continue
        if unit is None or not str(unit).strip():
            result.issues.append(
                _issue("unite_manquante", "Ligne sans unité exploitable.",
                       row_number, row, severity="error")
            )
            continue
        try:
            value_kwh = to_decimal(conso)
        except (TypeError, ValueError):
            result.issues.append(
                _issue("valeur_invalide",
                       f"Valeur de consommation non numérique : {conso!r}.",
                       row_number, row, severity="error")
            )
            continue

        # --- Normalisation temporelle (Europe/Brussels) ---
        local_aware = to_aware_brussels(raw_data_time, settings.timezone)
        utc_dt = local_to_utc(local_aware) if local_aware else None

        source_id = get("source_id")
        ean_number = get("ean_number")
        source_name = get("source_name")
        raw_period = get("raw_data_period")

        result.readings.append(
            {
                "source_row_number": row_number,
                "source_id": _to_int(source_id),
                "site_name": _to_str(get("site_name")),
                "source_name": _to_str(source_name),
                "ean_number": _to_str(ean_number),
                "meter_number": _to_str(get("meter_number")),
                "raw_data_period": _to_str(raw_period),
                "unit": _to_str(unit),
                "variable_name": _to_str(variable_name),
                "granularity": _to_str(get("granularity")),
                "aggregation": _to_str(get("aggregation")),
                "raw_data_period_frequency": _to_int(get("raw_data_period_frequency")),
                "data_time_raw": _raw_repr(raw_data_time),
                "data_time_local": local_dt,
                "data_time_utc": utc_dt.replace(tzinfo=None) if utc_dt else None,
                "direction": direction.value,
                "value_kwh_milli": kwh_to_milli(value_kwh),
                "dedup_hash": _dedup_hash(
                    source_id, source_name, ean_number, local_dt,
                    variable_name, raw_period, direction.value,
                ),
            }
        )

    return result


def _issue(issue_type: str, message: str, row_number: int, row: tuple, severity: str = "warning") -> dict:
    return {
        "issue_type": issue_type,
        "severity": severity,
        "message": message,
        "source_row_number": row_number,
        "raw_data": json.dumps([_raw_repr(v) for v in row], ensure_ascii=False),
    }


def _raw_repr(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (int, float)):
        return str(value)
    return "" if value is None else str(value)


def _to_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
