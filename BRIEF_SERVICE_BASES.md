# BRIEF D'EXÉCUTION — SERVICE « BASES » (base des bases Elite Turf)

Version 1.0 — 21 septembre 2026 — Rédigé pour la session Claude Code « développeur Bases ».
Donneur d'ordre : Steph (Tsalach Ventures LLC / Elite Turf). Mentor architecture : session Claude « moteur mentor ».

---

## 0. Lis ceci en premier

Tu construis un **service indépendant** qui produit chaque matin, pour chaque course éligible, une « échelle des bases » (1, 2, 3 ou 4 chevaux à fixer en bases d'un champ réduit Quarté/Quinté) avec sa probabilité de réussite, un indice de solidité et une structure de ticket recommandée.

Le service est un **consommateur externe** de prono.elite-turf.fr, exactement comme un partenaire tiers. Il lit ce qui est déjà public, il n'écrit jamais chez les autres, il ne demande rien à personne.

Trois règles absolues, non négociables, valables pour toute la durée du chantier :

1. **Tu ne modifies rien** dans le dépôt `Moriah12783/turf-engine`, dans le projet Cloudflare Pages `prono-elite-turf`, ni dans le projet Supabase Radar. Aucune PR, aucun commit, aucune clé, aucune requête d'écriture. Tu n'as pas besoin de leurs secrets et tu ne dois pas les demander.
2. **Tu ne scrapes pas le HTML** de prono.elite-turf.fr. Tu lis uniquement : le dépôt public (fichiers listés en §3), et les JSON de résultats publics documentés par le moteur.
3. **Ne sur-implémente pas.** Le périmètre v1 est l'étage 0 (simulateur d'ordre + échelle + recalibration + publication en mode ombre). Le modèle de placement entraîné (étage 1) est hors périmètre : il fera l'objet d'un brief séparé après le verdict.

Ton cœur numérique est fourni : `base_des_bases.py` (numpy uniquement). Tu l'intègres tel quel dans le paquet (`bases_engine/core.py`) ; tu peux l'améliorer, mais chaque changement de formule doit être couvert par un test et consigné dans `CHANGELOG.md`.

---

## 1. Contexte utile (à ne pas redécouvrir)

- Le moteur (`turf-engine`) tourne dans le cloud via GitHub Actions : édition du matin à **08h30 UTC** (fenêtre 7 jours), passes live aux minutes **6, 21, 36, 51 de 9h à 20h UTC** (verrouillage T-90 / T-30 / T-15 course par course), consolidation des arrivées à **21h30 UTC**. Chaque passe committe `turf_bench.db`, `benchmark_report.json`, `benchmark_dashboard.html` et `site/` sur `main`, puis déploie `site/` sur Cloudflare Pages. Le job a un timeout de 12 minutes : l'instantané du matin est donc disponible sur `main` au plus tard vers **08h45 UTC**.
- Le dépôt est **public**. Les probabilités calibrées de tous les partants, pour chaque moteur et chaque horizon, sont dans la table `predictions`. RADAR_V4 y est déjà (pont existant) : **tu n'as aucun besoin de Radar**.
- Le moteur émet déjà des « smart tickets » (Couplé Placé, Trio, Quinté+ champ réduit à 2 bases + XXX sur 4 associés). Le service ne les contredit pas : il ajoute la 3e base, la probabilité de chaque barreau de l'échelle et la recommandation d'abstention. Les deux messages sont complémentaires.
- Le développeur moteur a déjà écrit `lab_trio_bases.py` (étude rétrospective, 7 stratégies de trio, walk-forward). Lis-le pour comprendre les cohortes et les métriques ; **ne le modifie pas**. Ses résultats sur 898 courses : aucune pondération heuristique par la régularité ne bat « les 3 premiers » ; 3/3 dans les 5 = 24,8 % toutes courses, 35,7 % sur les courses 5★, 16,0 % sur les pelotons de 13+ ; ≥2/3 dans les 5 ≈ 73 %.
- Résultats de l'étude préliminaire du mentor (annexe A) : le trio à probabilité jointe maximale est identique aux 3 premiers du moteur dans 95 % des courses. **L'étage 0 ne change pas le trio, il le tarifie** : sa valeur est la probabilité par course (sélectivité forte : le tiers des courses le mieux noté réussit le 3/3 à 37 % contre 12 % pour les autres), l'échelle 1→4 bases, l'abstention, et l'affichage loyal d'un palmarès.

---

## 2. Charte du développeur Bases

Droits d'écriture : le dépôt `bases-engine` et le projet Cloudflare Pages `bases-elite-turf` (plus tard, éventuellement, un bot Telegram dédié au service). Rien d'autre.

Interdits : toute écriture sur `turf-engine`, `prono-elite-turf`, Radar ; toute clé ou secret des deux autres développeurs ; tout scraping HTML ; tout appel LLM dans le pipeline numérique (le service est déterministe et reproductible) ; toute modification du protocole pré-enregistré (§10) après la date de début du mode ombre.

