"""Authentification simple par liste d'EAN autorisés.

L'EAN n'étant pas public, le fait de le connaître suffit à s'authentifier
(pas de mot de passe). Si la liste est vide, l'accès est libre.
"""

from __future__ import annotations

from app.config import Settings


def is_ean_authorized(ean: str | None, settings: Settings) -> bool:
    """Retourne `True` si l'EAN est autorisé (ou si l'authentification est désactivée)."""
    allowed = settings.authorized_ean_list
    if not allowed:
        return True
    return (ean or "").strip() in allowed
