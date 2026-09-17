"""API FastAPI : import, synchronisation des prix, exports et accès aux agrégats."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import __version__
from app.config import Settings, get_settings
from app.db import get_session
from app.domain.units import micro_to_eur
from app.models import SpotPriceQuarterHourly
from app.repositories import aggregates as aggregates_repo
from app.repositories import prices as prices_repo
from app.schemas import (
    FormulaSwitchRequest,
    HealthResponse,
    ImportResult,
    MonthlyIndexPriceRequest,
    PriceSyncRequest,
    SyncResult,
)
from app.services import pricing_formula as pricing_formula_service
from app.services.aggregation import build_recap_rows, price_index_by_hour
from app.services.auth import is_ean_authorized
from app.services.exports import (
    export_monthly_xlsx,
    export_recap_xlsx,
    monthly_to_public_rows,
    recap_to_public_rows,
)
from app.services.importer import import_excel
from app.services.prices import sync_prices
from app.services.quality import get_issues

app = FastAPI(
    title="Suivi énergétique ORES / Elexys",
    version=__version__,
    description="Import des relevés ORES, prix spot Elexys et agrégation horaire/mensuelle.",
)


def get_db():
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def require_ean(
    x_ean: str | None = Header(default=None, alias="X-EAN"),
    settings: Settings = Depends(get_settings),
) -> str:
    """Vérifie l'en-tête `X-EAN` contre `AUTHORIZED_EAN_LIST`.

    Liste vide = accès libre (comportement par défaut). Sinon, l'EAN fourni
    doit figurer dans la liste autorisée.
    """
    if not is_ean_authorized(x_ean, settings):
        raise HTTPException(status_code=401, detail="EAN non autorisé.")
    return (x_ean or "").strip()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@app.post("/imports/excel", response_model=ImportResult, dependencies=[Depends(require_ean)])
def imports_excel(
    file: UploadFile | None = File(default=None),
    path: str | None = Form(default=None),
    sheet_name: str = Form(default="Data"),
    sync_prices: bool = Form(default=True),
    settings: Settings = Depends(get_settings),
) -> ImportResult:
    """Importe un classeur (fichier téléversé ou chemin serveur)."""
    if file is not None:
        suffix = Path(file.filename or "upload.xlsx").suffix or ".xlsx"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file.file.read())
            target = tmp.name
        try:
            result = import_excel(
                target, sheet_name=sheet_name, sync_prices_flag=sync_prices, settings=settings
            )
        finally:
            Path(target).unlink(missing_ok=True)
    elif path:
        result = import_excel(path, sheet_name=sheet_name, sync_prices_flag=sync_prices, settings=settings)
    else:
        raise HTTPException(status_code=400, detail="Fournir un fichier ou un chemin serveur.")
    return ImportResult(**result)


@app.post("/prices/sync", response_model=SyncResult, dependencies=[Depends(require_ean)])
def prices_sync(
    body: PriceSyncRequest,
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_db),
) -> SyncResult:
    try:
        result = sync_prices(
            session,
            settings,
            from_date=body.from_date,
            until_date=body.until_date,
            refresh=body.refresh,
        )
        session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SyncResult(**result)


@app.get("/pricing/formulas", dependencies=[Depends(require_ean)])
def pricing_formulas(
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_db),
) -> list[dict]:
    """Liste les formules de prix disponibles (Engie, Bolt, Octa+, TotalEnergie...) et la formule active."""
    return pricing_formula_service.list_formulas(session, settings)


@app.post("/pricing/formula", dependencies=[Depends(require_ean)])
def pricing_set_formula(
    body: FormulaSwitchRequest,
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_db),
) -> dict:
    """Change la formule de prix active et reconstruit tous les agrégats.

    Refusé (400) si des données requises (indice mensuel, prix Elexys) sont
    manquantes : la base n'est alors pas modifiée.
    """
    try:
        result = pricing_formula_service.switch_formula(session, settings, body.formula)
        session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@app.get("/pricing/monthly-index", dependencies=[Depends(require_ean)])
def pricing_monthly_index(index_key: str | None = None, session: Session = Depends(get_db)) -> list[dict]:
    """Liste les indices mensuels encodés (EPEX SPP pour Octa+, BELPEXM pour TotalEnergie...)."""
    return [
        {
            "index_key": p.index_key,
            "month": p.month,
            "price_eur_mwh": str(micro_to_eur(p.price_eur_mwh_micro)),
        }
        for p in prices_repo.get_monthly_index_prices(session, index_key)
    ]


@app.post("/pricing/monthly-index", dependencies=[Depends(require_ean)])
def pricing_set_monthly_index(
    body: MonthlyIndexPriceRequest,
    session: Session = Depends(get_db),
) -> dict:
    """Encode (ou met à jour) l'indice mensuel `index_key` d'un mois donné."""
    try:
        result = pricing_formula_service.set_monthly_index_price(
            session, body.index_key, body.month, body.price_eur_mwh
        )
        session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


def _load_recap_rows(
    session: Session,
    settings: Settings,
    site_name: str | None = None,
    ean_number: str | None = None,
) -> list[dict]:
    hourly_orm = aggregates_repo.get_hourly(session, site_name=site_name, ean_number=ean_number)
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
    formula = pricing_formula_service.get_active_formula(session, settings)
    if formula.requires == "monthly_index":
        price_index: dict = {}
        monthly_index = prices_repo.get_monthly_index(session, formula.index_key)
    else:
        prices_orm = session.query(SpotPriceQuarterHourly).order_by(SpotPriceQuarterHourly.timestamp_utc).all()
        price_index = price_index_by_hour(
            [
                {
                    "timestamp_local": p.timestamp_local,
                    "price_eur_kwh_transformed_micro": p.price_eur_kwh_transformed_micro,
                }
                for p in prices_orm
            ]
        )
        monthly_index = {}
    return build_recap_rows(
        hourly,
        price_index,
        settings.allow_incomplete_price,
        formula=formula,
        monthly_index=monthly_index,
    )


@app.get("/recap/hourly", dependencies=[Depends(require_ean)])
def recap_hourly(
    site_name: str | None = None,
    ean_number: str | None = None,
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_db),
) -> list[dict]:
    return recap_to_public_rows(_load_recap_rows(session, settings, site_name, ean_number))


@app.get("/totals/monthly", dependencies=[Depends(require_ean)])
def totals_monthly(
    site_name: str | None = None,
    ean_number: str | None = None,
    session: Session = Depends(get_db),
) -> list[dict]:
    records = [
        {
            "month": m.month,
            "site_name": m.site_name,
            "ean_number": m.ean_number,
            "withdrawn_kwh_milli": m.withdrawn_kwh_milli,
            "injected_kwh_milli": m.injected_kwh_milli,
            "net_injected_minus_withdrawn_kwh_milli": m.net_injected_minus_withdrawn_kwh_milli,
            "injected_value_eur_micro": m.injected_value_eur_micro,
            "average_spot_price_eur_kwh_micro": m.average_spot_price_eur_kwh_micro,
            "negative_price_hours": m.negative_price_hours,
            "hours_with_missing_energy": m.hours_with_missing_energy,
            "hours_with_missing_price": m.hours_with_missing_price,
        }
        for m in aggregates_repo.get_monthly(session, site_name=site_name, ean_number=ean_number)
    ]
    return monthly_to_public_rows(records)


@app.get("/quality/issues", dependencies=[Depends(require_ean)])
def quality_issues(session: Session = Depends(get_db)) -> list[dict]:
    return get_issues(session)


@app.get("/exports/recap.xlsx", dependencies=[Depends(require_ean)])
def export_recap_xlsx_endpoint(
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_db),
) -> Response:
    rows = _load_recap_rows(session, settings)
    content = export_recap_xlsx(rows)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=recap.xlsx"},
    )


@app.get("/exports/monthly.xlsx", dependencies=[Depends(require_ean)])
def export_monthly_xlsx_endpoint(session: Session = Depends(get_db)) -> Response:
    records = [
        {
            "month": m.month,
            "site_name": m.site_name,
            "ean_number": m.ean_number,
            "withdrawn_kwh_milli": m.withdrawn_kwh_milli,
            "injected_kwh_milli": m.injected_kwh_milli,
            "net_injected_minus_withdrawn_kwh_milli": m.net_injected_minus_withdrawn_kwh_milli,
            "injected_value_eur_micro": m.injected_value_eur_micro,
            "average_spot_price_eur_kwh_micro": m.average_spot_price_eur_kwh_micro,
            "negative_price_hours": m.negative_price_hours,
            "hours_with_missing_energy": m.hours_with_missing_energy,
            "hours_with_missing_price": m.hours_with_missing_price,
        }
        for m in aggregates_repo.get_monthly(session)
    ]
    content = export_monthly_xlsx(records)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=monthly.xlsx"},
    )
