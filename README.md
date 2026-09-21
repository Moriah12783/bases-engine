# bases-engine — service « base des bases » Elite Turf

Service **indépendant et en lecture seule** qui produit chaque matin, pour chaque course éligible, une
« échelle des bases » (1 à 4 chevaux à fixer en bases d'un champ réduit Quarté/Quinté) avec sa probabilité
de réussite, un indice de solidité (A/B/C) et une structure de ticket recommandée.

Il consomme les sorties **publiques** du moteur `Moriah12783/turf-engine` (SQLite `turf_bench.db` et
`benchmark_report.json` sur `main`, JSON `/resultats/`) exactement comme un partenaire tiers : aucune
écriture chez les autres, aucun secret d'autrui, aucun scraping HTML, aucun appel LLM.

Documents de référence : `BRIEF_SERVICE_BASES.md` (brief d'exécution), `CHARTE_DEVELOPPEUR_BASES.md`
(charte signée), `CHANGELOG.md` (toute évolution de formule ou de paramètre).

## Hébergement

Dépôt dédié `Moriah12783/bases-engine` (extraction du sous-dossier `bases-engine/` d'`elite-turf` par
`git subtree split`). Le workflow `.github/workflows/bases.yml` ne tourne qu'à la racine de ce dépôt.

## Mise en service (sprint 2) — actions de Steph

1. Créer le dépôt privé `Moriah12783/bases-engine` et y pousser l'extraction ; activer « Watch → Custom → Actions » pour recevoir les échecs de workflow.
2. Secrets : `CLOUDFLARE_API_TOKEN_BASES` (Pages : Edit), `CLOUDFLARE_ACCOUNT_ID`, `SHADOW_TOKEN` (32 caractères aléatoires). Variables : `PUBLICATION_MODE=shadow`, `NOTIFY_CHANNELS=summary,journal`.
3. Lancer manuellement le workflow avec la commande `pages-init` (crée le projet Pages `bases-elite-turf`, idempotent), puis rattacher `bases.elite-turf.fr` dans le tableau de bord Pages.
4. Lancer manuellement le workflow avec la commande `contract-check` (Actions → bases → Run workflow). Tant qu'il ne passe pas, les crons restent commentés dans `bases.yml`.
5. Sur `contract-check` vert : décommenter le bloc `schedule` (décision écrite) et modifier soi-même une minute d'une ligne cron pour en devenir l'auteur (destinataire des notifications d'échec), puis premier `matin` en mode ombre.
6. Consulter la page ombre : `https://bases.elite-turf.fr/shadow/<SHADOW_TOKEN>/`.

## Installation

```bash
cd bases-engine
python3.11 -m pip install -r requirements.txt   # numpy, requests, pytest
python -m pytest -q                              # tests hors réseau (fixtures/snapshot/, fixtures/resultats/)
```

## Commandes

```bash
python -m bases_engine contract-check [--date J] [--no-network]   # tests de contrat §4.4 (bloquants)
python -m bases_engine backtest --since 2026-08-25 [--horizon T15|T_MATIN] [--until J] [--freeze-params]
python -m bases_engine show --date J [--horizon T_MATIN] [--retro]  # aperçu console de l'édition
python -m bases_engine matin [--date J] [--dry-run] [--no-network] [--shadow-token T] [--now ISO]
python -m bases_engine soir  [--date J] [--no-network]
python -m bases_engine hebdo                                       # sprint 3 (non implémenté)
```

Hors-ligne (`--no-network`) avec `BASES_RESULTS_LOCAL_DIR=fixtures/resultats`, le manifeste et les
journées sont lus dans la fixture (format de production identique) au lieu de `prono.elite-turf.fr`.

Options globales : `--sha <commit>` (défaut : `git ls-remote` de `main`), `--db <bases.db>`.

Variables d'environnement utiles :

| Variable | Rôle |
|---|---|
| `BASES_CACHE_DIR` | cache des instantanés `.cache/<sha>/` (défaut : `./.cache`) |
| `BASES_LOCAL_SNAPSHOT_DIR` | instantané déjà rempli (tests, hors-ligne) — court-circuite le réseau |
| `BASES_SOURCE_BASE_URL`, `BASES_DB_FILENAME` (`.gz` accepté), `BASES_REPORT_FILENAME` | source alternative (§12 : croissance de `turf_bench.db`) |
| `BASES_RESULTS_BASE_URL` | base des JSON de résultats publics (`file://<dossier>` accepté pour une fixture) |

## Pipeline (résumé)

1. `fetch.py` — SHA de `main` via `git ls-remote`, téléchargement **au SHA** (jamais `main` flottant), cache par SHA, budget 4 téléchargements/jour/fichier, client résultats ≤ 1 requête/minute avec vérification d'empreinte.
2. `contract.py` — tables/colonnes, `contract_version = 2` sur les prédictions du jour, sommes de probabilités, `historical_logs` (date J, clés, `publication_reason` connus), manifeste public. Un échec = arrêt, exit ≠ 0, aucune publication.
3. `eligibility.py` — miroir de la porte de publication (`publishable` + `OK` = autorité), prédiction `NEW_VALUE_ENGINE` conforme, départ > maintenant + 20 min, peloton ≥ 8, candidats = `editions_moteur.<horizon>.sel` (≥ 6 valides), cible top 5 si `QUINTE_PLUS`, sinon top 4.
4. `compute.py` + `core.py` — simulateur d'ordre à discount (lambdas littérature), échelles k = 1..4 pour m = 4 **et** m = 5, 5 meilleurs trios, recalibration post-sélection par (k, m), solidité par terciles gelés, structure v1. Graine fixée par (date, race_id).
5. `scoring.py` / `report.py` — back-test rétrospectif (rapport Markdown + JSON dans `rapports/backtest/`), calibrateurs, seuils.
6. `storage.py` — `bases.db` (runs, bases_editions, bases_results, calibration, params, results_manifest, abstentions, journal_days) ; `params.json` = export lisible de la version courante.
7. `pipeline.py` — `matin` / `soir` (§4, §7) ; `publish.py` — site, JSON contrat, palmarès, fiabilité ; `notify.py` — résumé de job, journal, Telegram inactif.

## Paramètres gelés (`params.json`, version 2026-09-21.2)

Lambdas `(1.0, 0.81, 0.65, 0.55, 0.50)` (pas de ré-estimation avant 1 500 courses). Recalibration
post-sélection **à paliers** selon n par (k, cible) : fixe 0,85 (n < 150) → ratio borné [0,60 ; 1,00]
(< 300) → logit-linéaire (< 1000) → isotonique. Seuils de solidité = terciles de P(3/3) recalibrée du
back-test **T_MATIN** (339 courses, commit `f1677b6`) : top5 A ≥ 0,2275 / B ≥ 0,1466 ; top4 A ≥ 0,1344 /
B ≥ 0,0781. Ils ne changent plus jusqu'au verdict du protocole pré-enregistré ; la recalibration
hebdomadaire créera une nouvelle version sans toucher aux éditions passées.

## Résultats du back-test de référence (T_MATIN, 339 courses, 08/09 → 20/09/2026)

Échelle top 5 : 1 base 63,4 % · 2 bases 33,3 % · 3 bases 20,1 % · 4 bases 9,1 % · ≥ 2/3 : 61,1 %.
Trio joint identique aux 3 premiers du moteur dans 92,3 % des courses ; 3/3 : trio joint 20,1 % ·
3 premiers du moteur 19,2 % · 3 plus courtes cotes 18,6 %. Solidité A / B / C → 3/3 : 33,6 % / 15,9 % /
10,6 %. Détail : `rapports/backtest/2026-09-21_T_MATIN_since-2026-08-25.md` ; référence secondaire T15
(394 courses) : `rapports/backtest/2026-09-21_T15_since-2026-08-25.md`.

_Aucun chiffre retouché. Rendements non calculés tant que le mapping `rapports` n'est pas validé._
