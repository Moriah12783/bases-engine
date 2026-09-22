# Runbook — service Bases

## Métronome (Worker Cloudflare `bases-metronome`)

- Rôle : déclencheur primaire des passes `matin` (`5 9 * * *` = 09:05 UTC), `soir` (`3 22 * * *` = 22:03 UTC), `hebdo` (`28 7 * * 1` = 07:28 UTC le lundi), deux minutes avant les crons GitHub (`7 9`, `5 22`, `30 7 * * 1`), qui restent le filet.
- Déploiement : Actions → « Métronome · déploiement » → Run workflow (`.github/workflows/metronome.yml`). Secrets : `CLOUDFLARE_API_TOKEN_METRONOME`, `CLOUDFLARE_ACCOUNT_ID`, `METRONOME_GH_TOKEN`.
- **Jeton GitHub `metronome-bases` (fine-grained, dépôt `bases-engine`, Actions : lecture-écriture)** : créé le ____ · **expire le ____** (à inscrire par Steph, validité un an). Rotation : nouveau jeton → mettre à jour le secret `METRONOME_GH_TOKEN` → relancer « Métronome · déploiement ».
- Symptômes d'un jeton mort ou d'un Worker absent : runs `cron …` portant l'annotation « Métronome silencieux », ligne « Métronome : N jours servis par le filet » dans le rapport hebdomadaire, erreurs HTTP 401 dans Cloudflare → Workers & Pages → bases-metronome → Metrics → Errors.
- Arrêt d'urgence : supprimer les Cron Triggers dans le tableau de bord (ou vider `crons` dans `metronome/wrangler.toml` et redéployer). Le filet GitHub reprend seul.
- Quotas plan gratuit : 5 Cron Triggers par compte (tous Workers confondus), 100 000 requêtes/jour, 10 ms CPU par frappe. En cas de pénurie : fusionner matin et soir (`5 9,22 * * *`) et router par l'heure UTC dans le Worker.
- Budget Actions : les runs filet deviennent des répétitions de moins d'une minute ; surcoût net ≈ 3 minutes/jour.

## Passes et déclencheurs

| Déclencheur | Origine | Valeur pour le protocole |
|---|---|---|
| `metronome` | Worker Cloudflare → `workflow_dispatch` (`source = metronome`) | planifiée (fixe la date de début si première édition) |
| `cron` | cron GitHub (`schedule`) | planifiée (filet ; annotation si le métronome n'a pas servi la passe) |
| `manuel` | bouton Run workflow ou exécution locale | hors protocole (répétition) |

Une passe planifiée qui trouve la journée déjà servie sort en répétition en quelques secondes, avant tout téléchargement (test sur `bases.db`).
