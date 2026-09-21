# CHANGELOG — bases-engine

Toute évolution de formule, de paramètre ou de contrat est consignée ici avec sa date. Les éditions passées ne sont jamais recalculées.

## 2026-09-21 — Corrections après le contract-check #2 (commit moteur `71f79f42d2`)

- `publication_reason` : `PRICED_RATIO_LOW` ajouté à l'ensemble connu. Nouvelle règle : une valeur inconnue avec `publishable = false` est un **avertissement** (compté, listé dans le résumé, journalisé dans `ALERTES.md`, non bloquant) ; une valeur inconnue avec `publishable = true` reste **bloquante**. Le drapeau `publishable` est l'autorité, la raison est informative.
- Workflow, étape « Commit des artefacts » : n'ajoute que les chemins existants (`test -e`), n'échoue jamais sur « rien à ajouter », reste en `if: always()` pour que `ALERTES.md` soit commité même si l'exécution a échoué (cause du run #2 : `git add site` sur un dossier absent).
- Résumé de secours : écrit seulement si l'exécution n'a posé aucun marqueur (`.cache/summary_written`, posé par le CLI à chaque écriture dans `$GITHUB_STEP_SUMMARY`), pour éviter un double message contradictoire.

## 2026-09-21 — Retour du mentor sur le rapport T_MATIN : GO pour le gel (version 2026-09-21.2 confirmée)

- Vérification 1 — **seuils calculés sur la P(3/3) recalibrée** : `scoring.analyse()` prend les terciles de `cal_all.transform(p_brute)` ; à l'exécution `compute_edition()` compare `p_calibree` (même calibrateur, depuis `params.json`) aux seuils. Même quantité des deux côtés : aucun recalcul.
- Vérification 2 — **filtre `priced_ratio ≥ 0,9`** (`config.MIN_PRICED_RATIO`), identique au pipeline quotidien. Sur la cohorte T_MATIN de l'instantané `f1677b62` (397 lignes `odds_real = 1` avec résultat vérifié) : 0 ligne `< 0,9`, 0 ligne NULL, 397 lignes `≥ 0,9` (minimum observé 0,9). Aucun rejeu : **la version 2026-09-21.2 reste la version gelée**, aucun seuil ne bouge.
- `PROTOCOLE_PREENREGISTRE.md` : mention de la version gelée, du commit moteur du back-test (`f1677b62`) et champ « commit du dépôt à l'activation » rempli automatiquement (`GITHUB_SHA`) par le premier `matin` planifié.
- Rapport hebdomadaire : compteur cumulé des courses où le trio publié diffère des 3 premiers du moteur (n, part, 3/3 de chacun). Informatif, hors verdict.

## 2026-09-21 — Décisions du mentor avant activation des crons

- **Date de début du protocole** : champ « à renseigner par la première exécution planifiée » dans `PROTOCOLE_PREENREGISTRE.md` ; fixée par le premier `matin` déclenché par le cron (`GITHUB_EVENT_NAME = schedule`), écrite dans `bases.db` (`meta.protocole_debut`) et dans le fichier (jamais réécrite).
- **Répétitions** : toute exécution de `matin`/`soir` portant sur un jour antérieur au début du protocole (ou avant qu'il soit fixé : exécutions manuelles, `workflow_dispatch`, locales, `--dry-run`) est marquée `repetition = 1` dans `bases_editions` et `bases_results` (migration 3), exclue du palmarès, de la fiabilité, de la recalibration et du verdict ; le résumé de job et le journal l'indiquent (« RÉPÉTITION »). `palmares.json` expose `repetitions_exclues`.
- **`hebdo` implémenté** (`bases_engine/hebdo.py`) : recalibration par (k, cible) sur l'ensemble noté hors répétitions → nouvelle version `AAAA-MM-JJ.N` de `params.json` (seuils de solidité et lambdas inchangés jusqu'au verdict), ligne automatique dans ce CHANGELOG ; rapport `rapports/AAAA-Www.md` (échelle, solidité, baselines « 3 premiers du moteur » et « 3 plus courtes cotes » sur les mêmes courses, fiabilité, état des trois critères du protocole) ; rendement **non calculé** tant que `docs/rapports_mapping.md` n'est pas validé. Option `--sans-recalibration`.
- `bases_results` : clé primaire étendue à l'horizon (migration 4) — la notation de l'édition publiée (T_MATIN) et celle de la mesure (T15) coexistent.
- Ordre de mise en service mis à jour dans le README (pages-init → domaine → contract-check → une répétition `matin` manuelle un jour de courses → validation du rapport T_MATIN par le mentor → décommenter le bloc schedule et modifier une minute → début du protocole).

