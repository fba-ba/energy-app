# Suivi énergétique ORES / Elexys

Application locale (et déployable sur serveur distant) qui :

1. importe la feuille `Data` d'un classeur **ORES** (un rapport par mois) ;
2. récupère les prix spot **quart-horaires Elexys** (Belpex day-ahead) ;
3. stocke tout dans **SQLite** (SQLAlchemy 2.x + Alembic) ;
4. produit une vue horaire `recap_hourly` fonctionnellement identique à la feuille `Récap` ;
5. calcule les **totaux mensuels** ;
6. affiche les **graphiques clés** (Streamlit + Plotly) ;
7. relance l'import **sans créer de doublons**.

---

## 1. Arborescence

```text
.
├── app/
│   ├── api.py                  # API FastAPI
│   ├── cli.py                  # Interface en ligne de commande
│   ├── config.py               # Configuration (pydantic-settings)
│   ├── dashboard.py            # Interface Streamlit
│   ├── db.py                   # Moteur / session SQLAlchemy
│   ├── models.py               # Modèles SQLAlchemy
│   ├── schemas.py              # Schémas Pydantic (API)
│   ├── views.py                # Vue SQL recap_hourly
│   ├── domain/                 # Règles métier (dates, prix, unités, classification)
│   ├── ingestion/              # Import Excel + récupération Elexys
│   ├── repositories/           # Accès aux données
│   └── services/               # Agrégation, exports, qualité, import, prix
├── alembic/                    # Migrations
├── tests/                      # Tests pytest
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── pyproject.toml
├── Makefile
└── README.md
```

## 2. Prérequis

- Python **3.12+**
- (optionnel) Docker pour le déploiement distant

## 3. Installation

```bash
# Environnement virtuel
python -m venv .venv
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

# Dépendances (runtime + dev)
python -m pip install -e ".[dev]"

# Configuration (copier puis adapter si besoin)
copy .env.example .env        # Windows
cp .env.example .env          # Linux/macOS
```

## 4. Initialisation

```bash
python -m app.cli init-db
```

Crée automatiquement la base `app.db` (tables + vue `recap_hourly`).

## 5. Utilisation (ligne de commande)

```bash
# Importer un rapport mensuel ORES (feuille Data, onglet caché accepté)
python -m app.cli import-excel --file "D:/DevSources/Ores_Digest/Rapport mensuel ORES - 2026-08-03 - 0306 PM.xlsx" --sheet Data

# Récupérer les prix Elexys (période déduite des données, ou surchargée)
python -m app.cli fetch-prices
python -m app.cli fetch-prices --from 2026-06-17 --until 2026-07-31 --refresh

# Reconstruire les agrégats (heures + mois) après un import manuel
python -m app.cli rebuild-aggregates

# Valider la cohérence (réconciliation horaire <-> mensuel)
python -m app.cli validate
```

L'import est **atomique** et **idempotent** : relancer la même commande ne crée
aucun doublon (contrainte unique `dedup_hash`).

### 5.1 Exemple complet (commandes réellement exécutées)

Parcours validé sur les deux classeurs fournis (résultat : 1 036 heures, 2 mois,
4 320 prix quart-horaires, réconciliation horaire ↔ mensuel OK) :

```powershell
# 1. Initialisation du schéma (tables + vue recap_hourly)
.venv\Scripts\python.exe -m app.cli init-db

# 2. Import du rapport mensuel ORES (feuille Data, onglet caché accepté)
.venv\Scripts\python.exe -m app.cli import-excel --file "Rapport mensuel ORES - 2026-08-03 - 0306 PM.xlsx" --sheet Data
.venv\Scripts\python.exe -m app.cli import-excel --file "Rapport mensuel ORES - JUILLET - 0315 PM_COURBEVOIE.xlsx" --sheet Data

# 3. Récupération des prix spot Elexys (période déduite automatiquement : 17/06 -> 31/07)
.venv\Scripts\python.exe -m app.cli fetch-prices

# 4. Reconstruction des agrégats horaires et mensuels avec les prix
.venv\Scripts\python.exe -m app.cli rebuild-aggregates

# 5. Validation de cohérence
.venv\Scripts\python.exe -m app.cli validate

# 6. Tests et linting
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check app tests
```

Valeurs de référence vérifiées : `17/06/2026 21:00` → prélevé `0.010` kWh,
injecté `2.430` kWh, prix `0.030902` €/kWh, valeur injectée `0.075092` €.

## 6. API (FastAPI)

```bash
uvicorn app.api:app --reload
```

| Méthode | Chemin | Description |
|---|---|---|
| GET | `/health` | État du service |
| POST | `/imports/excel` | Import (fichier téléversé ou chemin serveur) |
| POST | `/prices/sync` | Synchronisation des prix Elexys |
| GET | `/recap/hourly` | Récap horaire (21 colonnes) |
| GET | `/totals/monthly` | Totaux mensuels |
| GET | `/quality/issues` | Anomalies de qualité |
| GET | `/exports/recap.xlsx` | Export XLSX du récap |
| GET | `/exports/monthly.xlsx` | Export XLSX mensuel |

## 7. Interface (Streamlit)

```bash
streamlit run app/dashboard.py
```

Pages : **Récap horaire** (courbes prélèvement/injection, énergie cumulée, prix
et injection, profil moyen par heure) et **Synthèse mensuelle** (KPI, tableau,
comparaison au mois précédent, complétude).

## 8. Tests

```bash
pytest                # tests unitaires + intégration (hors-ligne)
pytest -m elexys_live # test d'intégration qui contacte réellement Elexys (réseau)
```

Le test d'intégration Excel utilise les deux classeurs réels si la variable
d'environnement `ENERGY_TEST_WORKBOOK` pointe vers un classeur ORES.

