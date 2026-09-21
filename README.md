# bases-engine — service « base des bases » Elite Turf

Service **indépendant et en lecture seule** qui produit chaque matin, pour chaque course éligible, une
« échelle des bases » (1 à 4 chevaux à fixer en bases d'un champ réduit Quarté/Quinté) avec sa probabilité
de réussite, un indice de solidité (A/B/C) et une structure de ticket recommandée.

Il consomme les sorties **publiques** du moteur `Moriah12783/turf-engine` (SQLite `turf_bench.db` et
`benchmark_report.json` sur `main`, JSON `/resultats/`) exactement comme un partenaire tiers : aucune
écriture chez les autres, aucun secret d'autrui, aucun scraping HTML, aucun appel LLM.

Documents de référence : `BRIEF_SERVICE_BASES.md` (brief d'exécution), `CHARTE_DEVELOPPEUR_BASES.md`
(charte signée), `CHANGELOG.md` (toute évolution de formule ou de paramètre).

## Hébergement (état sprint 1)

Le service vit dans le sous-dossier autonome `bases-engine/` du dépôt `elite-turf` (aucune dépendance
vers le reste du dépôt). Il est prêt à être extrait tel quel vers un dépôt `bases-engine` dédié :
`git subtree split --prefix=bases-engine -b bases-engine-export`. Le workflow GitHub Actions (§8 du brief)
sera ajouté au sprint 2, dans le dépôt dédié (GitHub ne lit les workflows qu'à la racine).

## Installation

```bash
cd bases-engine
python3.11 -m pip install -r requirements.txt   # numpy, requests, pytest
python -m pytest -q                              # 26 tests, hors réseau (fixtures/snapshot/)
```

## Commandes

```bash
python -m bases_engine contract-check [--date J] [--no-network]   # tests de contrat §4.4 (bloquants)
python -m bases_engine backtest --since 2026-08-25 [--horizon T15|T_MATIN] [--until J] [--freeze-params]
python -m bases_engine show --date J [--horizon T_MATIN] [--retro]  # aperçu console de l'édition
python -m bases_engine matin | soir | hebdo                        # sprint 2 (non implémentés)
```

Options globales : `--sha <commit>` (défaut : `git ls-remote` de `main`), `--db <bases.db>`.

Variables d'environnement utiles :

| Variable | Rôle |
|---|---|
| `BASES_CACHE_DIR` | cache des instantanés `.cache/<sha>/` (défaut : `./.cache`) |
| `BASES_LOCAL_SNAPSHOT_DIR` | instantané déjà rempli (tests, hors-ligne) — court-circuite le réseau |
| `BASES_SOURCE_BASE_URL`, `BASES_DB_FILENAME` (`.gz` accepté), `BASES_REPORT_FILENAME` | source alternative (§12 : croissance de `turf_bench.db`) |
| `BASES_RESULTS_BASE_URL` | base des JSON de résultats publics |

## Pipeline (résumé)

1. `fetch.py` — SHA de `main` via `git ls-remote`, téléchargement **au SHA** (jamais `main` flottant), cache par SHA, budget 4 téléchargements/jour/fichier, client résultats ≤ 1 requête/minute avec vérification d'empreinte.
2. `contract.py` — tables/colonnes, `contract_version = 2` sur les prédictions du jour, sommes de probabilités, `historical_logs` (date J, clés, `publication_reason` connus), manifeste public. Un échec = arrêt, exit ≠ 0, aucune publication.
3. `eligibility.py` — miroir de la porte de publication (`publishable` + `OK` = autorité), prédiction `NEW_VALUE_ENGINE` conforme, départ > maintenant + 20 min, peloton ≥ 8, candidats = `editions_moteur.<horizon>.sel` (≥ 6 valides), cible top 5 si `QUINTE_PLUS`, sinon top 4.
4. `compute.py` + `core.py` — simulateur d'ordre à discount (lambdas littérature), échelles k = 1..4 pour m = 4 **et** m = 5, 5 meilleurs trios, recalibration post-sélection par (k, m), solidité par terciles gelés, structure v1. Graine fixée par (date, race_id).
5. `scoring.py` / `report.py` — back-test rétrospectif (rapport Markdown + JSON dans `rapports/backtest/`), calibrateurs, seuils.
6. `storage.py` — `bases.db` (runs, bases_editions, bases_results, calibration, params) ; `params.json` = export lisible de la version courante.

## Paramètres gelés (`params.json`, version 2026-09-21.1)

Lambdas `(1.0, 0.81, 0.65, 0.55, 0.50)` (pas de ré-estimation avant 1 500 courses), shrink 0,85 tant que
n < 150, seuils de solidité = terciles de P(3/3) recalibrée du back-test T15 (394 courses, commit `f1677b6`).
Ils ne changent plus jusqu'au verdict du protocole pré-enregistré ; la recalibration hebdomadaire créera
une nouvelle version sans toucher aux éditions passées.

## Résultats du back-test de référence (T15, 394 courses, 07/09 → 20/09/2026)

Échelle top 5 : 1 base 69,3 % · 2 bases 43,7 % · 3 bases 22,3 % · 4 bases 10,4 % · ≥ 2/3 : 70,8 %.
Trio joint identique aux 3 premiers du moteur dans 95,7 % des courses. Solidité A / B / C → 3/3 :
34,8 % / 18,3 % / 13,7 %. Détail : `rapports/backtest/2026-09-21_T15_since-2026-08-25.md`.

_Aucun chiffre retouché. Rendements non calculés tant que le mapping `rapports` n'est pas validé._
