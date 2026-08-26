# Prompt pour générer une application de suivi énergétique

## Rôle

Tu es un ingénieur logiciel senior spécialisé en Python, traitement de données énergétiques, SQLite et visualisation. Crée une application locale complète, robuste, testée et documentée à partir d'un classeur Excel fourni par l'utilisateur.

Ne te contente pas d'expliquer : génère tous les fichiers du projet, le code exécutable, les migrations SQL, les tests, une configuration d'exemple et un README avec les commandes exactes.

## Objectif

Construire une application qui :

1. importe la feuille **`Data`** d'un classeur Excel ; ( exemple : D:\DevSources\Ores_Digest\Rapport mensuel ORES - 2026-08-03 - 0306 PM.xlsx ,onglet caché 'Data' )
2. récupère les prix quart-horaires sur Elexys ;
3. stocke les données dans une base **SQLite** ;
4. produit une table ou vue horaire fonctionnellement identique à la feuille **`Récap`**  (D:\DevSources\Ores_Digest\Rapport mensuel ORES - JUILLET - 0315 PM_COURBEVOIE.xlsx, voir onglet "Récap" ) ;
5. calcule des totaux mensuels ;
6. affiche des graphiques clés dans une interface locale ;
7. permet de relancer l'import sans créer de doublons.
8. L'application est une application web qui sera déployée sur mon serveur distant (est-ce qu'il faut un frontend et un backend ? )

## Stack technique imposée

- Python 3.12+
- SQLite
- SQLAlchemy 2.x et Alembic
- pandas + openpyxl pour l'import Excel
- FastAPI pour l'API
- Streamlit pour l'interface utilisateur
- Plotly pour les graphiques
- httpx + BeautifulSoup pour Elexys
- Playwright uniquement si le contenu est rendu en JavaScript
- pytest pour les tests
- ruff pour le linting
- pydantic-settings pour la configuration

Utiliser `DECIMAL` ou des entiers en millièmes/millionièmes pour les calculs financiers et énergétiques sensibles. Ne jamais stocker les nombres sous forme de chaînes formatées.

## Données Excel d'entrée

Le chemin du classeur doit être fourni par argument CLI ou variable d'environnement. Ne jamais coder le nom du fichier en dur.

La feuille **`Data`** contient actuellement 7 colonnes () et environ 16 735 lignes, mais le code doit accepter un nombre quelconque de lignes. Il faut enrichir cette feuille pour avoir 22 colonnes.
Les données **`Data`** sont données par quart d'heure; les données **`Récap`** sont données par heure :

```
SourceId
SiteName
SourceName
EanNumber
MeterNumber
RawDataPeriod
DataTime
Unit
Conso
VariableName
Granularity
-
Aggregation
Year
Month
Day
Hour
Minute
Second
DayOfWeek
WeekNumber
RawDataPeriodFrequency
```

Exemples :

```text
RawDataPeriod = Day ou Minute
DataTime = date Excel ou date/heure
Unit = Kilowatt-hour
Conso = valeur numérique en kWh
VariableName = Consumption (+A) rate 1
VariableName = Consumption (+A) rate 2
VariableName = Production (-A) totals rate 1
VariableName = Production (-A) totals rate 2
```

### Normalisation attendue

- Convertir correctement les numéros de série Excel en dates/heures.
- Interpréter les dates dans le fuseau `Europe/Brussels`.
- Conserver la date source et la date normalisée.
- Pour le récapitulatif horaire, utiliser les enregistrements d'intervalle (`RawDataPeriod = Minute`) et non les agrégats journaliers.
- Classer les variables sans dépendre de la casse :
  - contient `Consumption` ou correspond à `Energie prélevée` → **prélèvement** ;
  - contient `Production` ou correspond à `Energie injectée` → **injection**.
- Additionner les registres tarifaires complémentaires `rate 1` et `rate 2` d'une même direction et d'un même intervalle.
- Ne pas additionner simultanément une valeur `Totals` et ses composantes si elles représentent la même énergie.
- Appliquer une règle de précédence explicite et testée : valeur totale unique si disponible, sinon somme des composantes tarifaires.
- Dédupliquer avec une clé comprenant au minimum : source, EAN, horodatage, variable et granularité.
- Placer dans une table d'anomalies les lignes sans horodatage, unité ou valeur exploitable.
- Ne jamais ignorer silencieusement les anomalies.
- Conserver les prix négatifs et les injections nulles.
- Gérer les journées de 23 ou 25 heures liées au changement d'heure.

