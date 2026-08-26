"""Tests de l'authentification par liste d'EAN autorisés."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api import require_ean
from app.config import Settings, get_settings
from app.services.auth import is_ean_authorized


@pytest.fixture()
def make_settings(monkeypatch):
    def _make(raw: str) -> Settings:
        monkeypatch.setenv("AUTHORIZED_EAN_LIST", raw)
        return Settings()
    return _make


def test_authorized_ean_list_parses_quoted_values(make_settings):
    settings = make_settings('"000000000000000001","000000000000000002"')
    assert settings.authorized_ean_list == ["000000000000000001", "000000000000000002"]


def test_authorized_ean_list_parses_malformed_quotes(make_settings):
    # Exemple tel que fourni : guillemets mal équilibrés.
    settings = make_settings('"000000000000000001,"000000000000000002"')
    assert settings.authorized_ean_list == ["000000000000000001", "000000000000000002"]


def test_authorized_ean_list_parses_plain_values(make_settings):
    settings = make_settings("000000000000000001, 000000000000000002")
    assert settings.authorized_ean_list == ["000000000000000001", "000000000000000002"]


def test_empty_list_disables_auth(make_settings):
    settings = make_settings("")
    assert settings.authorized_ean_list == []
    assert is_ean_authorized("n'importe quel EAN", settings) is True


def test_ean_membership(make_settings):
    settings = make_settings("000000000000000001")
    assert is_ean_authorized("000000000000000001", settings) is True
    assert is_ean_authorized("000000000000000002", settings) is False
    assert is_ean_authorized(" 000000000000000001 ", settings) is True


def _test_client(monkeypatch, authorized: str) -> TestClient:
    monkeypatch.setenv("AUTHORIZED_EAN_LIST", authorized)
    app = FastAPI()
    app.dependency_overrides[get_settings] = lambda: Settings()

    @app.get("/protect", dependencies=[Depends(require_ean)])
    def protect() -> dict:
        return {"ok": True}

    return TestClient(app)


def test_api_requires_x_ean_header(monkeypatch):
    client = _test_client(monkeypatch, "000000000000000001")

    assert client.get("/protect").status_code == 401
    assert client.get("/protect", headers={"X-EAN": "000000000000000001"}).status_code == 200
    assert client.get("/protect", headers={"X-EAN": "000000000000000002"}).status_code == 401


def test_api_open_when_auth_disabled(monkeypatch):
    client = _test_client(monkeypatch, "")
    assert client.get("/protect").status_code == 200
