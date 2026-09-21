# CHANGELOG — bases-engine

Toute évolution de formule, de paramètre ou de contrat est consignée ici avec sa date. Les éditions passées ne sont jamais recalculées.

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