Devoirs : tests de contrat à chaque exécution (§4.4) ; arrêt bruyant et alerte (§6.2) à la moindre incohérence, jamais de publication partielle ; traçabilité complète de chaque base publiée (commit source, `prediction_hash`, `lock_time_utc`, paramètres) ; journal `CLAUDE.local.md` mis à jour à chaque fin de session, brief de 5 lignes demandé en début de session.

Comportement vis-à-vis des deux autres développeurs : si un format change chez eux, le service s'arrête et alerte Steph ; c'est Steph qui décide, pas toi. Tu n'écris jamais à leur place, tu ne proposes pas de PR chez eux.

---

## 3. Contrat de lecture (sources exactes)

### 3.1 Dépôt public du moteur

`https://github.com/Moriah12783/turf-engine`, branche `main`.

Détection de changement : `git ls-remote https://github.com/Moriah12783/turf-engine.git refs/heads/main` (pas d'API GitHub, pas de quota). Le SHA obtenu est le `snapshot_commit` de la journée.

Récupération : téléchargement direct des fichiers bruts (`https://raw.githubusercontent.com/Moriah12783/turf-engine/<sha>/<fichier>`), **au SHA détecté** (jamais `main` flottant, pour la reproductibilité). Fichiers :

| Fichier | Usage | Taille (21/09/2026) |
|---|---|---|
| `turf_bench.db` | SQLite : predictions, races, runners, race_results, rapports, odds_snapshots | 32 Mo, croît ~1 Mo/jour |
| `benchmark_report.json` | clé `historical_logs[]` : verdict de la porte de publication et sélection de 8 par horizon | 11 Mo |

Budget : au plus 4 téléchargements par jour de chaque fichier. Mettre en cache par SHA dans le répertoire de travail du job (`.cache/<sha>/`).

### 3.2 Tables et colonnes utilisées (noms exacts, vérifiés sur l'instantané du 21/09/2026)

`predictions` — `race_id`, `engine_name` (valeurs : `NEW_VALUE_ENGINE`, `ETPE_ENGINE`, `MARKET_BASELINE`, `RADAR_V4`, `PRESS_SYNTHESIS` historique), `horizon` (`T_MATIN`, `T90`, `T30`, `T15`), `selection_json` (liste de numéros, ordre du moteur, longueur variable 3 à 10), `bases_json`, `outsider_num`, `probabilities_json` (dict `"num" -> proba`, tous les partants, somme = 1), `metadata_json`, `odds_real`, `priced_ratio`, `confidence_stars`, `confidence_label`, `is_no_bet`, `smart_tickets_json`, `contract_version`, `prediction_hash`, `lock_time_utc`, `created_at`. Unicité : (`race_id`, `engine_name`, `horizon`). Attention : les lignes antérieures au contrat v2 ont `contract_version`, `prediction_hash`, `is_no_bet` et `priced_ratio` à NULL (10 159 lignes sur 16 123 au 21/09) ; elles sont acceptées par le `backtest` (drapeau `LEGACY_CONTRACT`) mais jamais par le pipeline quotidien.

`races` — `race_id` (format `R1C1_21092026_LA CAPELLE`, **contient des espaces** : ne jamais l'utiliser tel quel dans un nom de fichier ou une URL ; dériver un slug), `date` (`AAAA-MM-JJ`), `meeting_number`, `race_number`, `name`, `hippodrome`, `discipline`, `distance`, `declared_runners`, `start_time_utc` (`2026-09-21T14:00:00Z`), `scheduled_start_time` (`14:00 GMT (16:00 Paris)`), `pmu_statut`, `status`, `bets_json` (liste `{code, mise_base_eur, en_vente}` ; codes utiles : `QUINTE_PLUS`, `QUARTE_PLUS`, `MULTI`, `MINI_MULTI`, `DEUX_SUR_QUATRE`).

`runners` — `race_id`, `num`, `horse_name`, `is_non_partant`, `music`, `driver_jockey`, `trainer`, `shoeing`, `blinkers`, `morning_odds`, `odds_t15`, `final_odds`, `odds_is_real`. (v1 : seul `is_non_partant` est nécessaire ; les autres colonnes sont réservées à l'étage 1.)

`race_results` — `race_id`, `arrival_order_json` (liste ordonnée des numéros), `ranking_json`, `disqualified_json`, `non_partants_json`, `statut` (`DEFINITIVE` / `PROVISOIRE` / …), `finalite` (`VERIFIEE_PMU` / `LEGACY_NON_VERIFIEE`), `version`, `nb_corrections`, `updated_at`.

`rapports` — `race_id`, `bet_type` (`QUINTE_PLUS`, `QUARTE_PLUS`, `MULTI`, `SIMPLE_PLACE`, …), `combination` (ex. `14-9-11-6-3`, `14-9-11-6`), `dividend`. La sémantique ordre / désordre / bonus des combinaisons n'est **pas** documentée dans la table : avant tout calcul de rendement, lis `turf_lab/results_export.py` et `turf_lab/results_reader.py` (lecture seule) et consigne le mapping dans `docs/rapports_mapping.md`. Tant que ce mapping n'est pas validé par Steph, le rendement est **informatif** et marqué « non validé ».

`benchmark_report.json` → `historical_logs[]` : `race_id`, `date`, `course` (libellé `LA CAPELLE - R1C1`), `publishable` (bool), `publication_reason` (`OK`, `RACE_STARTED`, `ODDS_DEFAULT`, `RACE_CANCELLED`), `display_horizon`, `priced_ratio`, `market_odds_available`, `edition_provisoire`, `editions_moteur{<horizon>: {sel: "16-13-4-8-15-9-6-3", lock, priced_ratio, odds_real}}`, `editions_marche{…}`.

### 3.3 Résultats publics (site)

Documentés par le moteur dans `RESULTATS_JSON.md` (lis-le intégralement) :

- `https://prono.elite-turf.fr/resultats/index.json` — manifeste des journées, avec `empreinte_sha256`
- `https://prono.elite-turf.fr/resultats/AAAA-MM-JJ.json` — en-tête `schema_version`, `version_code`, `date_course`, `genere_le_utc`, `nb_courses`, `compte_par_statut`, `empreinte_sha256`, puis `courses[]` : `course_id`, `identite{code, hippodrome, discipline, distance_m, heure_depart_utc, heure_depart_affichee, partants_declares, partants_actifs}`, `statut{code, definitive, finalite, annulee, pmu_statut}`, `classement[]{rang, num, nom, dead_heat}`, `arrivee[]`, `non_classes[]`, `non_partants[]`, `rapports`, `correction{version, nb_corrections, historique[]}`, `horodatages{…}`
- `https://prono.elite-turf.fr/resultats/corrections.json`

Règles du producteur, à respecter : comparer l'empreinte du manifeste avant de relire une journée ; ne faire confiance qu'aux courses `statut.definitive = true` **et** `statut.finalite = "VERIFIEE_PMU"` ; exclure `ANNULEE` ; **≤ 1 requête par minute**. Une course dont `correction.version` augmente doit être re-notée (§7).

Source de vérité pour la notation : le JSON public (c'est le livrable que le moteur garantit à ses partenaires). `race_results` de la base SQLite sert de contrôle croisé ; en cas de divergence, alerte et pas de notation.

### 3.4 Ce que tu ne lis pas

`site/index.html` (5,6 Mo, HTML), les pages HTML de prono, le projet Supabase Radar, les JSON n8n. Aucune exception.

---

## 4. Pipeline quotidien

### 4.1 Course éligible (miroir de la porte de publication, sans la toucher)

Une course de la date J est éligible pour l'édition du matin si **toutes** les conditions suivantes sont vraies dans l'instantané :

1. `historical_logs` contient la course avec `publishable = true` et `publication_reason = "OK"` (autorité). Si la course est absente de `historical_logs`, elle est **inéligible** (pas de repli sur les seuls drapeaux SQLite : la porte appartient au moteur).
2. `predictions` contient la ligne (`NEW_VALUE_ENGINE`, `T_MATIN`) avec `contract_version = 2`, `prediction_hash` non NULL, `odds_real = 1`, `priced_ratio` non NULL et `>= 0.9`, `is_no_bet` différent de 1, et `probabilities_json` couvrant au moins 8 partants non `is_non_partant`, de somme comprise entre 0,99 et 1,01.
3. `races.start_time_utc` est postérieur à l'instant du calcul + 20 minutes.
4. `declared_runners - nb non-partants >= 8`.

Toute course non éligible est consignée dans `abstentions` avec son motif (`NON_PUBLISHABLE:<reason>`, `NO_BET`, `PRICED_RATIO`, `RACE_STARTED`, `FIELD_TOO_SMALL`, `CONTRACT`).

### 4.2 Ensemble candidat et cible

- Candidats = les numéros (au plus 8) de `editions_moteur.T_MATIN.sel` (chaîne `16-13-4-8-15-9-6-3`), dans cet ordre. Repli si la chaîne est absente : `selection_json[:8]` de la prédiction `T_MATIN`. Si moins de 6 candidats valides (présents dans `probabilities_json`, non NP) : abstention `CANDIDATES_TOO_FEW`.
- Probabilités = `probabilities_json` de (`NEW_VALUE_ENGINE`, `T_MATIN`), renormalisées après retrait des NP.
- Cible `top_m` : 5 si `QUINTE_PLUS` figure dans `bets_json`, sinon 4. Le service calcule **toujours** les deux échelles (m = 4 et m = 5) et les stocke ; il publie celle de la cible et garde l'autre disponible dans le JSON.

### 4.3 Calcul (cœur fourni)

1. Ordres d'arrivée simulés : `simulate_top_m(p, lambdas, top_m, n_sims=40_000)` avec les `lambdas` de `params.json` (défaut littérature `(1.0, 0.81, 0.65, 0.55, 0.50)` — **ne pas ré-estimer avant 1 500 courses définitives** ; l'estimation sur 200 courses a donné des coefficients instables et une sur-confiance de 25 %).
2. Échelle : `base_ladder(...)` → pour k = 1..4 le meilleur sous-ensemble, `p_all` (brute) et `p_all_but_one` ; conserver aussi les 5 meilleurs trios.
3. Recalibration post-sélection : `PostSelectionCalibrator` par (k, top_m), ajusté sur l'historique noté (P annoncée → réussite observée), repli `shrink = 0.85` tant que n < 150. La probabilité **publiée** est toujours la valeur recalibrée ; la brute est stockée.
4. Indice de solidité (sur P recalibrée du trio, k = 3) : `A` si ≥ `seuil_A`, `B` si ≥ `seuil_B`, sinon `C`. Les seuils sont calculés une fois par la commande `backtest` (terciles de la distribution sur l'historique) puis **gelés** dans `params.json` jusqu'au verdict.
5. Structure recommandée v1 : `A` → « 3 bases + XX » (m = 5) ou « 3 bases + X » (m = 4) ; `B` → « 2 bases + XXX » (m = 5) ou « 2 bases + XX » (m = 4) ; `C` → « abstention sur bases fixes ». L'échelle complète est toujours publiée : l'abonné garde la main.
6. Graine aléatoire fixée par (`date`, `race_id`) pour qu'un recalcul donne le même résultat.

### 4.4 Tests de contrat (bloquants, à chaque exécution)

Avant tout calcul : les tables et colonnes de §3.2 existent ; `contract_version` vaut 2 sur toutes les prédictions du jour ; chaque `probabilities_json` somme à 1 ± 0,01 ; `historical_logs` contient au moins une course de la date J ; les valeurs de `publication_reason` sont dans l'ensemble connu ; le manifeste `index.json` répond et contient `empreinte_sha256`. Un échec = arrêt, exit code ≠ 0, alerte (§6.2) avec le nom du test, **aucune publication**.

### 4.5 Idempotence

Une exécution est identifiée par (`date`, `horizon`, `snapshot_commit`). Rejouer la même exécution ne crée pas de doublon. Si un nouveau commit apparaît le même matin (relance manuelle du moteur), le service recalcule et publie une nouvelle version, en conservant l'ancienne dans `bases_editions` avec `superseded_by`.

---

## 5. Stockage

Base SQLite `bases.db` committée dans le dépôt (même doctrine que le moteur : persistance définitive, historique lisible).

- `runs` : `run_id`, `started_at_utc`, `command`, `snapshot_commit`, `mode`, `races_seen`, `races_published`, `status`, `error`, `duration_s`.
- `bases_editions` : `edition_id`, `date`, `race_id`, `race_slug`, `horizon`, `top_m`, `computed_at_utc`, `snapshot_commit`, `prediction_hash`, `lock_time_utc`, `engine8_json`, `candidates_json`, `lambdas_json`, `ladder_json` (k → chevaux, p_brute, p_calibree, p_k_moins_1), `trios_json` (top 5), `solidite`, `structure_code`, `flags_json`, `params_version`, `mode`, `published_at_utc`, `superseded_by`.
- `bases_results` : `race_id`, `result_version`, `arrivee_json`, `top_m`, `hit_k1..hit_k4`, `hit_2of3`, `scored_at_utc`, `source` (`RESULTATS_JSON`), `checked_against_sqlite` (bool).
- `calibration` : `computed_at_utc`, `k`, `top_m`, `n`, `knots_json`, `params_version`.
- `params` : `version`, `valid_from`, `lambdas_json`, `seuils_json`, `shrink`, `note`.

`params.json` à la racine est l'export lisible de la version courante de `params`.

---

## 6. Publication

### 6.1 Site statique (Cloudflare Pages, projet `bases-elite-turf`)

Généré dans `site/` et déployé avec `npx --yes wrangler@4 pages deploy site --project-name=bases-elite-turf --branch=main --commit-dirty=true`. Domaine `bases.elite-turf.fr` rattaché par Steph dans le tableau de bord Pages (zone déjà chez Cloudflare).

Mode `shadow` : la racine sert une page neutre « Service en préparation » ; les contenus vivent sous `site/shadow/<SHADOW_TOKEN>/…` (jeton aléatoire 32 caractères, secret du dépôt). Mode `live` : les contenus sont à la racine.

Contenus : `index.html` (édition du jour, thème noir et or Elite Turf, sobre, double affichage des heures GMT / Paris), `bases/AAAA-MM-JJ.json` (contrat annexe B), `palmares.json` (compteurs glissants depuis le début du mode ombre, par k et par solidité, avec n), `fiabilite.json` (courbe P annoncée vs observée par tranche), `archive/AAAA-MM.json`.

Le palmarès affiché n'est **jamais** retouché ni filtré : c'est un pilier de la marque (« aucun chiffre retouché »). Les abstentions sont comptées et affichées.

### 6.2 Notifications (sans Telegram en v1)

Steph n'utilise pas Telegram pour le moment. Le service n'en dépend donc pas ; il s'appuie sur trois canaux qui existent dès la création du dépôt, et Telegram s'ajoutera plus tard par simple configuration.

1. **Résumé de job GitHub** (`$GITHUB_STEP_SUMMARY`) : chaque exécution écrit l'édition du matin ou le bilan du soir (gabarits annexe E) dans le résumé du run, lisible dans l'onglet Actions du dépôt, y compris depuis l'application GitHub mobile.
2. **Journal committé** : `rapports/journal/AAAA-MM-JJ.md` (édition du matin + bilan du soir, même contenu que le résumé) et `rapports/journal/ALERTES.md` (une ligne par incident). Le journal est la mémoire lisible du mode ombre ; le rapport hebdomadaire s'en nourrit.
3. **Page ombre** : `site/shadow/<SHADOW_TOKEN>/index.html`, consultable à tout moment.

Alertes : tout échec (test de contrat, téléchargement, déploiement) fait **échouer le job** (exit code ≠ 0) après avoir écrit la cause dans le résumé et dans `ALERTES.md`. GitHub notifie l'échec par e-mail : Steph active « Watch → Custom → Actions » sur le dépôt `bases-engine` pour recevoir tous les échecs de workflow, quel que soit l'auteur du commit.

Architecture : `notify.py` expose `notify(kind, title, body)` et diffuse vers les canaux listés dans la variable `NOTIFY_CHANNELS` (`summary,journal` par défaut). Le canal `telegram` est prévu dans le code mais **inactif** : il ne s'active que si `NOTIFY_CHANNELS` le contient **et** que `TELEGRAM_BOT_TOKEN_BASES` et `TELEGRAM_CHAT_ID_<MODE>` existent ; absents, le canal est ignoré silencieusement, sans erreur. Aucun changement de code ne sera nécessaire le jour où Steph crée son canal.

### 6.3 Contrat JSON pour de futurs consommateurs

`bases/AAAA-MM-JJ.json` est versionné (`contract_version: 1`). Toute rupture de format = `contract_version: 2` et conservation de l'ancien pendant 30 jours. C'est par ce fichier, et uniquement par lui, que le site principal ou l'espace membres pourront un jour afficher les bases, à la discrétion de leur développeur.

---

## 7. Notation, calibration, rapports

Chaque soir (§8), pour J et J-1 à J-7 : relire `index.json`, ne relire une journée que si son empreinte a changé, noter chaque course définitive `VERIFIEE_PMU` dont une édition existe ; en cas de nouvelle `correction.version`, re-noter et conserver l'historique. Contrôle croisé avec `race_results` de l'instantané : divergence = alerte, pas de notation.

Réussite pour k bases : les k chevaux du barreau k sont tous dans les `top_m` premiers de `arrivee` (les non-partants ne comptent jamais comme placés ; une course avec `dead_heat` se note sur `classement[].rang`).

Recalibration : `PostSelectionCalibrator` réajusté chaque lundi sur l'ensemble noté, par (k, top_m) ; nouvelle version de `params` avec `valid_from`. Jamais d'ajustement rétroactif des éditions passées.

Rapport hebdomadaire (lundi) : n courses, taux observés par k et par solidité, courbe de fiabilité, comparaison aux deux baselines (3 premiers du moteur ; 3 plus courtes cotes `MARKET_BASELINE`), rendement informatif « 3 bases + XX / 5 associés » et « 3 bases + champ total » sur les courses Quinté/Quarté avec rapports (marqué « non validé » tant que §3.2 `rapports` n'est pas validé). Écrit dans `rapports/AAAA-Www.md`, repris dans le résumé de job, et diffusé sur Telegram le jour où ce canal existera.

---

## 8. Ordonnancement (GitHub Actions, `.github/workflows/bases.yml`)

```yaml
on:
  schedule:
    - cron: '5 9 * * *'     # matin : édition des bases (instantané 08h30 attendu vers 08h45)
    - cron: '35 9 * * *'    # rattrapage idempotent (retard de cron GitHub ou instantané tardif)
    - cron: '5 22 * * *'    # soir : notation J et J-7..J-1, mesure T15, palmarès, déploiement
    - cron: '30 7 * * 1'    # lundi : recalibration + rapport hebdomadaire
  workflow_dispatch:
    inputs: { command: {description: "matin | soir | hebdo | backtest | contract-check", default: "matin"} }
permissions: { contents: write }
concurrency: { group: bases-engine, cancel-in-progress: false }
```

Job unique, `timeout-minutes: 10`, Python 3.11, `pip install -r requirements.txt` (numpy, requests). Étapes : checkout → `python -m bases_engine <commande>` → commit `bases.db`, `params.json`, `site/`, `rapports/` si changement (message `Bases: <commande> <date> [skip ci]`, push avec 3 tentatives et rebase, jamais de force-push) → déploiement Pages.

Le matin, si `git ls-remote` renvoie un SHA identique à celui déjà traité pour la date J, attendre 5 minutes et réessayer, 3 fois au plus ; au-delà, journaliser `SNAPSHOT_LATE` et alerter (pas d'échec du job : le rattrapage de 09h35 prendra le relais).

Secrets du dépôt `bases-engine` (v1) : `CLOUDFLARE_API_TOKEN_BASES` (jeton dédié, permission Cloudflare Pages : Edit), `CLOUDFLARE_ACCOUNT_ID`, `SHADOW_TOKEN`. Secrets optionnels, à poser plus tard : `TELEGRAM_BOT_TOKEN_BASES`, `TELEGRAM_CHAT_ID_SHADOW`, `TELEGRAM_CHAT_ID_LIVE`. Variables de dépôt : `PUBLICATION_MODE` (`shadow` par défaut ; `live` uniquement sur décision écrite de Steph après le verdict §10) et `NOTIFY_CHANNELS` (`summary,journal` par défaut). Le `GITHUB_TOKEN` par défaut n'a de droits que sur `bases-engine`.

Le sprint 1 ne requiert **aucun** secret (lecture publique, back-test local). Le sprint 2 ne requiert que les trois secrets Cloudflare/ombre ; sans eux, `matin` et `soir` fonctionnent en `--dry-run` (calcul, stockage, journal, résumé de job) et seul le déploiement du site est sauté.

---

## 9. Structure du dépôt et commandes

```
bases-engine/
  README.md · BRIEF_SERVICE_BASES.md · CHARTE_DEVELOPPEUR_BASES.md · PROTOCOLE_PREENREGISTRE.md · CHANGELOG.md
  requirements.txt · params.json · bases.db
  bases_engine/
    __init__.py · __main__.py (CLI)
    core.py          ← base_des_bases.py fourni, inchangé au départ
    fetch.py         ← ls-remote, téléchargement au SHA, cache, résultats JSON (≤ 1 req/min)
    contract.py      ← tests de contrat §4.4
    eligibility.py   ← §4.1-4.2
    pipeline.py      ← matin / soir / hebdo
    scoring.py       ← notation, calibration, baselines
    storage.py       ← bases.db (schéma §5, migrations numérotées)
    publish.py       ← site/, JSON contrat
    notify.py        ← résumé de job, journal, (Telegram inactif tant que non configuré)
    report.py        ← rapport hebdomadaire
  tests/             ← unitaires (cas calculable à la main), contrat (instantané figé), bout-en-bout (dry-run)
  fixtures/          ← extrait figé de turf_bench.db (≤ 2 Mo) et de historical_logs pour les tests
  site/ · rapports/ · docs/rapports_mapping.md
  .github/workflows/bases.yml
```

Commandes : `python -m bases_engine contract-check` · `matin [--date J] [--dry-run]` · `soir [--date J]` · `hebdo` · `backtest --since 2026-08-25 [--horizon T15|T_MATIN]` · `show --date J` (affiche l'édition en console).

---

## 10. Protocole pré-enregistré (à écrire dans `PROTOCOLE_PREENREGISTRE.md` avant la première exécution en mode ombre, puis gelé)

Période : à partir du premier `matin` réussi, jusqu'à **28 jours ou 800 courses éligibles notées**, la première des deux échéances atteinte. Horizon jugé : `T_MATIN` (celui que verrait l'abonné). Les baselines sont calculées sur les mêmes courses.

Critères principaux :

1. **Calibration** : sur les deux tranches supérieures de P recalibrée (k = 3), |fréquence observée − P annoncée| ≤ 5 points, avec n ≥ 60 par tranche.
2. **Sélectivité** : taux 3/3 des courses `A` ≥ 1,8 × taux 3/3 des courses `C`, et taux 3/3 des courses `A` ≥ 28 %.
3. **Non-régression** : taux 3/3 du trio publié ≥ taux 3/3 des 3 premiers du moteur − 2 points.

Critères secondaires (informatifs) : taux ≥ 2/3 par solidité ; taux 2/2 et 1/1 ; rendement des deux structures de ticket sur les courses avec rapports.

Décision : les trois critères principaux tenus → Steph peut passer `PUBLICATION_MODE=live`. Critère 1 échoué → refonte de la recalibration, nouvelle période. Critère 2 échoué → l'indice de solidité est retiré de la publication, l'échelle seule est publiée. Critère 3 échoué → le trio publié devient « les 3 premiers du moteur » et le service ne garde que la tarification.

Rien de ce protocole ne se modifie après la première exécution. Toute évolution des paramètres pendant la période est consignée avec date dans `CHANGELOG.md` et n'affecte que les éditions postérieures.

---

## 11. Sprints et définition de « terminé »

**Sprint 1 (jours 1-2) — Fondations et back-test.** Dépôt créé, `core.py` intégré avec ses tests unitaires (cas calculable à la main : 3 partants, Harville, P(top 2) = 0,8393), `fetch.py` + `contract.py` opérationnels sur l'instantané courant, `backtest` fonctionnel et produisant un rapport Markdown (taux par k, fiabilité par tranche, terciles, baselines, par taille de peloton), `params.json` écrit avec les seuils de solidité gelés. Terminé quand : `contract-check` passe, `backtest --since 2026-08-25 --horizon T15` s'exécute en moins de 3 minutes et ses ordres de grandeur sont cohérents avec l'annexe A (3/3 ≈ 20-25 %, échelle ≈ 68 / 40 / 20 / 9).

**Sprint 2 (jours 3-4) — Pipeline et mode ombre.** `matin`, `soir`, stockage, site, JSON contrat, notifications (§6.2), workflow, secrets Cloudflare posés par Steph, `PROTOCOLE_PREENREGISTRE.md` écrit, premier `matin` en mode ombre exécuté et lisible dans le résumé du job et dans `rapports/journal/`. Terminé quand : deux journées consécutives complètes (matin + soir) sans intervention, et une relance manuelle idempotente vérifiée.

**Sprint 3 (hebdomadaire) — Rapports.** `hebdo` en place, premier rapport reçu, `docs/rapports_mapping.md` rédigé et soumis à Steph. Ensuite : laisser tourner. Pas de nouvelle fonctionnalité avant le verdict.

Conventions : commits atomiques en français, préfixe `Bases:` ; jamais de force-push ; `CHANGELOG.md` tenu à jour ; toute décision non couverte par ce brief est posée à Steph, pas prise seule.

---

## 12. Risques identifiés et réponses

- **Croissance de `turf_bench.db`** (~1 Mo/jour, 32 Mo le 21/09) : GitHub refuse les fichiers > 100 Mo. Ce risque appartient au moteur, mais le service doit le prévoir : `fetch.py` accepte une source alternative (fichier compressé, export JSON de sélection, ou autre chemin) par configuration, sans changement de code ailleurs. Signaler à Steph le jour où le fichier dépasse 80 Mo.
- **Retard de cron GitHub** : couvert par le rattrapage 09h35 et l'idempotence. Si les deux passes manquent l'instantané, la journée est marquée `SNAPSHOT_MISSING` (pas de bases ce jour-là, jamais de calcul sur un instantané de la veille).
- **Changement de schéma chez le moteur** : tests de contrat, arrêt, alerte. Le service reste à l'arrêt tant que Steph n'a pas tranché.
- **Course annulée ou non-partant après l'édition** : l'édition reste telle quelle (elle reflète l'information du matin), la notation exclut la course (`ANNULEE`) ou traite le NP comme non placé ; le palmarès l'indique.
- **Résultat corrigé après notation** : re-notation versionnée, palmarès recalculé, mention dans le rapport hebdomadaire.

---

## Annexe A — Résultats préliminaires (mentor, 20-21/09/2026)

Simulation (modèle à discount, probabilités de qualité marché) — probabilité que toutes les bases soient à l'arrivée, meilleur sous-ensemble parmi 8 :

| Profil | 1 base | 2 bases | 3 bases | 4 bases |
|---|---|---|---|---|
| Quinté 16 partants, hiérarchie nette | 65 % | 33 % | 13 % | 3,6 % |
| Quinté 16 partants, course ouverte | 47 % | 18 % | 5,6 % | 1,2 % |
| Quarté 12 partants (top 4) | 65 % | 32 % | 11 % | 2,1 % |

Instantané réel (400 courses T15 éligibles, 200 de test) : trio joint = 3 premiers du moteur dans 95,5 % des courses ; échelle observée 68 / 39,5 / 20,5 / 9 % ; tercile haut de P annoncée : 3/3 = 37 %, ≥2/3 = 82 % ; terciles bas et médian : 12 % et 57-64 %. Avec les lambdas par défaut, P annoncée moyenne 0,222 pour 0,218 observé (bien calibré en moyenne, léger optimisme dans la zone 0,18-0,22). Avec des lambdas ré-estimés sur 200 courses : sur-confiance de 25 % → d'où la consigne « pas de ré-estimation avant 1 500 courses ».

Étude du développeur moteur (`lab_trio_bases.py`, 898 courses) : 3/3 dans les 5 = 24,8 % (toutes), 35,7 % (5★), 30,4 % (4-5★), 16,0 % (13+ partants), 31,5 % (8-12 partants) ; aucune heuristique de régularité ne bat les 3 premiers.

## Annexe B — Contrat `bases/AAAA-MM-JJ.json` (version 1)

```json
{
  "contract_version": 1,
  "date": "2026-09-21",
  "mode": "shadow",
  "genere_le_utc": "2026-09-21T09:07:41Z",
  "source": {"depot": "Moriah12783/turf-engine", "commit": "<sha>", "moteur": "NEW_VALUE_ENGINE", "horizon": "T_MATIN"},
  "parametres": {"version": "2026-09-22.1", "lambdas": [1.0, 0.81, 0.65, 0.55, 0.5], "seuils_solidite": {"A": 0.30, "B": 0.18}, "calibration": {"k3_m5": {"n": 0, "mode": "shrink", "shrink": 0.85}}},
  "courses": [
    {
      "course_id": "R1C1_21092026_LA CAPELLE",
      "slug": "2026-09-21_r1c1_la-capelle",
      "libelle": "LA CAPELLE - R1C1",
      "depart_utc": "2026-09-21T11:20:00Z",
      "depart_affiche": "11:20 GMT (13:20 Paris)",
      "discipline": "TROT_ATTELE",
      "partants": 16,
      "pari_cible": "QUINTE_PLUS",
      "top_m": 5,
      "moteur": {"selection_8": [16, 13, 4, 8, 15, 9, 6, 3], "etoiles": 4, "prediction_hash": "<hash>", "lock_time_utc": "2026-09-21T07:45:39Z"},
      "echelle": {
        "1": {"chevaux": [16], "p_brute": 0.78, "p_calibree": 0.66, "p_k_moins_1": 1.0},
        "2": {"chevaux": [16, 13], "p_brute": 0.47, "p_calibree": 0.40, "p_k_moins_1": 0.86},
        "3": {"chevaux": [16, 13, 4], "p_brute": 0.24, "p_calibree": 0.20, "p_k_moins_1": 0.66},
        "4": {"chevaux": [16, 13, 4, 8], "p_brute": 0.10, "p_calibree": 0.08, "p_k_moins_1": 0.38}
      },
      "echelle_top4": {"...": "même structure pour m = 4"},
      "base_des_bases": {"chevaux": [16, 13, 4], "p_calibree_3sur3": 0.20, "p_calibree_2sur3": 0.66, "solidite": "B"},
      "trios_alternatifs": [{"chevaux": [16, 13, 8], "p_brute": 0.21}],
      "structure_recommandee": {"code": "2B_XXX", "texte": "2 bases + XXX", "motif": "solidité B"},
      "drapeaux": []
    }
  ],
  "abstentions": [{"course_id": "R1C4_21092026_LA CAPELLE", "motif": "NON_PUBLISHABLE:ODDS_DEFAULT"}]
}
```

## Annexe C — Charte (fichier `CHARTE_DEVELOPPEUR_BASES.md`)

Reprendre intégralement le §2 de ce brief. Signature : « Lu et appliqué par la session développeur Bases, le <date> ».

## Annexe D — Textes de gouvernance (à faire copier par Steph, pas par toi)

Ligne d'annexe du pont Radar : « <date> — Service Bases (aval, lecture seule) : consomme `predictions` (`NEW_VALUE_ENGINE`, `T_MATIN`/`T15`), `historical_logs` et les JSON de résultats publics ; ne modifie ni le moteur, ni la porte de publication, ni Radar ; mode ombre jusqu'au verdict du protocole pré-enregistré. »

Mot aux deux développeurs : « Un service tiers, `bases-engine`, lit les sorties publiques de turf-engine (base SQLite et `benchmark_report.json` sur `main`, JSON `/resultats/`). Il s'arrête de lui-même et alerte Steph si un format change. Aucune action n'est attendue de votre côté ; si vous prévoyez de renommer une table, une colonne ou une clé JSON, une ligne dans votre journal suffit. »

## Annexe E — Gabarits de notification (résumé de job, journal ; Telegram plus tard, même texte)

Matin (mode ombre, un message) :

```
🏇 BASES — 21/09 — édition du matin (ombre)
Source moteur commit a1b2c3d · 32 courses lues · 24 éligibles · 8 abstentions

LA CAPELLE R1C1 · 11:20 GMT (13:20 Paris) · Quinté+ · 16 partants
Base des bases : 16 - 13 - 4 · solidité B · P(3/3) 20 % · P(2/3) 66 %
Échelle : 1 base 66 % · 2 bases 40 % · 3 bases 20 % · 4 bases 8 %
Structure : 2 bases + XXX

[… une ligne par course, solidité A en premier …]

Abstentions : R1C4 (cotes par défaut), R2C2 (no bet) …
```

Soir : « BASES — bilan du 21/09 : 22 courses notées · 3/3 : 5 (23 %) · 2/3 : 14 (64 %) · solidité A : 4/9 · palmarès depuis le 22/09 : … · corrections : 0 ».

Alerte : « ⛔ BASES — arrêt : <test de contrat> a échoué sur commit <sha>. Aucune publication. Action requise : Steph. »
