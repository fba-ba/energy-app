"""Moteur, session et base déclarative SQLAlchemy."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Base déclarative commune à tous les modèles."""


def _enable_sqlite_fk(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Retourne l'instance unique du moteur SQLAlchemy."""
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"future": True}
        if settings.db_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(settings.db_url, **kwargs)
        if settings.db_url.startswith("sqlite"):
            event.listen(_engine, "connect", _enable_sqlite_fk)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Retourne la fabrique de sessions."""
    get_engine()
    assert _session_factory is not None
    return _session_factory


def get_session() -> Session:
    """Retourne une nouvelle session."""
    return get_session_factory()()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Contexte transactionnel : commit en fin, rollback en cas d'erreur."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all() -> None:
    """Crée toutes les tables (utilisé en secours ; la voie nominale est Alembic)."""
    from app import models  # noqa: F401  (enregistre les modèles)

    Base.metadata.create_all(get_engine())
