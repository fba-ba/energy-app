# Plan — Application de suivi énergétique ORES/Elexys

> Fichier de questions préparatoires. Aucun développement n'a été démarré.
> Objectif : lever les ambiguïtés avant de générer `energy-app/`.

---

## 1. Constats d'analyse des deux classeurs fournis

### 1.1 Classeur « Rapport mensuel ORES - JUILLET - 0315 PM_COURBEVOIE.xlsx »
Feuilles : `Rapport mensuel`, `Mapping`, `Data` (16 734 lignes + en-tête), `Sites`, `Sources`, `tech`, `Prix électricité` (4 514 lignes), `Récap` (1 080 heures + en-tête).

- **`Data`** : 22 colonnes déjà présentes (pas 7). Répartition :
  - `RawDataPeriod = Minute` : 16 562 lignes, du **17/06/2026 21:00** au **31/07/2026 00:00**.
  - `RawDataPeriod = Day` : 172 lignes (agrégats journaliers, à exclure du récap horaire).
  - `VariableName` observés : `Consumption (A+) Totals`, `Consumption (+A) totals rate 1/2`, `Production (+A) Totals`, `Production (-A) totals rate 1/2` (+ variantes `rate 1/2` pour les lignes Day).
  - **Vérifié** : `Totals = rate 1 + rate 2` exactement (aucun écart). La règle de précédence « Totals si présent, sinon somme des rates » est donc correcte.
  - Incohérences de nommage source : `(A+)` vs `(+A)` et `(+A)` vs `(-A)` selon les registres. La classification `Consumption`/`Production` (insensible à la casse) suffit à les départager.

- **`Prix électricité`** : contient déjà les prix Elexys (Date, Heure, Euro, PrixKWh, Prix Moy/Heure, Heure Entière, Clé), du **15/06/2026** au **31/07/2026**.
  - Confirme la formule : `PrixKWh = (-17.3 + 0.3 × Euro) / 1000`.
  - Ex. `165.13 €/MWh` → `0.03223899999999999` (≈ `0.032239`), moyenne horaire `0.03352`. **Conforme aux tests de référence.**
  - L'URL Elexys inscrite dans l'en-tête : `…?from=2026-06-15&until=2026-06-30`.

- **`Récap`** : exactement **21 colonnes** dans l'ordre attendu, **1 080 heures continues** du 17/06/2026 00:00 au 31/07/2026 23:00.
  - Formules validées sur les lignes de référence (17/06 21:00, 22:00, 01/07 00:00, 31/07 23:00) :
    - `Solde = Prél - Inj` ; `Cumul Net = Σ(Inj - Prél)` (positif = net injecté) ;
    - `Injecté (EUR) = Injectée (kWh) × Prix Horaire (€/kWh)` ;
    - **cumuls mensuels remis à zéro au changement de mois** (test n°9 validé) ;
    - `17/06 21:00` → prél. 0.010 / inj. 2.430 / prix 0.03090175 / valeur 0.07509125 ✅ ;
    - `31/07 23:00` → prix 0.03352 ✅.

### 1.2 Classeur « Rapport mensuel ORES - 2026-08-03 - 0306 PM.xlsx »
Feuilles : `Rapport mensuel`, `Mapping`, `Data` (11 642 lignes + en-tête), `Sites`, `Sources`, `tech`. **Pas de `Prix électricité`, pas de `Récap`.**
- `Data` couvre **juillet uniquement** (01/07/2026 → 31/07/2026 00:00). Mêmes 22 colonnes et mêmes variables.
- → **Chevauchement avec le fichier JUILLET sur juillet.** L'import doit donc être idempotent et dédupliqué entre fichiers.

### 1.3 Points d'attention relevés
- **Heures sans donnée** : le Récap d'origine affiche `0` pour les heures sans mesure (ex. 31/07 de 01:00 à 23:00, 44 heures au total). L'app doit, elle, distinguer « manquant » de « zéro réel ».
Oui, l'app ne doit pas générer de données si Récap si il n'y a pas de données brutes relatives dans Data
- **`Clé Prix`** : le classeur utilise un `u` minuscule (`17/06/2026|21u00`), alors que la requête écrit `Hu00`.
- **`Label Heure`** : format `D/M Hh` (ex. `17/6 21h`). **`Label Axe X`** : `D/M\n0h` à l'heure 0 de chaque jour, sinon `Hh`.
- **Pas de changement d'heure** dans la période (juin–juillet = heure d'été), mais le code devra le gérer (test n°12).
- Les dates du classeur sont des datetimes naïfs représentant **Europe/Brussels**.

---

## 2. Questions à trancher avant développement

