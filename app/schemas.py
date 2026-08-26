"""Schémas Pydantic (requêtes et réponses de l'API)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str


class ImportRequest(BaseModel):
    path: str
    sheet_name: str = "Data"
    sync_prices: bool = True


class PriceSyncRequest(BaseModel):
    from_date: date | None = None
    until_date: date | None = None
    refresh: bool = False


class ImportResult(BaseModel):
    source_file: str
    sheet_name: str
    row_count: int
    imported: int
    duplicates: int
    issues: int
    prices: dict


class SyncResult(BaseModel):
    status: str
    count: int
    source_url: str
    error: str | None = None
