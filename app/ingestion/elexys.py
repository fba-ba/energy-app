"""Récupération des prix spot quart-horaires Elexys (Belpex day-ahead).

Stratégie :
1. export structuré (Excel) si accessible de façon stable ;
2. sinon, analyse du tableau HTML (Date / Heure / Euro) ;
3. Playwright uniquement en dernier recours (contenu rendu en JavaScript).

Un prix manquant reste `NULL` : on n'invente jamais de prix, on ne remplace
jamais un prix par zéro.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import io
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urljoin

import httpx

from app.config import Settings
from app.domain.datetime import local_to_utc
from app.logging_conf import get_logger

logger = get_logger("elexys")

# Le site Elexys écrit les heures au format « 23u45 » (u = heure).
HOUR_TOKEN_RE = re.compile(r"(?P<h>\d{1,2})[uUhH:.]?(?P<m>\d{2})?$")


@dataclass(frozen=True)
class PricePoint:
    """Un prix spot quart-horaire (brut, en €/MWh)."""

    timestamp_local: datetime
    timestamp_utc: datetime
    price_eur_mwh: Decimal


@dataclass(frozen=True)
class FetchOutcome:
    """Bilan d'une récupération Elexys."""

    points: list[PricePoint]
    source_url: str
    retrieved_at: datetime
    status: str  # ok / cache / erreur
    from_cache: bool = False
    error: str | None = None


def build_url(base_url: str, from_date: date, until_date: date) -> str:
    """Construit l'URL Elexys avec les paramètres `from` et `until`."""
    return (
        f"{base_url.rstrip('/')}"
        f"?from={from_date.isoformat()}&until={until_date.isoformat()}"
    )


