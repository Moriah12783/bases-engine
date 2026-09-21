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