## Source des prix Elexys

URL paramétrée :

```text
https://www.elexys.be/fr/insights/quarter-hourly-belpex-day-ahead-spot-be?from=YYYY-MM-DD&until=YYYY-MM-DD
```

La page présente des lignes **Date / Heure / Euro** au quart d'heure et propose un export Excel.

Privilégier l'export structuré s'il est accessible de façon stable. Sinon, parser le tableau HTML. Utiliser Playwright uniquement en dernier recours.

Exigences :

- Déterminer automatiquement `from` et `until` à partir de la période des données importées.
- Permettre de surcharger ces dates en CLI.
- Gérer les délais réseau, les retries exponentiels, un User-Agent explicite et un cache local.
- Journaliser l'URL, la date de récupération et le statut.
- Ne jamais inventer de prix si Elexys ne répond pas.
- Un prix manquant doit rester `NULL` et être signalé, jamais remplacé par zéro.
- Stocker le prix brut Elexys en **€/MWh**.
- Stocker également le prix transformé en **€/kWh** selon la formule utilisée dans le classeur :

```
prix_kwh = (-17.3 + 0.3 × prix_elexys_eur_mwh) / 1000
```

- Calculer le prix horaire comme la moyenne arithmétique des quatre prix quart-horaires transformés.
- Si moins de quatre quarts d'heure sont présents :
  - conserver le nombre de points ;
  - calculer éventuellement la moyenne disponible dans un champ distinct ;
  - définir `price_complete = false` ;
  - exposer `NULL` comme prix officiel dans `recap_hourly`, sauf option explicite de tolérance.
- Conserver la provenance et la formule de transformation dans les métadonnées.

Source :  
https://www.elexys.be/fr/insights/quarter-hourly-belpex-day-ahead-spot-be

## Modèle SQLite

Créer au minimum les tables suivantes.

### `energy_readings_raw`

Données importées telles que reçues, plus :

- `id`
- `import_batch_id`
- `source_row_number`
- `data_time_raw`
- `data_time_local`
- `data_time_utc`
- `direction` : `withdrawal` ou `injection`
- `value_kwh`
- `dedup_hash`
- `created_at`

### `spot_prices_quarter_hourly`

- `timestamp_local`
- `timestamp_utc`
- `price_eur_mwh_raw`
- `price_eur_kwh_transformed`
- `source_url`
- `retrieved_at`
- contrainte unique sur l'horodatage et la source

### `energy_hourly`

- `timestamp_local` — début de l'heure
- `site_name`
- `ean_number`
- `withdrawn_kwh`
- `injected_kwh`
- `balance_withdrawn_minus_injected_kwh`
- `spot_price_eur_kwh`
- `injected_value_eur`
- `energy_point_count`
- `price_point_count`
- indicateurs de complétude
- contrainte unique par site, EAN et heure

### `monthly_totals`

- `month` au format `YYYY-MM-01`
- `site_name`
- `ean_number`
- `withdrawn_kwh`
- `injected_kwh`
- `net_injected_minus_withdrawn_kwh`
- `injected_value_eur`
- `average_spot_price_eur_kwh`
- `negative_price_hours`
- `hours_with_missing_energy`
- `hours_with_missing_price`
- contrainte unique par site, EAN et mois

### Tables techniques

- `import_batches`
- `data_quality_issues`
- `app_metadata`

Créer les index adaptés aux recherches par date, mois, site et EAN.

## Vue compatible avec la feuille `Récap`

Créer une vue SQL `recap_hourly` et un endpoint d'export CSV/XLSX avec exactement les 21 colonnes suivantes, dans cet ordre :