### A. Données d'entrée
1. **Fichiers à importer** : l'app doit-elle importer un seul classeur (ex. le JUILLET, qui contient Récap + Prix + Data), ou **fusionner plusieurs rapports mensuels** (un fichier ORES par mois, comme les deux fournis) avec déduplication ? Le JUILLET est-il le fichier de référence pour valider la conformité à `Récap` ?
Non, le fichier avec les données brut est D:\DevSources\Ores_Digest\Rapport mensuel ORES - 2026-08-03 - 0306 PM.xlsx ; il s'agit d'un exemple. On en reçoit un par mois qu'on doit être capable de charger dans l'App.
Au moment du chargement, l'app doit être capable de générer les données qu'on retrouve dans `Récap`. Si les prix pour la nouvelle période chargées ne sont pas encore connus, il faut aller chercher les prix sur Elexys.
2. **Enrichissement 7 → 22 colonnes** : les deux fichiers ont déjà 22 colonnes. Faut-il implémenter l'étape d'enrichissement depuis une version « brute » à 7 colonnes, ou importer directement les 22 colonnes telles quelles ? (Je propose : importer les 22 colonnes, et être tolérant si certaines manquent.) ; Il faut enrichir à partir de l'onglet `Data` de 7 colonnes présent dans D:\DevSources\Ores_Digest\Rapport mensuel ORES - 2026-08-03 - 0306 PM.xlsx
3. **Prix** : Elexys en ligne est-il la source **unique et obligatoire**, ou l'app peut-elle aussi importer l'onglet `Prix électricité` déjà présent dans le classeur (source alternative / fixture) ?
elexys est la source unique et obligatore. Le fichier D:\DevSources\Ores_Digest\Rapport mensuel ORES - JUILLET - 0315 PM_COURBEVOIE.xlsx est déjà le résultat des transformations des données brutes.

### B. Règles métier
4. **Format `Clé Prix`** : reproduire le classeur (`DD/MM/YYYY|Hu00` avec `u` minuscule, ex. `17/06/2026|21u00`) ou suivre strictement la requête (`H` majuscule) ? *(Je recommande `u` minuscule pour être identique au Récap.)*
ok
5. **Heures manquantes** : pour l'export `recap_hourly`, reproduire exactement le Récap (affichage `0`) ou distinguer NULL + indicateur de complétude (mon approche recommandée : stocker NULL, exposer un flag, avec une option d'export « compatible Récap » qui force 0) ?
ok
6. **Plage de la série horaire** : continue de 00:00 à 23:00 sur toute la plage utile (comme le Récap, 17/06 00:00 → 31/07 23:00), ou bornée au min/max des données réellement présentes (17/06 21:00 → 31/07 00:00) ?
Bornée aux données réellement présentes dans le fichier des données brutes.
7. **Cumul mensuel de juin** : les données commencent le 17/06. Le cumul mensuel de juin doit-il simplement démarrer à la première donnée (17/06) avec un indicateur « mois partiel », ou faut-il un comportement particulier ?
Les cumuls mensuels prennent les données présentes pour le mois (avec un tooltip - "missing data" )

### C. Architecture & déploiement (serveur distant)
8. **Frontend/backend** : la stack impose Streamlit (UI) + FastAPI (API). Pour un serveur distant, il faut **deux processus** (Streamlit :8501, FastAPI :8000). Quelle option veux-tu ?
   - (a) Streamlit seul comme interface principale (FastAPI en option/arrière-plan) ;
   - (b) les deux exposés derrière un reverse proxy ;
   - (c) Docker Compose (conteneur API + conteneur UI).
   As-tu des contraintes (Docker, systemd, Nginx/Caddy, **authentification** requise ou accès restreint/IP) ?
   option (c); pas d'authentification pour le moment
9. **Usage** : Streamlit est pensé pour un usage personnel / petit nombre d'utilisateurs (pas un vrai frontend multi-utilisateurs). Confirme que c'est adapté, sinon je propose une alternative (petite SPA servie par FastAPI).
C'est ok.

### D. Technique
10. **Précision numérique** : SQLite n'a pas de DECIMAL natif. Je propose de stocker les énergies en **millièmes de kWh** et les montants/prix en **millionièmes d'euro** (colonnes INTEGER), conversion à l'affichage. Valides-tu (ou préfères-tu `Numeric` SQLAlchemy) ?
ok
11. **Environnement** : je crée un `venv` + `pyproject.toml` (uv/pip). L'interpréteur système détecté ici est **Python 3.14** — acceptable, ou faut-il cibler strictement 3.12 ? Docker souhaité ?
ok . Docker souhaité.
12. **Tests Elexys** : tests 100 % hors-ligne avec fixtures (recommandé) + un test d'intégration optionnel marqué `@pytest.mark.elexys_live` qui contacte le vrai site — OK ?
Ce test n'est pas optionnel

### E. Livraison
13. **Emplacement** : je génère le projet dans `d:\DevSources\Ores_Digest\energy-app\` (sous-dossier) ou directement à la racine du workspace ?
A la racine
14. **Fixtures** : puis-je embarquer des copies des deux classeurs réels dans `tests/fixtures/` pour les tests d'intégration (données réelles incluses) — ou préfères-tu des classeurs synthétiques anonymisés ?
non, tu peux utiliser les 2 classeurs. ( données brutes : D:\DevSources\Ores_Digest\Rapport mensuel ORES - 2026-08-03 - 0306 PM.xlsx ; résultats dans `Récap` de D:\DevSources\Ores_Digest\Rapport mensuel ORES - JUILLET - 0315 PM_COURBEVOIE.xlsx)

---

## 3. Décisions que je propose d'appliquer par défaut (dites-moi si vous en changez)

- Structure en couches : `ingestion` / `domaine` / `persistance` (repositories) / `services` / `api` / `dashboard`.
- Import idempotent : dédup par hash `(source, EAN, horodatage, variable, granularité)` + transaction atomique.
- Règle de précédence prix : `price_complete = true` ssi 4 quarts d'heure ; sinon moyenne disponible dans un champ distinct + `NULL` en prix officiel.
- Journalisation structurée (`structlog` ou `logging` JSON) ; messages d'erreur en français ; aucun secret dans le dépôt (`.env.example` seulement).
- README, Makefile, Alembic initialisé, tests pytest + linting ruff.