## 2026-09-21 — Compléments du mentor (sprint 2)

- Workflow : commande `pages-init` (workflow_dispatch **uniquement**, refus explicite sinon) : `npx --yes wrangler@4 pages project create bases-elite-turf --production-branch=main` avec `CLOUDFLARE_API_TOKEN_BASES` / `CLOUDFLARE_ACCOUNT_ID` ; idempotente (projet déjà listé, ou réponse « already exists » → succès). Le rattachement du domaine reste manuel (tableau de bord Pages).
- Lignes `cron` : note de propriété en tête du bloc `schedule` (l'auteur de la dernière modification reçoit les notifications d'échec — Steph). Elles ne seront plus retouchées sans signalement explicite dans le rapport de session.
- Résumé de job (§6.2) garanti pour **chaque** exécution : `contract-check` (succès ou échec), `backtest`, `hebdo` (stub), `matin`/`soir` (édition, bilan ou alerte), erreurs de téléchargement et exceptions inattendues (filet dans le CLI → `ALERTES.md` + résumé), et étape de secours du workflow si le processus meurt avant d'écrire.

## 2026-09-21 — Sprint 2 (pipeline et mode ombre)

- `pipeline.py` : `matin` (instantané du jour avec attente 5 min × 3 puis `SNAPSHOT_LATE` sans échec, tests de contrat bloquants, porte §4.1, calcul, stockage, idempotence par (date, horizon, commit), `superseded_by` si nouveau commit le même matin, publication, notification annexe E) et `soir` (tests de contrat, mesure T15 rétrospective en `mode = mesure` jamais publiée, relecture des journées J-7..J dont l'empreinte a changé, notation sur le JSON public `DEFINITIVE` + `VERIFIEE_PMU` avec contrôle croisé SQLite — divergence = alerte et pas de notation —, re-notation versionnée sur `correction.version`, palmarès, fiabilité, site, bilan).
- `publish.py` : contrat `bases/AAAA-MM-JJ.json` (annexe B, `contract_version: 1`, plus `echelle_top4`/`echelle_top5`, `edition_id`, `snapshot_commit`, `params_version`), `palmares.json` (compteurs glissants depuis le premier `matin` OK, par k, par solidité, par cible, par jour ; abstentions comptées ; jamais filtré), `fiabilite.json`, `archive/AAAA-MM.json`, page noir et or (heures GMT + Paris). Mode ombre : racine neutre « Service en préparation » + contenu sous `site/shadow/<SHADOW_TOKEN>/` (**non committé** : `.gitignore`, pour ne pas écrire le jeton dans le dépôt ; le contenu est régénéré à chaque run depuis `bases.db`).
- `notify.py` : `notify(kind, title, body)` → `summary` (`$GITHUB_STEP_SUMMARY`, sinon stdout), `journal` (`rapports/journal/AAAA-MM-JJ.md`, `ALERTES.md`), `telegram` prévu mais inactif tant que `NOTIFY_CHANNELS` ne le contient pas **et** que les secrets n'existent pas.
- `bases.db` migration 2 : colonnes `edition_id`, `hits_json`, `solidite`, `p_calibree_k3`, `horizon`, `statut` sur `bases_results` ; tables `results_manifest` (empreintes), `abstentions`, `journal_days` (début du mode ombre = première ligne `OK`). Un `matin --dry-run` est journalisé `DRY_RUN` et ne démarre pas la période.
- `.github/workflows/bases.yml` : `workflow_dispatch` (commande + date) ; **crons commentés** jusqu'au premier `contract-check` complet réussi ; commit des artefacts avec 3 tentatives et rebase, jamais de force-push ; déploiement Pages seulement si `CLOUDFLARE_API_TOKEN_BASES` existe ; `matin` passe en `--dry-run` sans ce secret.
- `PROTOCOLE_PREENREGISTRE.md` rédigé et gelé (§10) sur `params.json` v2026-09-21.2.
- Sémantique `--dry-run` (matin) : calcul, stockage, journal et résumé de job, mais `published_at_utc` vide et pas de déploiement.
- Non fait (sprint 3) : `hebdo` (recalibration du lundi, rapport hebdomadaire), `docs/rapports_mapping.md`, rendements.

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