```text
Date-Heure
Prélevée (kWh)
Injectée (kWh)
Solde (Prél-Inj)
Label Heure
Cumul Net (kWh)
Cumul Prélevée
Cumul Injectée
Prélevée (kWh) [copie]
Injectée (kWh) [copie]
Cumul Net [copie]
Cumul Prélevée [copie]
Cumul Injectée [copie]
Label Axe X
Cumul Injecté (EUR)
Clé Prix
Prix Horaire (€/kWh)
Injecté (EUR)
Cumul mensuel prélevé (kWh)
Cumul mensuel injecté (kWh)
Cumul mensuel injecté (EUR)
```

SQLite exige des noms uniques. Utiliser des noms techniques uniques dans la vue, puis appliquer les libellés ci-dessus à l'export.

### Règles de calcul exactes

Pour chaque heure `t` :

```text
withdrawn_kwh =
    somme des prélèvements dont timestamp ∈ [t, t + 1 heure[

injected_kwh =
    somme des injections dont timestamp ∈ [t, t + 1 heure[

balance_withdrawn_minus_injected_kwh =
    withdrawn_kwh - injected_kwh

cumulative_net_kwh =
    somme cumulée de (injected_kwh - withdrawn_kwh)

cumulative_withdrawn_kwh =
    somme cumulée de withdrawn_kwh

cumulative_injected_kwh =
    somme cumulée de injected_kwh

injected_value_eur =
    injected_kwh × hourly_price_eur_kwh

cumulative_injected_value_eur =
    somme cumulée de injected_value_eur

monthly_withdrawn_kwh =
    cumul de withdrawn_kwh depuis le premier jour du mois

monthly_injected_kwh =
    cumul de injected_kwh depuis le premier jour du mois

monthly_injected_value_eur =
    cumul de injected_value_eur depuis le premier jour du mois

price_key =
    DD/MM/YYYY|Hu00
```

Les cumuls globaux sont partitionnés par site et EAN, puis triés par horodatage.

Les cumuls mensuels sont partitionnés par site, EAN et mois.

Générer une série horaire continue entre le minimum et le maximum des données utiles afin que les heures sans mesure soient visibles.

Distinguer une vraie mesure nulle d'une mesure manquante.

## Totaux mensuels

L'application doit fournir :

- une page « Synthèse mensuelle » ;
- un tableau filtrable par mois, site et EAN ;
- un export CSV et XLSX ;
- des cartes KPI :
  - prélèvement ;
  - injection ;
  - solde net ;
  - valeur de l'injection ;
  - prix moyen ;
- une comparaison avec le mois précédent, en valeur et en pourcentage ;
- un indicateur de complétude des données.

Ne pas sommer les cumuls horaires pour produire les totaux mensuels. Sommer uniquement les flux horaires élémentaires.

## Graphiques clés

Créer au minimum :

1. **Courbes horaires prélèvement/injection**
   - deux séries en kWh ;
   - plage de dates filtrable.

2. **Énergie cumulée**
   - cumul prélevé ;
   - cumul injecté ;
   - cumul net.

3. **Énergie mensuelle**
   - barres groupées prélevé contre injecté pour chaque mois.

4. **Valeur de l'injection**
   - cumul en euros ;
   - montant mensuel.

5. **Prix et injection**
   - prix horaire en €/kWh ;
   - injection en kWh sur axe secondaire.

6. **Profil moyen par heure**
   - moyenne du prélèvement et de l'injection pour les heures 0 à 23.

Afficher clairement les prix négatifs et les périodes incomplètes.

Éviter les graphiques 3D.

Tous les graphiques doivent réagir aux filtres site, EAN, mois et plage de dates.

## API et commandes

Créer au minimum les commandes suivantes :

```
python -m app.cli init-db
python -m app.cli import-excel --file chemin.xlsx --sheet **Data**
python -m app.cli fetch-prices --from YYYY-MM-DD --until YYYY-MM-DD
python -m app.cli rebuild-aggregates
python -m app.cli validate
uvicorn app.api:app --reload
streamlit run app/dashboard.py
pytest
```

Endpoints souhaités :

```text
GET /health
POST /imports/excel
POST /prices/sync
GET /recap/hourly
GET /totals/monthly
GET /quality/issues
GET /exports/recap.xlsx
GET /exports/monthly.xlsx
```

## Qualité, sécurité et robustesse

