#!/bin/sh
# Initialise la base de données (idempotent) puis démarre le service demandé.
set -e

echo "Initialisation de la base de données..."
python -m app.cli init-db || {
  echo "Nouvelle tentative d'initialisation (course entre conteneurs)..."
  sleep 2
  python -m app.cli init-db
}

exec "$@"
