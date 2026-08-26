"""Interface en ligne de commande (`python -m app.cli`)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app.config import get_settings
from app.logging_conf import setup_logging

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def cmd_init_db(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        from alembic.config import Config

        from alembic import command

        cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
        command.upgrade(cfg, "head")
        print("Base de données initialisée (Alembic).")
    except Exception as exc:  # pragma: no cover - secours
        print(f"Alembic indisponible ({exc}) : création directe des tables.")
        from app.db import create_all

        create_all()

    from app.db import get_engine
    from app.views import create_recap_view

    create_recap_view(get_engine())
    print(f"Vue `recap_hourly` créée. Base : {settings.db_url}")
    return 0


def cmd_import_excel(args: argparse.Namespace) -> int:
    from app.services.importer import import_excel

    result = import_excel(
        args.file,
        sheet_name=args.sheet,
        sync_prices_flag=not args.no_sync_prices,
        settings=get_settings(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_fetch_prices(args: argparse.Namespace) -> int:
    from app.db import session_scope
    from app.services.prices import sync_prices

    settings = get_settings()
    with session_scope() as session:
        result = sync_prices(
            session,
            settings,
            from_date=_parse_date(args.from_date),
            until_date=_parse_date(args.until_date),
            refresh=args.refresh,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "ok" else 1


def cmd_rebuild(args: argparse.Namespace) -> int:
    from app.db import session_scope
    from app.services.importer import rebuild_aggregates

    settings = get_settings()
    with session_scope() as session:
        result = rebuild_aggregates(session, settings)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from app.db import session_scope
    from app.services.quality import validate

    with session_scope() as session:
        report = validate(session)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["all_reconciliations_ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="energy-app",
        description="Application de suivi énergétique ORES / Elexys.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Initialise le schéma de la base (Alembic).").set_defaults(func=cmd_init_db)

    p_import = sub.add_parser("import-excel", help="Importe la feuille Data d'un classeur Excel.")
    p_import.add_argument("--file", required=True, help="Chemin du classeur Excel.")
    p_import.add_argument("--sheet", default="Data", help="Nom de la feuille (défaut : Data).")
    p_import.add_argument("--no-sync-prices", action="store_true",
                          help="Ne pas récupérer les prix Elexys après l'import.")
    p_import.set_defaults(func=cmd_import_excel)

    p_prices = sub.add_parser("fetch-prices", help="Récupère les prix spot Elexys.")
    p_prices.add_argument("--from", dest="from_date", default=None, help="Date de début (YYYY-MM-DD).")
    p_prices.add_argument("--until", dest="until_date", default=None, help="Date de fin (YYYY-MM-DD).")
    p_prices.add_argument("--refresh", action="store_true", help="Ignore le cache local.")
    p_prices.set_defaults(func=cmd_fetch_prices)

    sub.add_parser("rebuild-aggregates", help="Reconstruit les agrégats horaires et mensuels.").set_defaults(
        func=cmd_rebuild
    )

    sub.add_parser("validate", help="Valide la cohérence des données.").set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - message utilisateur en français
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
