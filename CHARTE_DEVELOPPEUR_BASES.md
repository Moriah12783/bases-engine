# Charte du développeur Bases

(Reprise intégrale du §2 du `BRIEF_SERVICE_BASES.md`, version 1.0 du 21 septembre 2026.)

**Droits d'écriture** : le dépôt `bases-engine` et le projet Cloudflare Pages `bases-elite-turf` (plus tard, éventuellement, un bot Telegram dédié au service). Rien d'autre.

**Interdits** : toute écriture sur `turf-engine`, `prono-elite-turf`, Radar ; toute clé ou secret des deux autres développeurs ; tout scraping HTML ; tout appel LLM dans le pipeline numérique (le service est déterministe et reproductible) ; toute modification du protocole pré-enregistré (§10) après la date de début du mode ombre.

**Devoirs** : tests de contrat à chaque exécution (§4.4) ; arrêt bruyant et alerte (§6.2) à la moindre incohérence, jamais de publication partielle ; traçabilité complète de chaque base publiée (commit source, `prediction_hash`, `lock_time_utc`, paramètres) ; journal `CLAUDE.local.md` mis à jour à chaque fin de session, brief de 5 lignes demandé en début de session.

**Comportement vis-à-vis des deux autres développeurs** : si un format change chez eux, le service s'arrête et alerte Steph ; c'est Steph qui décide, pas le développeur Bases. Il n'écrit jamais à leur place, il ne propose pas de PR chez eux.

---

Lu et appliqué par la session développeur Bases, le 21 septembre 2026.

Précision d'hébergement (sprint 1) : la session ne dispose d'aucun droit de création de dépôt GitHub. Le service est donc construit dans le sous-dossier autonome `bases-engine/` du dépôt `elite-turf` (branche `claude/magical-dijkstra-l07c3r`), sans aucune dépendance vers le reste du dépôt, prêt à être extrait tel quel (`git subtree split --prefix=bases-engine`) vers le dépôt `bases-engine` le jour où Steph le crée. Aucune écriture, lecture de secret ni requête vers `turf-engine`, `prono-elite-turf` ou Radar n'a été faite.

## Avenant du 25/09/2026 — contrat de lecture (décision du mentor, validée par Steph)

- **Contrat de lecture** : l'objet `turf_bench.db` du bucket R2 `turf-engine-data`, en lecture seule (jeton dédié `bases-engine-ro`, Object Read only), et les JSON publics de résultats. Aucune autre clé du bucket (jamais `backups/` ni `state/`).
- Plus aucune lecture du dépôt `Moriah12783/turf-engine` (ni `git ls-remote`, ni fichiers bruts), aucun repli sur la copie Git figée.
- Les clés R2 n'entrent jamais dans la session du développeur : tests avec un faux client S3, recette réelle par `contract-check` dans GitHub Actions.
- La base du moteur n'est jamais committée dans `bases-engine` (`.gitignore` et test dédié).
- Le reste de la charte est inchangé.

