# CHANGELOG — bases-engine

Toute évolution de formule, de paramètre ou de contrat est consignée ici avec sa date. Les éditions passées ne sont jamais recalculées.

## 2026-09-23 — `resultats` sur le métronome (GO Steph)

- Constat : le cron GitHub `20 11-21 * * *` a été servi 3 fois sur 11 le 22/09 et 1 fois sur 8 le 23/09 (jusqu'à 18:18 UTC) : la page du jour restait figée sur l'état de 15:29 UTC.
- 4e Cron Trigger du Worker `bases-metronome` : `18 11-21 * * *` → `resultats` (deux minutes avant le cron GitHub, qui reste le filet). Quatre triggers sur cinq. Redéploiement à faire par Steph (« Métronome · déploiement »).

## 2026-09-23 — Décision du mentor : jour 1 maintenu au 22/09, écart d'empreinte persistant

- `PROTOCOLE_PREENREGISTRE.md` : annexe factuelle d'activation (passe fondatrice servie par le filet cron à 14:00:22 UTC, 11 courses, métronome silencieux le jour 1, actif dès le jour 2 ; fenêtre 22/09 → 19/10/2026, verdict attendu le 20/10/2026). Critères et seuils inchangés.
- Écart manifeste ↔ journée : renoncement sans échec confirmé ; s'il persiste sur **3 passes horaires consécutives** ou **jusqu'à la passe soir**, annotation `::warning title=Écart d'empreinte persistant::…`, ligne `ECART_EMPREINTE_PERSISTANT` dans `ALERTES.md`, incident compté dans le rapport hebdomadaire (« Écarts d'empreinte persistants … : N »). Compteur consécutif remis à zéro à la première lecture réussie (tables `incidents`, `ecarts_empreinte`, migration 8).

## 2026-09-23 — Corrections après la lecture de la page du 23/09 (présentation ; protocole inchangé)

- **En-tête du palmarès et des archives** : le préfixe `f` des deux chaînes avait sauté lors de l'ajout du favicon (gabarit brut `{pal.get('depuis') or '—'}` affiché). Corrigé ; test de non-régression : aucune accolade de gabarit dans aucune page, « Palmarès depuis le JJ/MM/AAAA » rendu.
- La page du jour affiche désormais « Palmarès depuis le JJ/MM/AAAA » (lien vers le palmarès).
- Compteurs du jour : « courses écartées (non éligibles) » distinguée de « solidité C · abstention sur bases fixes » ; bloc du bas renommé « Courses écartées du jour ».
- Passe horaire / soir : quand la journée a été régénérée par le producteur entre la lecture du manifeste et celle du fichier (« empreinte ≠ manifeste », run `resultats` de 19:46 le 22/09), relecture cohérente une fois (manifeste puis journée) ; si l'écart persiste, la passe renonce sans échec et le note.
- Constat : la date de début du protocole est **2026-09-22**, fixée à 14:00:22 UTC par le cron GitHub `matin` servi avec cinq heures de retard (déclencheur `cron`, donc passe planifiée), après le commit A ; annotation « Métronome silencieux » émise comme prévu. La passe `matin · metronome` du 23/09 (09:05:26 UTC, 24 courses, repetition = 0) n'a donc pas eu à la fixer. Le protocole interdit de réécrire la date.

## 2026-09-22 — Mini-sprint « Métronome », commit C (après recette)

- Recette verte : run `contract-check · metronome` à 13:30 UTC, 36 s. Ligne de recette retirée de `COMMANDES` (`worker.js`) et son cron de `wrangler.toml`.
- Correction : Cloudflare numérote les jours 1 = dimanche … 7 = samedi ; `28 7 * * 1` remplacé par `28 7 * * MON` dans `wrangler.toml` **et** dans `COMMANDES` (égalité stricte de chaîne avec `controller.cron`).
- `docs/RUNBOOK.md` : jeton GitHub créé le 22/09/2026, expire le mercredi 22 septembre 2027, rappel agenda au 7 septembre 2027.
- À faire par Steph : relancer « Métronome · déploiement » pour appliquer les crons.

## 2026-09-22 — Mini-sprint « Métronome », commit B (Worker Cloudflare)

- `metronome/worker.js` (frappe `workflow_dispatch` de `bases.yml` avec `source = metronome`, un nouvel essai après 60 s, erreur visible dans Metrics → Errors), `metronome/wrangler.toml` (crons `5 9 * * *` matin, `3 22 * * *` soir, `28 7 * * 1` hebdo, sans URL publique, journaux activés), `.github/workflows/metronome.yml` (déploiement en un clic : `wrangler deploy` puis pose du secret `GH_DISPATCH_TOKEN`).
- Ligne de **recette** active : cron `30 13 * * *` UTC → `contract-check` (sans effet sur le protocole ni la page). À retirer au commit C après le test, avec son cron.
- Secrets GitHub attendus : `CLOUDFLARE_API_TOKEN_METRONOME`, `CLOUDFLARE_ACCOUNT_ID`, `METRONOME_GH_TOKEN`.

## 2026-09-22 — Mini-sprint « Métronome », commit A (workflow + sémantique des passes)

- `bases.yml` : input `source` (`manuel` | `metronome`) sur `workflow_dispatch`, `run-name` lisible (`cron <expr>` ou `<commande> · <source>`), déclencheur transmis au Python (`--declencheur manuel|cron|metronome`) en plus de la commande dérivée de l'expression cron ; groupe de concurrence `bases-engine` sans annulation confirmé (déjà en place). Lignes cron intactes.
- Passe planifiée = `cron` **ou** `metronome` : la première passe `matin` planifiée qui produit réellement une édition fixe la date de début du protocole ; `manuel` reste hors protocole. Déclencheur enregistré sur `runs`, `bases_editions`, `journal_days` (migration 7).
- Répétition rapide : une passe planifiée qui trouve la journée déjà servie (matin : par n'importe quel déclencheur ; soir/hebdo : par une passe planifiée) sort en quelques secondes **avant tout téléchargement**, sans toucher la page ni le protocole (`runs.mode = repetition`). Une passe manuelle recalcule toujours (relance volontaire, remplacement si nouveau commit moteur).
- Garde-fou « métronome silencieux » : un run `cron` qui sert `matin`, `soir` ou `hebdo` sans frappe du métronome le signale (annotation `::warning title=Métronome silencieux::…`, ligne `METRONOME_SILENCIEUX` dans le journal) sans échec de run. Compteur dans le rapport hebdomadaire : « Métronome : N jours servis par le métronome, N par le filet, N manqués » (passe matin, 7 derniers jours).
- `PROTOCOLE_PREENREGISTRE.md` : une phrase (le métronome compte comme planifié ; une passe manuelle ou une répétition ne fixe pas la date). Critères et seuils inchangés. `docs/RUNBOOK.md` créé (exploitation du métronome, expiration du jeton à inscrire par Steph).
- Constat du 22/09 : les crons GitHub `7 9` et `35 9` n'ont pas été servis du tout (aucun run dans l'onglet Actions), d'où ce sprint.

## 2026-09-22 — Favicon (présentation uniquement, hors protocole)

- `assets/favicon/` (favicon.svg, favicon.ico, favicon-32.png, apple-touch-icon.png, favicon-512.png) copié à la racine de `site/` à chaque régénération ; les cinq balises du kit ajoutées au gabarit `<head>` commun (page neutre, pages ombre, journées, archives, palmarès). Aucun autre changement.

## 2026-09-22 — Complément sprint 4 : `soir` auto-réparateur (hors protocole)

- `soir` traite J puis J-1 à J-7 et complète, de façon idempotente, tout ce qui manque : mesure intrajournée T90/T30/T15 absente (pour J toujours ; pour J-1..J-7 si une édition du matin existe), notation non faite (journée jamais notée alors que le manifeste annonce des arrivées définitives), contrôle croisé SQLite absent (notations de la passe horaire), empreinte modifiée. Un `soir` manqué ou servi en retard est rattrapé au suivant sans intervention.
- Résumé de job et journal : lignes « Rattrapage — journée du JJ/MM : mesure intrajournée complétée (…) ; notation complétée (motif : n notation(s) ajoutée(s), n contrôlée(s)) », ou « Rattrapage : rien à compléter sur J-1..J-7 ».
- Workflow : ligne cron **commentée** `'40 23 * * *'` (soir de rattrapage, idempotent) ajoutée sous les lignes existantes, intactes ; `timeout-minutes` porté de 10 à 20 (jusqu'à 8 journées relues à ≤ 1 requête/minute).
- Budget Actions estimé et noté dans le README : 20 à 25 min/jour, 600 à 750 min/mois (30 à 38 % du forfait privé).
- Fixture : `fixtures/resultats/2026-09-21.json` (journée en attente, 32 courses) ajoutée pour la cohérence avec le manifeste.

## 2026-09-22 — Sprint 4 : consultation et résultats (présentation et publication ; aucun changement des éditions, du calcul, de params.json ni du protocole)

- **Lignes dépliables** (`bases_engine/site.py`) : chaque course est un `<details>` natif ; le `<summary>` montre hippodrome-numéro, heure GMT (Paris), pari, base des bases, solidité, structure courte et le résultat (« en attente », « 3/3 ✓ », « 2/3 », « 1/3 », « 0/3 », « annulée », suffixe « (provisoire) »). Contenu déplié = fiche complète + bloc résultat (arrivée top 4/5, statut PMU, verdict par barreau « 3 bases : 2 sur 3 à l'arrivée », verdict de la structure recommandée). Quinté+ épinglé, puis A, B, C. Recherche hippodrome/réunion/numéro par mini-script inline (facultatif, la page fonctionne sans).
- **Passe horaire `resultats`** : nouvelle commande ; cron `'20 11-21 * * *'` ajouté **commenté** dans le bloc `schedule` (Steph le décommentera — signalé). Lit `index.json`, relit la journée seulement si l'empreinte a changé, note DEFINITIVE et PROVISOIRE (statut affiché tel quel), régénère et déploie la page. Aucun instantané moteur téléchargé (budget) donc pas de contrôle croisé : `soir` relit d'office les journées ayant des notations non contrôlées et reste la consolidation de référence. Le palmarès ne compte que DEFINITIVE + VERIFIEE_PMU (`bases_results.finalite`, migration 6) ; table `course_statuts` pour l'affichage des courses sans notation (en attente / annulée).
- **En tête de page** : compteur du jour (3/3 et ≥ 2/3 sur n courses notées, provisoires comptées à part), courses éligibles, abstentions.
- **Historique** : pastilles aujourd'hui / hier / 14 jours avec le nombre de courses, une page par journée `jours/AAAA-MM-JJ.html` (régénérée par `matin`, `resultats`, `soir`), archives mensuelles `archive/AAAA-MM.html`, `palmares.html` (par barreau, par solidité, par cible, par journée ; répétitions exclues et comptées).
- Tout reste sous `site/shadow/<jeton>/` tant que `PUBLICATION_MODE = shadow`.
- **Incident du 22/09 00:36 UTC** : le cron `soir` de 22:05 a été servi par GitHub avec 2 h 30 de retard ; la commande était déduite de l'heure courante et l'exécution a été prise pour un `matin` du 22/09 (échec de contrat, aucune publication). Correction : commande déduite de l'expression cron déclenchante (`github.event.schedule`) ; un `soir`/`resultats` servi avant 06:00 UTC vise la veille. `BEFORE_0630` ajouté aux raisons connues (vu ce matin-là, non publiable).
- Tests : journée avec résultats partiels (définitives, provisoire, annulée, en attente), second passage sans relecture, relecture et contrôle croisé par `soir`, navigation entre jours, archive, palmarès.

## 2026-09-21 — Libellés de l'échelle (présentation uniquement)

- Page et résumé de job : ligne « Tous à l'arrivée » avec cases « xx % (1 sur 1) · xx % (2 sur 2) · xx % (3 sur 3) · xx % (4 sur 4) » ; ligne « Tous sauf un » avec « — · xx % (1 sur 2) · xx % (2 sur 3) · xx % (3 sur 4) ». Plus aucune mention de k, (k/k) ni ((k−1)/k). Légende : « Tous à l'arrivée = les chevaux indiqués finissent tous dans les 4 (ou 5) premiers ; Tous sauf un = un seul d'entre eux peut manquer. »

## 2026-09-21 — Mesure intrajournée (demande du mentor, hors protocole)

- `soir` : la mesure rétrospective couvre **T90, T30 et T15** (même calcul, même graine), éditions `mode = mesure` stockées par horizon dans `bases_editions`, notées par horizon dans `bases_results`, `repetition` selon la règle en vigueur. Jamais publiées.
- `bases_results.non_partants_json` (migration 5) : non-partants au résultat.
- Rapport hebdomadaire, section « Évolution intrajournée » : part des courses où le trio T90 / T30 / T15 diffère du trio du matin, taux 3/3 et ≥ 2/3 du trio du matin contre celui de l'horizon sur ces seules courses, nombre de courses où une base du trio du matin figure dans les non-partants au résultat. Informatif, hors verdict.
- Aucune publication intrajournée, aucun changement des éditions publiées, du protocole ni de `params.json`.

## 2026-09-21 — Courses Trio / Couplé placé seulement (retour du mentor sur 57ea54b)

- Courses sans Quarté+, Multi ni 2sur4 : une **échelle cible top 3** est calculée avec le simulateur (mêmes lambdas, même graine), stockée dans `ladder_json.top3` et exposée dans le JSON en champ additif `echelle_top3` (+ `note_top3`). La ligne de structure affiche « Trio ou Couplé placé : 2 bases + X · P(les 2 bases dans les 3 premiers) = xx % (estimation brute, non recalibrée) », avec les 2 bases du barreau 2 de cette échelle. Plus aucune probabilité top 4 affichée à côté d'un pari sur les 3 premiers.
- Solidité, palmarès et protocole : inchangés, toujours calculés sur la cible top 4 / top 5. Test dédié (Vichy R4C3 du 21/09).

## 2026-09-21 — Présentation (retour du mentor sur la répétition matin ; hors protocole)

- Pari et structure : l'étiquette « TOP4 » disparaît au profit des paris réellement offerts (`bets_json` : Quinté+, Quarté+, Multi, Mini Multi, 2sur4 ; drapeau `paris:` stocké dans `flags_json`). Structure formulée dans le pari principal : Quinté+ → « 3 bases + XX avec les associés », Quarté+ → « 3 bases + X avec les associés », Multi → « Multi en 5 ou 6 autour des 3 bases », course sans Quarté+/Multi → barreau 2, « 2sur4 avec les 2 bases » ; solidité B → variantes à 2 bases ; C → abstention. **Les codes de structure stockés ne changent pas.**
- Cartes : lignes « Sélection moteur : … » (les 8) et « Associés : … » (les 8 moins les bases du barreau recommandé). Le contrat JSON gagne `paris_offerts`, `paris_libelle`, `pari_principal`, `associes`, `structure_recommandee.{pari, barreau, bases}` (ajouts, `contract_version` inchangée).
- Ordre de page : Quinté+ du jour épinglé en tête, puis A, B, C ; par heure de départ dans un groupe.
- Libellés : « Tous à l'arrivée (k/k) » et « Un manquant au plus ((k−1)/k) ».
- Bloc « Abstentions du jour » en bas de page, motifs en français ; légende d'une ligne sous l'en-tête (probabilité, lettres A/B/C, mention shadow).
- Éditions antérieures à ce changement (répétition du 21/09) : drapeau `paris:` absent → « paris non renseignés » ; régénérées à la prochaine édition.
- Aucune modification de `params.json`, du calcul ni du protocole.

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
