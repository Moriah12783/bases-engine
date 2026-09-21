# CHANGELOG — bases-engine

Toute évolution de formule, de paramètre ou de contrat est consignée ici avec sa date. Les éditions passées ne sont jamais recalculées.

## 2026-09-21 — Décisions du mentor (après rapport de sprint 1)

- **Calibration à paliers** (`bases_engine/calibration.py`, remplace le couple « shrink puis isotonique ») : le palier est choisi automatiquement selon n (courses notées par cible et par k) :
  n < 150 → facteur fixe 0,85 · 150 ≤ n < 300 → facteur = observé/annoncé global borné [0,60 ; 1,00] · 300 ≤ n < 1000 → logit-linéaire à deux paramètres (a + b·logit P, maximum de vraisemblance) · n ≥ 1000 → isotonique (classe `PostSelectionCalibrator` de `core.py`, inchangée). Seuils consignés dans `params.json` (`calibration_paliers`).
- **Horizon jugé = T_MATIN** : `backtest --since 2026-08-25 --horizon T_MATIN` (339 courses, 08/09 → 20/09) ; `params.json` regelé en **version 2026-09-21.2** sur les valeurs T_MATIN : seuils top5 A ≥ 0,2275 / B ≥ 0,1466, top4 A ≥ 0,1344 / B ≥ 0,0781 ; calibrateurs au palier `logit` (n = 339) pour les 8 couples (k, m). Le rapport T15 (394 courses) reste en référence secondaire. La version 2026-09-21.1 (T15) est conservée dans `bases.db` mais n'est plus la version courante.
- **Fixture résultats** : `fixtures/resultats/` = copie de `site/resultats/{index,2026-09-19,2026-09-20,corrections}.json` de l'instantané (format de production identique) ; `ResultsClient` accepte `file://<dossier>` pour les tests et le mode hors-ligne.
- Écarts acceptés : notation du back-test sur `race_results` SQLite ; seuils par cible top4/top5.
- Premier `contract-check` complet : par `workflow_dispatch` manuel ; crons désactivés tant qu'il ne passe pas.

## 2026-09-21 — Sprint 1 (fondations et back-test)

- `bases_engine/core.py` : cœur numérique fourni par le mentor (`base_des_bases.py`), intégré **sans modification**.
- `fetch.py` : détection du commit via `git ls-remote`, téléchargement au SHA (jamais `main` flottant), cache `.cache/<sha>/`, budget 4 téléchargements/jour/fichier, source alternative configurable (`BASES_SOURCE_BASE_URL`, `BASES_DB_FILENAME`, `.gz` accepté, `BASES_LOCAL_SNAPSHOT_DIR`), client résultats publics limité à 1 requête/minute.
- `contract.py` : tests de contrat §4.4 (bloquants).
- `eligibility.py` : porte d'éligibilité §4.1-4.2 (mode `matin` strict, mode `backtest` rétrospectif avec drapeau `LEGACY_CONTRACT`).
- `storage.py` : `bases.db` (schéma §5, migrations numérotées).
- `scoring.py` : back-test (`backtest --since --horizon`), courbe de fiabilité, terciles, baselines, calibrateur post-sélection par (k, top_m).
- `params.json` : première version gelée des paramètres (lambdas littérature, seuils de solidité = terciles du back-test, shrink 0,85).
- Écarts documentés par rapport au brief :
  - Le back-test note les courses sur `race_results` de l'instantané SQLite (`DEFINITIVE` + `VERIFIEE_PMU`), et non sur le JSON public : les JSON `/resultats/` sont le livrable du pipeline quotidien (sprint 2), le back-test est rétrospectif. Le contrôle croisé JSON ↔ SQLite arrive avec `soir`.
  - `seuils_solidite` de `params.json` sont stockés **par cible** (`top5`, `top4`) car la cible dépend de la course (`QUINTE_PLUS` présent ou non) ; l'annexe B ne montre qu'une paire.
  - Les commandes `matin`, `soir`, `hebdo` sont déclarées dans le CLI mais répondent « sprint 2 » (aucune publication possible avant les secrets Cloudflare).
