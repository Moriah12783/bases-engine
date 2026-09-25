# Runbook — service Bases

## Métronome (Worker Cloudflare `bases-metronome`)

- Rôle : déclencheur primaire des passes `matin` (`5 9,11,13 * * *` = 09:05, 11:05 et 13:05 UTC depuis le 25/09 : répétition si la journée est servie, sinon courses restantes), `soir` (`3 22 * * *` = 22:03 UTC), `hebdo` (`28 7 * * MON` = 07:28 UTC le lundi ; Cloudflare numérote 1 = dimanche … 7 = samedi, d'où le nom du jour) et, depuis le 23/09 (GO Steph), `resultats` (`18 11-21 * * *`), deux minutes avant les crons GitHub (`7 9`, `5 22`, `30 7 * * 1`, `20 11-21`), qui restent le filet. Quatre Cron Triggers sur les cinq du plan gratuit.
- Déploiement : Actions → « Métronome · déploiement » → Run workflow (`.github/workflows/metronome.yml`). Secrets : `CLOUDFLARE_API_TOKEN_METRONOME`, `CLOUDFLARE_ACCOUNT_ID`, `METRONOME_GH_TOKEN`.
- **Jeton GitHub `metronome-bases` (fine-grained, dépôt `bases-engine`, Actions : lecture-écriture)** : créé le 22 septembre 2026 · **expire le mercredi 22 septembre 2027** · rappel agenda posé au 7 septembre 2027. Rotation : nouveau jeton → mettre à jour le secret `METRONOME_GH_TOKEN` → relancer « Métronome · déploiement ».
- Recette du 22/09/2026 : run `contract-check · metronome` à 13:30 UTC, vert en 36 s.
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

## Page shadow vide ou 404 alors que les runs sont verts

- Règle : l'étape « Déploiement Cloudflare Pages » de `bases.yml` ne déploie que si le run a écrit `.cache/site_built` (écrit par `build_site`, jamais en dry-run). Un run en répétition ou en renoncement affiche « ⏭ Déploiement sauté » dans son résumé et laisse la version en ligne intacte.
- Diagnostic : Actions → dernier run → étape de déploiement. « 🚀 Déploiement … site reconstruit par ce run (…) » = la version en ligne date de ce run. Si la page reste vide après un déploiement vert, ajouter `?v=<heure>` à l'URL (cache navigateur) avant toute autre hypothèse.
- Restauration immédiate : Actions → « Bases » → Run workflow → commande `resultats` (source `manuel`) : reconstruit et déploie la page du jour sans créer d'édition (aucun effet sur le protocole).

## Source moteur R2 (depuis le 25/09/2026)

- Objet lu : `turf-engine-data/turf_bench.db`, point d'accès `https://<CLOUDFLARE_ACCOUNT_ID>.r2.cloudflarestorage.com` (même compte que `bases-metronome`). Métadonnées du moteur : `sha256`, `counts`, `pushed-at`, `run-id`, `commit`.
- **Jeton R2 `bases-engine-ro`** (Object Read only, bucket `turf-engine-data`) : créé le 25/09/2026 par Steph · **expire le mercredi 22 septembre 2027** · **rotation le même jour que `metronome-bases`**, rappel agenda du 7 septembre 2027 déjà posé. Secrets GitHub : `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` (et `CLOUDFLARE_ACCOUNT_ID`, déjà posé). Rotation : nouveau jeton, mise à jour des deux secrets, puis Actions → « Bases » → `contract-check`.
- **Job rouge `SOURCE_INVALIDE`** : empreinte ≠ métadonnée, métadonnée `sha256` absente, `PRAGMA integrity_check` en échec, R2 injoignable ou secrets absents. Aucune édition. Lire le résumé du run.
- **Job vert `SOURCE_SANS_MATIN` avec annotation « Source sans matin du jour »** : la base lue n'a pas les T_MATIN du jour, ou sa poussée n'est pas postérieure à leur verrou. Aucune édition ; la passe n'est pas servie, donc les frappes de 11:05 et 13:05 retentent.
- **Annotation « Source moteur ancienne »** : poussée vieille de plus d'une heure. Avertissement seulement.
- Lecture : un seul GET (métadonnées et contenu dans la même réponse). Écart d'empreinte : jusqu'à 3 nouvelles lectures à 30 s, puis job rouge. `NoSuchKey` (clé renommée) : job rouge. Budget : 4 téléchargements par jour.
- `contract-check` n'échoue que sur une colonne attendue absente ou renommée, ou un `contract_version` inattendu ; le reste est signalé en avertissement.