## 9. Linting

```bash
ruff check app tests
```

## 10. Docker — construction, déploiement et interactions

L'application est distribuée en deux conteneurs (Compose) :

- **api** : FastAPI (port `8000`) ;
- **ui** : Streamlit (port `8501`).

Les deux partagent le volume nommé `appdata`, monté sur `/data` dans chaque
conteneur (base `app.db` et cache Elexys).

### 10.1 Construction et déploiement

```bash
# Construire l'image et démarrer (détaché)
docker compose up --build -d

# État des services
docker compose ps

# Journaux
docker compose logs -f api
docker compose logs -f ui

# Arrêter (le volume et les données sont conservés)
docker compose down

# Arrêter et supprimer le volume (données effacées)
docker compose down -v
```

Accès :

- API : `http://<serveur>:8000` (documentation interactive : `http://<serveur>:8000/docs`)
- Interface : `http://<serveur>:8501`

### 10.2 Configuration

Les variables d'environnement sont définies dans `docker-compose.yml`
(`ENERGY_DB_URL`, `ENERGY_CACHE_DIR`). Elles peuvent être surchargées par un
fichier `.env` (lu automatiquement par Docker Compose) :

```bash
cp .env.example .env   # puis adapter
```

### 10.3 Importer des données

**Option A — via l'API (téléversement du fichier) :**

```bash
curl -X POST http://<serveur>:8000/imports/excel \
  -F "file=@Rapport mensuel ORES - 2026-08-03 - 0306 PM.xlsx" \
  -F "sheet_name=Data" \
  -F "sync_prices=true"
```

Sous **Windows PowerShell**, `curl` est un alias de `Invoke-WebRequest` qui
n'accepte pas les options `-H` / `-d` / `-F` : utilisez `curl.exe` (curl réel,
fourni avec Windows 10+) :

```powershell
curl.exe -X POST http://<serveur>:8000/imports/excel -F "file=@C:\chemin\vers\Rapport mensuel ORES - 2026-08-03 - 0306 PM.xlsx" -F "sheet_name=Data" -F "sync_prices=true"
```

**Option B — via la CLI dans le conteneur** (après copie du fichier dans le
volume partagé) :

```bash
docker cp "Rapport mensuel ORES - 2026-08-03 - 0306 PM.xlsx" "$(docker compose ps -q api):/data/"
docker compose exec api python -m app.cli import-excel \
  --file "/data/Rapport mensuel ORES - 2026-08-03 - 0306 PM.xlsx" --sheet Data
```

### 10.4 Récupérer les prix Elexys

```bash
# Période déduite automatiquement des données importées
curl -X POST http://<serveur>:8000/prices/sync \
  -H "Content-Type: application/json" -d '{}'

# Période imposée
curl -X POST http://<serveur>:8000/prices/sync \
  -H "Content-Type: application/json" \
  -d '{"from_date":"2026-06-17","until_date":"2026-07-31","refresh":false}'
```

Sous **Windows PowerShell**, utilisez `Invoke-RestMethod` (ou `curl.exe`) :

```powershell
# Période déduite automatiquement
Invoke-RestMethod -Method Post -Uri http://<serveur>:8000/prices/sync -ContentType "application/json" -Body '{}'

# Période imposée
Invoke-RestMethod -Method Post -Uri http://<serveur>:8000/prices/sync -ContentType "application/json" -Body '{"from_date":"2026-06-17","until_date":"2026-07-31","refresh":false}'

# Équivalent curl réel (curl.exe)
curl.exe -X POST http://<serveur>:8000/prices/sync -H "Content-Type: application/json" -d '{}'
```

Équivalent en CLI :

```bash
docker compose exec api python -m app.cli fetch-prices
docker compose exec api python -m app.cli fetch-prices --from 2026-06-17 --until 2026-07-31 --refresh
```

### 10.5 Reconstruire les agrégats et valider

```bash
docker compose exec api python -m app.cli rebuild-aggregates
docker compose exec api python -m app.cli validate
```

### 10.6 Exports (CSV / XLSX)

```bash
curl -OJ http://<serveur>:8000/exports/recap.xlsx
curl -OJ http://<serveur>:8000/exports/monthly.xlsx
```

Les mêmes données sont consultables en JSON via `/recap/hourly` et
`/totals/monthly`.

### 10.7 Remarques

- **Aucune authentification** n'est configurée par défaut : exposer les ports
  derrière un reverse proxy ou restreindre l'accès réseau (firewall) si le
  serveur est accessible depuis Internet.
- **SQLite sur volume partagé** : adapté à un usage personnel / faible
  concurrence. Pour un usage intensif, envisager PostgreSQL.
- Le cache Streamlit (`ttl=60`) peut afficher la page vide jusqu'à ~1 minute
  après un import ; un rechargement suffit ensuite.

## 11. Règles de calcul (conformes à la feuille `Récap`)

- `solde = prélevé - injecté`
- `cumul net = Σ(injecté - prélevé)` (partition site/EAN)
- `injecté (EUR) = injectée (kWh) × prix horaire (€/kWh)`
- prix transformé : `prix_kwh = (-17.3 + 0.3 × prix_€/MWh) / 1000`
- prix horaire = moyenne des 4 quarts d'heure ; si < 4 points → `NULL` (sauf tolérance)
- cumuls mensuels remis à zéro au changement de mois
- règle de précédence : registre `Totals` si présent, sinon somme `rate 1 + rate 2`

## 12. Précision numérique

- Énergies stockées en **millièmes de kWh** (entiers, 3 décimales) ;
- Prix et montants stockés en **millionièmes d'euro** (entiers, 6 décimales) ;
- calculs intermédiaires en `Decimal` (arrondi au plus proche) ;
- affichage : kWh à 3 décimales, euros à 2 décimales.
