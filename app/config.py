"""Configuration centralisée de l'application (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Paramètres chargés depuis les variables d'environnement ou un fichier `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Base de données ---
    db_url: str = Field(default="sqlite:///./app.db", alias="ENERGY_DB_URL")

    # --- Fuseau horaire ---
    timezone: str = Field(default="Europe/Brussels", alias="ENERGY_TIMEZONE")

    # --- Elexys ---
    elexys_base_url: str = Field(
        default=(
            "https://www.elexys.be/fr/insights/"
            "quarter-hourly-belpex-day-ahead-spot-be"
        ),
        alias="ELEXYS_BASE_URL",
    )
    elexys_user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 EnergyApp/1.0"
        ),
        alias="ELEXYS_USER_AGENT",
    )
    elexys_timeout_seconds: float = Field(default=30.0, alias="ELEXYS_TIMEOUT_SECONDS")
    elexys_max_retries: int = Field(default=4, alias="ELEXYS_MAX_RETRIES")
    elexys_backoff_seconds: float = Field(default=2.0, alias="ELEXYS_BACKOFF_SECONDS")

    # --- Cache ---
    cache_dir: str = Field(default="./cache", alias="ENERGY_CACHE_DIR")

    # --- Transformation des prix (prix_kwh = (A + B × prix_mwh) / 1000) ---
    price_transform_a: str = Field(default="-17.3", alias="PRICE_TRANSFORM_A")
    price_transform_b: str = Field(default="0.3", alias="PRICE_TRANSFORM_B")

    # --- Import ---
    max_file_size_bytes: int = Field(
        default=52_428_800, alias="ENERGY_MAX_FILE_SIZE_BYTES"
    )
    allow_incomplete_price: bool = Field(
        default=False, alias="ENERGY_ALLOW_INCOMPLETE_PRICE"
    )
    allowed_import_roots_raw: str = Field(
        default="", alias="ENERGY_ALLOWED_IMPORT_ROOTS"
    )

    # --- Authentification (liste des EAN autorisés, séparés par des virgules) ---
    authorized_ean_list_raw: str = Field(default="", alias="AUTHORIZED_EAN_LIST")

    # --- SSL frontend (Streamlit, port 8501) ---
    ssl_cert_dir: str = Field(default="./certs", alias="ENERGY_SSL_CERT_DIR")
    ssl_cert_file: str = Field(default="", alias="ENERGY_SSL_CERT_FILE")
    ssl_key_file: str = Field(default="", alias="ENERGY_SSL_KEY_FILE")

    @property
    def db_path(self) -> Path:
        """Chemin du fichier SQLite (vide pour une base en mémoire)."""
        prefix = "sqlite:///"
        if not self.db_url.startswith(prefix):
            return Path()
        raw = self.db_url[len(prefix):]
        if raw in ("", ":memory:"):
            return Path()
        return Path(raw)

    @property
    def cache_path(self) -> Path:
        return Path(self.cache_dir)

    @property
    def allowed_import_roots(self) -> list[Path]:
        """Racines autorisées pour l'import (vide = pas de restriction)."""
        if not self.allowed_import_roots_raw.strip():
            return []
        parts = [p.strip() for p in self.allowed_import_roots_raw.replace(";", ",").split(",")]
        return [Path(p) for p in parts if p]

    @property
    def authorized_ean_list(self) -> list[str]:
        """Liste des EAN autorisés (vide = authentification désactivée).

        Tolère les valeurs entre guillemets simples/doubles et les espaces.
        """
        if not self.authorized_ean_list_raw.strip():
            return []
        result: list[str] = []
        for part in self.authorized_ean_list_raw.split(","):
            cleaned = part.strip().strip('"').strip("'").strip()
            if cleaned:
                result.append(cleaned)
        return result


@lru_cache
def get_settings() -> Settings:
    """Retourne l'instance unique de configuration."""
    return Settings()