- Transactions atomiques pour chaque import.
- Imports idempotents.
- Contraintes d'unicité et clés étrangères actives.
- Journalisation structurée.
- Validation stricte des types et plages de dates.
- Protection contre les fichiers trop volumineux et les chemins non autorisés.
- Aucun secret dans le dépôt.
- Messages d'erreur compréhensibles en français.
- Interface et README en français.
- Code organisé par couches :
  - ingestion ;
  - domaine ;
  - persistance ;
  - services ;
  - API ;
  - interface.
- Ne pas utiliser un notebook comme application principale.

## Tests obligatoires

Écrire des tests unitaires et d'intégration couvrant au minimum :

1. conversion d'une date Excel en `Europe/Brussels` ;
2. classement prélèvement/injection à partir de `VariableName` ;
3. agrégation de quatre quarts d'heure vers une heure ;
4. addition correcte de `rate 1` et `rate 2` sans double comptage ;
5. transformation du prix : `165.13 €/MWh` doit produire `0.032239 €/kWh` ;
6. moyenne horaire des quatre quarts d'heure ;
7. conservation d'un prix négatif ;
8. calcul `Injecté (EUR) = Injectée (kWh) × Prix Horaire (€/kWh)` ;
9. remise à zéro des cumuls mensuels au changement de mois ;
10. idempotence d'un second import identique ;
11. détection des heures de prix incomplètes ;
12. comportement aux changements d'heure ;
13. concordance entre `monthly_totals` et la somme des flux de `energy_hourly` ;
14. export des 21 colonnes dans le bon ordre.

Ajouter un test de référence avec les exemples suivants issus du classeur :

```text
17/06/2026 21:00 :
prélevé = 0.010 kWh
injecté = 2.430 kWh
prix horaire = 0.030902 €/kWh
valeur injectée ≈ 0.075092 EUR avant arrondi d'affichage

31/07/2026 23:00 :
prix horaire = 0.033520 €/kWh
```

Le stockage doit conserver la précision complète.

L'interface peut afficher :

- les kWh avec 3 décimales ;
- les euros avec 2 décimales.

## Livrables attendus

Produire l'arborescence complète, par exemple :

```text
energy-app/
├── app/
│   ├── api.py
│   ├── cli.py
│   ├── config.py
│   ├── dashboard.py
│   ├── db.py
│   ├── models.py
│   ├── schemas.py
│   ├── ingestion/
│   │   ├── excel.py
│   │   └── elexys.py
│   ├── services/
│   │   ├── aggregation.py
│   │   ├── exports.py
│   │   └── quality.py
│   └── repositories/
├── alembic/
├── tests/
├── .env.example
├── pyproject.toml
├── README.md
└── Makefile
```

Dans ta réponse :

1. commence par l'arborescence ;
2. fournis ensuite chaque fichier dans un bloc de code avec son chemin ;
3. termine par les commandes d'installation et d'exécution ;
4. indique les hypothèses restantes ;
5. n'abrège pas les fichiers essentiels avec « etc. » ou « à compléter » ;
6. assure-toi que le projet démarre réellement après copie des fichiers.

## Critères d'acceptation

Le travail est terminé uniquement si :

- un classeur contenant la feuille `Data` peut être importé sans modification manuelle ;
- `app.db` est créé automatiquement ;
- un second import ne crée pas de doublons ;
- les prix Elexys sont enregistrés avec leur provenance ;
- la vue horaire reproduit les règles de calcul de `Récap` ;
- les totaux mensuels concordent avec les données horaires ;
- les six graphiques fonctionnent avec les filtres ;
- les données manquantes sont visibles et ne sont pas transformées silencieusement en zéro ;
- tous les tests passent.

## Notes issues du classeur d'origine

- `Data` contient des données journalières et des intervalles au quart d'heure, malgré la valeur `Minute` dans `RawDataPeriod`.
- La feuille `Récap` observée couvre 1 080 heures, du 17/06/2026 00:00 au 31/07/2026 23:00.
- Le prix horaire est obtenu après transformation de chaque prix quart-horaire, puis calcul de la moyenne des quatre valeurs.
- La valeur financière comptabilisée concerne l'énergie injectée, et non l'énergie prélevée.
- Les prix spot peuvent être négatifs : l'injection peut donc produire une valeur financière négative.