def parse_hour_token(token: str) -> tuple[int, int] | None:
    """Analyse un jeton d'heure Elexys (`23u45`, `23:45`, `23h45`, `23`)."""
    if token is None:
        return None
    match = HOUR_TOKEN_RE.match(token.strip())
    if not match:
        return None
    hour = int(match.group("h"))
    minute = int(match.group("m") or 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def parse_date_token(token: str) -> date | None:
    """Analyse un jeton de date (`DD/MM/YYYY`, `YYYY-MM-DD`, `DD-MM-YYYY`)."""
    if token is None:
        return None
    text = str(token).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _to_local_datetime(date_value: date, hour: int, minute: int, timezone_name: str) -> tuple[datetime, datetime]:
    from zoneinfo import ZoneInfo

    local = datetime(date_value.year, date_value.month, date_value.day, hour, minute).replace(
        tzinfo=ZoneInfo(timezone_name)
    )
    utc = local_to_utc(local)
    return local.replace(tzinfo=None), utc.replace(tzinfo=None)


def _parse_price(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        text = str(value).strip().replace(",", ".").replace("€", "").replace("\u00a0", "")
        if not text:
            return None
        return Decimal(text)
    except Exception:
        return None


def _build_points(
    rows: list[tuple[object, object, object]],
    timezone_name: str,
    source: str,
) -> list[PricePoint]:
    points: list[PricePoint] = []
    for date_cell, hour_cell, price_cell in rows:
        d = parse_date_token(date_cell)
        if d is None:
            continue
        if isinstance(hour_cell, datetime):
            hm = (hour_cell.hour, hour_cell.minute)
        else:
            hm = parse_hour_token(str(hour_cell)) if hour_cell is not None else None
        if hm is None:
            continue
        price = _parse_price(price_cell)
        if price is None:
            continue  # prix manquant -> jamais transformé en zéro
        local, utc = _to_local_datetime(d, hm[0], hm[1], timezone_name)
        points.append(
            PricePoint(timestamp_local=local, timestamp_utc=utc, price_eur_mwh=price)
        )
    if not points:
        raise ValueError(f"Aucune ligne de prix exploitable trouvée ({source}).")
    return points


def parse_html_prices(html: str, timezone_name: str) -> list[PricePoint]:
    """Analyse le tableau HTML Elexys (colonnes Date / Heure / Euro)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[object, object, object]] = []
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).casefold() for th in table.find_all("th")]
        if not headers:
            headers = [
                td.get_text(strip=True).casefold()
                for td in table.find("tr").find_all(["td", "th"])
                if table.find("tr") is not None
            ]
        date_idx = next((i for i, h in enumerate(headers) if "date" in h), None)
        hour_idx = next((i for i, h in enumerate(headers) if "heure" in h), None)
        price_idx = next((i for i, h in enumerate(headers) if "euro" in h or "prix" in h), None)
        if date_idx is None or hour_idx is None or price_idx is None:
            continue
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) <= max(date_idx, hour_idx, price_idx):
                continue
            candidates.append((cells[date_idx], cells[hour_idx], cells[price_idx]))
    return _build_points(candidates, timezone_name, "HTML")


def parse_xlsx_prices(content: bytes, timezone_name: str) -> list[PricePoint]:
    """Analyse l'export Excel Elexys (colonnes Date / Heure / Euro)."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()

    # Localise la ligne d'en-tête (Date / Heure / Euro), précédée d'un titre.
    header_idx = None
    date_idx = hour_idx = price_idx = None
    for i, row in enumerate(rows):
        norm = [str(h).casefold() if h is not None else "" for h in row]
        d = next((j for j, h in enumerate(norm) if "date" in h), None)
        heu = next((j for j, h in enumerate(norm) if "heure" in h), None)
        euro = next((j for j, h in enumerate(norm) if "euro" in h or "prix" in h), None)
        if d is not None and heu is not None and euro is not None:
            header_idx, date_idx, hour_idx, price_idx = i, d, heu, euro
            break
    if header_idx is None:
        raise ValueError("Colonnes Date/Heure/Euro introuvables dans l'export Excel Elexys.")
    candidates = []
    for row in rows[header_idx + 1:]:
        if len(row) <= max(date_idx, hour_idx, price_idx):
            continue
        candidates.append((row[date_idx], row[hour_idx], row[price_idx]))
    return _build_points(candidates, timezone_name, "XLSX")


def _looks_like_xlsx(content: bytes) -> bool:
    return content[:2] == b"PK"


def _extract_export_url(html: str) -> str | None:
    """Extrait le lien d'export XLSX de la page Elexys (plage complète)."""
    match = re.search(r'href=["\']([^"\']*export/xlsx[^"\']*)["\']', html, flags=re.IGNORECASE)
    if not match:
        return None
    return html_lib.unescape(match.group(1))


class ElexysClient:
    """Client HTTP Elexys avec retries exponentiels, cache local et journalisation."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def _cache_path(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        cache_dir = self.settings.cache_path
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{key}.bin", cache_dir / f"{key}.json"

    def _download(self, url: str) -> bytes:
        """Télécharge avec retries exponentiels et User-Agent explicite."""
        last_error: Exception | None = None
        for attempt in range(self.settings.elexys_max_retries):
            try:
                with httpx.Client(
                    timeout=self.settings.elexys_timeout_seconds,
                    headers={"User-Agent": self.settings.elexys_user_agent},
                    follow_redirects=True,
                ) as client:
                    response = client.get(url)
                    logger.info(
                        "Récupération Elexys",
                        extra={"url": url, "status": response.status_code, "attempt": attempt + 1},
                    )
                    response.raise_for_status()
                    return response.content
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                wait = self.settings.elexys_backoff_seconds * (2**attempt)
                logger.warning(
                    "Échec de récupération Elexys",
                    extra={"url": url, "error": str(exc), "retry_in": wait},
                )
                time.sleep(wait)
        raise RuntimeError(
            f"Impossible de récupérer les prix Elexys après "
            f"{self.settings.elexys_max_retries} tentatives : {last_error}"
        )

    def _get_or_download(
        self,
        url: str,
        bin_path: Path,
        meta_path: Path,
        retrieved_at: datetime,
        refresh: bool,
    ) -> tuple[bytes | None, bool]:
        """Retourne le contenu (cache ou téléchargement) et indique s'il vient du cache."""
        if not refresh and bin_path.exists():
            return bin_path.read_bytes(), True
        try:
            content = self._download(url)
        except RuntimeError as exc:
            logger.error("Téléchargement impossible", extra={"url": url, "error": str(exc)})
            return None, False
        bin_path.write_bytes(content)
        meta_path.write_text(
            json.dumps({"url": url, "retrieved_at": retrieved_at.isoformat(), "status": 200}),
            encoding="utf-8",
        )
        return content, False

    def fetch(self, from_date: date, until_date: date, refresh: bool = False) -> FetchOutcome:
        """Récupère et analyse les prix pour la période donnée.

        Priorité : export XLSX (plage complète) > tableau HTML > Playwright.
        """
        url = build_url(self.settings.elexys_base_url, from_date, until_date)
        bin_path, meta_path = self._cache_path(url)
        retrieved_at = datetime.now(UTC).replace(tzinfo=None)

        content, from_cache = self._get_or_download(url, bin_path, meta_path, retrieved_at, refresh)
        if content is None:
            return FetchOutcome(
                points=[], source_url=url, retrieved_at=retrieved_at,
                status="erreur", error="Téléchargement impossible.",
            )

        def outcome(points: list[PricePoint], source_url: str = url) -> FetchOutcome:
            return FetchOutcome(
                points=points, source_url=source_url, retrieved_at=retrieved_at,
                status="cache" if from_cache else "ok", from_cache=from_cache,
            )

        # 1. Export structuré (XLSX) : contient toute la plage, contrairement au HTML paginé.
        if not _looks_like_xlsx(content):
            export_path = _extract_export_url(content.decode("utf-8", errors="replace"))
            if export_path:
                export_url = urljoin(self.settings.elexys_base_url, export_path)
                ebin, emeta = self._cache_path(export_url)
                xlsx, _ = self._get_or_download(export_url, ebin, emeta, retrieved_at, refresh)
                if xlsx is not None:
                    try:
                        return outcome(parse_xlsx_prices(xlsx, self.settings.timezone), export_url)
                    except ValueError as exc:
                        logger.warning(
                            "Export XLSX Elexys illisible, repli sur le tableau HTML",
                            extra={"error": str(exc)},
                        )

        # 2. Tableau HTML.
        try:
            if _looks_like_xlsx(content):
                points = parse_xlsx_prices(content, self.settings.timezone)
            else:
                points = parse_html_prices(content.decode("utf-8", errors="replace"), self.settings.timezone)
            return outcome(points)
        except ValueError as exc:
            logger.warning("Analyse HTML impossible", extra={"error": str(exc)})

        # 3. Dernier recours : Playwright.
        points = self._fetch_with_playwright(url) or []
        if points:
            return outcome(points)
        return FetchOutcome(
            points=[], source_url=url, retrieved_at=retrieved_at,
            status="erreur", error="Aucune donnée exploitable trouvée.",
        )

    def _fetch_with_playwright(self, url: str) -> list[PricePoint]:
        """Récupère le contenu rendu en JavaScript (Playwright, optionnel)."""
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError:
            logger.warning("Playwright non installé : analyse JavaScript impossible.")
            return []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, timeout=self.settings.elexys_timeout_seconds * 1000)
            html = page.content()
            browser.close()
        return parse_html_prices(html, self.settings.timezone)
