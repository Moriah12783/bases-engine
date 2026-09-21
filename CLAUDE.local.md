# Journal de session — développeur Bases

Brief de 5 lignes à demander en début de session ; journal mis à jour à chaque fin de session (charte §2).

## 2026-09-21 — Session 1 (sprint 1 : fondations et back-test)

- Lu le brief en entier, charte signée (`CHARTE_DEVELOPPEUR_BASES.md`). Kit reçu : brief + `core.py` (identique au fichier Drive `base_des_bases_py.txt`).
- Contexte d'hébergement : pas de droit de création de dépôt → service construit dans `elite-turf/bases-engine/` (branche `claude/magical-dijkstra-l07c3r`), autonome, extractible par `git subtree split`.
- Instantané moteur lu au SHA `f1677b6220a882baf8028e232d1a617f32b30d9d` (turf_bench.db 31,9 Mo, benchmark_report.json 11,2 Mo, RESULTATS_JSON.md). Vérifié : sélections `editions_moteur.*.sel` = `selection_json[:8]` dans 100 % des cas ; `probabilities_json` couvre tous les partants actifs ; 24 courses `publishable=OK` le 21/09.
- Contraintes du bac à sable : `prono.elite-turf.fr` est **refusé par le proxy de sortie** (403 CONNECT) → le test de contrat « manifeste » ne peut pas être exécuté d'ici (`--no-network` le marque explicitement sauté). Le téléchargement de fichiers `.py` du moteur est refusé par la politique de l'environnement → `lab_trio_bases.py` lu en résumé seulement ; `results_export.py` / `results_reader.py` (mapping `rapports`, sprint 3) restent à lire.
- Livré : paquet `bases_engine` (core inchangé, config, util, fetch, contract, eligibility, compute, scoring, report, storage, params, CLI), 26 tests hors réseau (fixture 2 Mo, 2 journées), back-test T15 (394 courses, 54 s), `params.json` v2026-09-21.1 gelé, `bases.db` initialisé.
- Écarts / décisions consignés dans `CHANGELOG.md` (notation du back-test sur SQLite, seuils par cible top4/top5, commandes sprint 2 en stub).
- Reste pour le sprint 2 : `pipeline.py` (matin/soir), `publish.py`, `notify.py`, workflow, `PROTOCOLE_PREENREGISTRE.md`, secrets Cloudflare (Steph).

## 2026-09-21 — Session 1, suite (décisions du mentor)

- Dépôt `Moriah12783/bases-engine` : non accessible à la session au moment de la vérification (introuvable ou sans accès). L'extraction (`git subtree split`) et la suppression de la branche `claude/magical-dijkstra-l07c3r` restent à faire dès que l'accès est ouvert.
- Fixture résultats construite depuis `site/resultats/` de l'instantané (19 et 20/09, manifeste, corrections). `ResultsClient` lit `file://`.
- Calibration à paliers implémentée et testée (fixe / ratio / logit / isotonique). Back-test T_MATIN rejoué, `params.json` v2026-09-21.2 gelé.
- Incident bénin : le run `backtest` T_MATIN a perdu sa sortie standard (pipe fermé) après le gel ; ligne `runs` corrigée à la main avec la cause dans `error`.

## 2026-09-21 — Session 1, sprint 2

- Livré : `pipeline.py` (matin/soir), `publish.py`, `notify.py`, migration 2 de `bases.db`, workflow (crons commentés), `PROTOCOLE_PREENREGISTRE.md`, 40 tests hors réseau (dont bout-en-bout matin dry-run → ombre idempotent, remplacement par nouveau commit, arrêt sur contrat, SNAPSHOT_LATE, soir avec notation JSON + contrôle croisé).
- Validation locale sur l'instantané réel (hors dépôt, dans le bac à sable) : `matin --date 2026-09-21 --dry-run --no-network --now 2026-09-21T09:05:00Z` → 20 éligibles / 12 abstentions, journal annexe E ; `soir --date 2026-09-20` → 43 éditions de mesure T15, 84 notations JSON toutes contrôlées avec SQLite. `bases.db` du dépôt reste vierge d'éditions : la première exécution ombre doit se faire dans GitHub Actions (traçabilité du run).
- Décision de conception à valider par Steph : `site/shadow/<jeton>/` n'est pas committé (le jeton resterait sinon dans l'historique git) ; seul `site/index.html` (page neutre) l'est. Le contenu ombre est régénéré à chaque run et déployé par wrangler.
- Reste : dépôt dédié + secrets (Steph), premier `contract-check` par workflow_dispatch, deux journées complètes sans intervention, relance idempotente vérifiée en Actions ; sprint 3 (`hebdo`, mapping `rapports`).
- Extraction faite : `git subtree split --prefix=bases-engine` → poussé sur `main` du dépôt dédié `Moriah12783/bases-engine` (7 commits `Bases:`, aucune histoire d'elite-turf). Tests verts dans le dépôt dédié (40). Branche locale `claude/magical-dijkstra-l07c3r` supprimée ; la **suppression de la branche distante est refusée par le proxy git de la session (HTTP 403)** → à faire par Steph (GitHub → Branches, ou `git push origin --delete claude/magical-dijkstra-l07c3r`). Rien n'a été fusionné dans elite-turf.
- Compléments du mentor appliqués : `pages-init` (dispatch seul, idempotent), résumé de job garanti pour toute exécution (y compris échec avant écriture), note de propriété des lignes cron. **Règle mémorisée : ne jamais retoucher les lignes `cron` de `bases.yml` sans le signaler dans le rapport ; ne jamais « corriger » la modification de minute faite par Steph.**
- Décisions « avant activation des crons » appliquées : date de début du protocole fixée par le premier matin planifié (`meta.protocole_debut` + champ du protocole), drapeau `repetition` (migration 3), clé de `bases_results` étendue à l'horizon (migration 4, bug trouvé par le test hebdo : la notation T15 écrasait la notation T_MATIN), `hebdo` implémenté (recalibration + rapport hebdomadaire + état des critères), ordre de mise en service dans le README.
- GO du mentor pour le gel v2026-09-21.2 après deux vérifications (seuils sur P recalibrée : oui ; filtre priced_ratio 0,9 : oui, 0 course exclue, 0 NULL). Protocole complété (version, commit moteur, commit dépôt à l'activation auto). Compteur « trio ≠ 3 premiers moteur » ajouté au rapport hebdo. Séquence de mise en service inchangée.
- contract-check #2 en Actions (moteur `71f79f42d2`) : échec sur `PRICED_RATIO_LOW` puis `git add site` ; trois corrections du mentor appliquées (raison inconnue non publiable = avertissement, commit des chemins existants en always(), résumé de secours conditionné à un marqueur). Relance par workflow_dispatch faite par la session.
