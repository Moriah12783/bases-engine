# bases-engine — service « base des bases » Elite Turf

Service **indépendant et en lecture seule** qui produit chaque matin, pour chaque course éligible, une
« échelle des bases » (1 à 4 chevaux à fixer en bases d'un champ réduit Quarté/Quinté) avec sa probabilité
de réussite, un indice de solidité (A/B/C) et une structure de ticket recommandée.

Depuis le 25/09/2026, il lit la **base vivante du moteur sur R2** (objet `turf_bench.db` du bucket `turf-engine-data`,
lecture seule, empreinte et intégrité vérifiées) et les JSON publics `/resultats/`, exactement comme un partenaire tiers : aucune
écriture chez les autres, aucun secret d'autrui, aucun scraping HTML, aucun appel LLM.

Documents de référence : `BRIEF_SERVICE_BASES.md` (brief d'exécution), `CHARTE_DEVELOPPEUR_BASES.md`
(charte signée), `CHANGELOG.md` (toute évolution de formule ou de paramètre).

## Hébergement

Dépôt dédié `Moriah12783/bases-engine` (extraction du sous-dossier `bases-engine/` d'`elite-turf` par
`git subtree split`). Le workflow `.github/workflows/bases.yml` ne tourne qu'à la racine de ce dépôt.

## Mise en service — ordre à respecter (décision mentor du 21/09/2026)

1. Créer le dépôt privé `Moriah12783/bases-engine` (fait), activer « Watch → Custom → Actions » ; poser les secrets `CLOUDFLARE_API_TOKEN_BASES` (Pages : Edit), `CLOUDFLARE_ACCOUNT_ID`, `SHADOW_TOKEN` (32 caractères aléatoires) et les variables `PUBLICATION_MODE=shadow`, `NOTIFY_CHANNELS=summary,journal`.
2. **`pages-init`** (Actions → bases → Run workflow) : crée le projet Pages `bases-elite-turf`, idempotent.
3. **Domaine** : rattacher `bases.elite-turf.fr` au projet dans le tableau de bord Pages.
4. **`contract-check` manuel** : premier test réseau complet (manifeste public inclus).
5. **Une répétition `matin` manuelle, un jour de courses** : marquée `repetition = 1`, hors palmarès et verdict ; sert à vérifier le résumé de job, le journal et la page ombre.
6. **Validation du rapport T_MATIN par le mentor** (`rapports/backtest/2026-09-21_T_MATIN_since-2026-08-25.md`, `params.json` v2026-09-21.2). Rien ne s'active avant ce retour.
7. Steph **décommente le bloc `schedule`** de `bases.yml` et **modifie une minute** d'une ligne cron (il devient l'auteur des lignes cron, donc le destinataire des notifications d'échec).
8. **Début du protocole** : fixé automatiquement par le premier `matin` planifié (date écrite dans `PROTOCOLE_PREENREGISTRE.md` et `bases.db`). `hebdo` tourne chaque lundi à partir de là.

Page ombre : `https://bases.elite-turf.fr/shadow/<SHADOW_TOKEN>/`.

## Métronome (déclencheur primaire, Worker Cloudflare)

Les crons GitHub sont servis « au mieux » (retards de plusieurs heures, occurrences sautées). Un Worker
Cloudflare `bases-metronome` (`metronome/`) frappe `workflow_dispatch` de `bases.yml` à la minute :
`5 9,11,13 * * *` matin (09:05, 11:05, 13:05 ; répétition si la journée est servie), `3 22 * * *` soir, `28 7 * * MON` hebdo, `18 11-21 * * *` resultats (UTC), deux minutes avant les crons GitHub qui
restent le filet. Déploiement : Actions → « Métronome · déploiement » (secrets `CLOUDFLARE_API_TOKEN_METRONOME`,
`CLOUDFLARE_ACCOUNT_ID`, `METRONOME_GH_TOKEN`). Exploitation : `docs/RUNBOOK.md`.

## Budget GitHub Actions (estimation, dépôt privé : 2 000 minutes/mois)

| Exécution | Par jour | Durée facturée (arrondie à la minute) | Minutes/jour |
|---|---:|---:|---:|
| `resultats` (passe horaire 11 h → 21 h UTC) | 11 | ≈ 1 min (checkout, pip en cache, lecture d'un JSON, régénération des pages) | 11 |
| `matin` + rattrapage 09:35 | 2 | ≈ 2 min (téléchargement de l'instantané 30 Mo + 20 courses × 40 000 simulations) | 4 |
| `soir` (+ rattrapage 23:40 si activé) | 1 à 2 | ≈ 3 à 5 min (instantané, mesure T90/T30/T15, relecture ≤ 1 requête/minute) | 5 à 10 |
| `hebdo` (lundi) | 1/7 | ≈ 2 min | 0,3 |

Total estimé : **20 à 25 minutes par jour, soit 600 à 750 minutes par mois**, entre 30 % et 38 % du forfait.
Le premier `soir` après un arrêt prolongé peut monter à 10 minutes (jusqu'à 8 journées relues) ; le job est
limité à 20 minutes. Les durées réelles se lisent dans l'onglet Actions ; à revoir si une exécution dépasse
régulièrement l'estimation.

## Pipeline (résumé)

1. `fetch.py` — objet `turf_bench.db` sur R2 (lecture seule) : empreinte sha256 = métadonnée du moteur, `PRAGMA integrity_check`, cache par empreinte (aucun téléchargement si inchangée), budget 4 téléchargements/jour ; client résultats ≤ 1 requête/minute avec vérification d'empreinte. Aucune lecture du dépôt turf-engine.
2. `contract.py` — tables/colonnes, `contract_version = 2` sur les prédictions du jour, sommes de probabilités, `historical_logs` (date J, clés, `publication_reason` connus), manifeste public. Un échec = arrêt, exit ≠ 0, aucune publication.
3. `eligibility.py` — miroir de la porte de publication (`publishable` + `OK` = autorité), prédiction `NEW_VALUE_ENGINE` conforme, départ > maintenant + 20 min, peloton ≥ 8, candidats = `editions_moteur.<horizon>.sel` (≥ 6 valides), cible top 5 si `QUINTE_PLUS`, sinon top 4.
4. `compute.py` + `core.py` — simulateur d'ordre à discount (lambdas littérature), échelles k = 1..4 pour m = 4 **et** m = 5, 5 meilleurs trios, recalibration post-sélection par (k, m), solidité par terciles gelés, structure v1. Graine fixée par (date, race_id).
5. `scoring.py` / `report.py` — back-test rétrospectif (rapport Markdown + JSON dans `rapports/backtest/`), calibrateurs, seuils.
6. `storage.py` — `bases.db` (runs, bases_editions, bases_results, calibration, params, results_manifest, abstentions, journal_days) ; `params.json` = export lisible de la version courante.
7. `pipeline.py` — `matin` / `soir` / `resultats` (§4, §7, sprint 4) ; `publish.py` — JSON contrat, palmarès, fiabilité ; `site.py` — pages (jour, journées, archives, palmarès) ; `notify.py` — résumé de job, journal, Telegram inactif.

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
