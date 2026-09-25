# Protocole pré-enregistré — service Bases (mode ombre)

Rédigé le 21 septembre 2026, **avant** la première exécution en mode ombre, à partir du §10 du
`BRIEF_SERVICE_BASES.md`. Rien de ce protocole ne se modifie après la première exécution. Toute
évolution de paramètre pendant la période est consignée avec date dans `CHANGELOG.md` et n'affecte
que les éditions postérieures. Le palmarès n'est jamais retouché ni filtré.

## Période

**Date de début : 2026-09-22** (fixée par le premier `matin` planifié, run `matin-2026-09-22-e4606b`).

**Commit du dépôt `bases-engine` à l'activation : `e284c28319e15ffe7848cc5847114d9886d8da59`.**

Paramètres gelés : `params.json` **version 2026-09-21.2** (validée par le mentor le 21/09/2026 après
vérification que les seuils de solidité sont calculés sur la P(3/3) **recalibrée**, la quantité comparée
aux seuils à l'exécution, et que le filtre `priced_ratio ≥ 0,9` du back-test est celui du pipeline
quotidien). Back-test de référence : horizon T_MATIN, commit moteur **`f1677b6220a882baf8028e232d1a617f32b30d9d`**
(`turf-engine`), 339 courses du 08/09 au 20/09/2026.

La date est fixée par la première passe `matin` **planifiée** qui produit réellement une édition : cron
GitHub (événement `schedule`) ou frappe du métronome (`workflow_dispatch` avec `source = metronome`), qui
compte comme planifiée au même titre. Elle est écrite ici et dans `bases.db` (clé `protocole_debut`) et
n'est jamais réécrite. Une passe manuelle ne la fixe pas ; une répétition non plus. Fin : **28 jours** ou
**800 courses éligibles notées** après cette date, la première des deux échéances atteinte.

Toute exécution manuelle de `matin` ou `soir` avant cette date (répétitions, `workflow_dispatch`,
exécutions locales, `--dry-run`) est marquée `repetition = 1` dans `bases_editions` et
`bases_results`, exclue du palmarès et du verdict, et signalée comme telle dans le résumé de job.

## Objet jugé

- Horizon : **T_MATIN** (celui que verrait l'abonné). L'horizon T15 est mesuré chaque soir à titre
  secondaire (éditions `mode = mesure`, jamais publiées).
- Paramètres : `params.json` version **2026-09-21.2** (lambdas littérature `(1.0, 0.81, 0.65, 0.55, 0.50)`,
  seuils de solidité top5 A ≥ 0,2275 / B ≥ 0,1466 et top4 A ≥ 0,1344 / B ≥ 0,0781 — terciles de la
  P(3/3) recalibrée du back-test T_MATIN sur le commit moteur `f1677b62` —, recalibration à paliers).
  La recalibration hebdomadaire crée une nouvelle version (calibrateurs seuls) sans effet rétroactif ;
  les seuils et les lambdas ne changent pas pendant la période.
- Notation : JSON public `/resultats/` (source de vérité), courses `DEFINITIVE` + `VERIFIEE_PMU`
  uniquement, `ANNULEE` exclues, non-partants jamais placés, ex æquo notés sur `classement[].rang`,
  contrôle croisé avec `race_results` de l'instantané (divergence = pas de notation, alerte).
- Baselines calculées sur les mêmes courses : 3 premiers du moteur ; 3 plus courtes cotes (`MARKET_BASELINE`).

## Critères principaux

1. **Calibration** : sur les deux tranches supérieures de P recalibrée (k = 3, cible publiée),
   |fréquence observée − P annoncée| ≤ 5 points, avec n ≥ 60 par tranche.
2. **Sélectivité** : taux 3/3 des courses `A` ≥ 1,8 × taux 3/3 des courses `C`, et taux 3/3 des
   courses `A` ≥ 28 %.
3. **Non-régression** : taux 3/3 du trio publié ≥ taux 3/3 des 3 premiers du moteur − 2 points.

## Critères secondaires (informatifs)

Taux ≥ 2/3 par solidité ; taux 2/2 et 1/1 ; rendement des deux structures de ticket
(« 3 bases + XX / 5 associés », « 3 bases + champ total ») sur les courses avec rapports, marqué
« non validé » tant que le mapping `rapports` (`docs/rapports_mapping.md`) n'est pas validé par Steph.

## Décision

- Les trois critères principaux tenus → Steph peut passer `PUBLICATION_MODE=live` (décision écrite).
- Critère 1 échoué → refonte de la recalibration, nouvelle période.
- Critère 2 échoué → l'indice de solidité est retiré de la publication, l'échelle seule est publiée.
- Critère 3 échoué → le trio publié devient « les 3 premiers du moteur » et le service ne garde que
  la tarification.

## Références du back-test préalable (informatif, non décisionnel)

T_MATIN, 339 courses (08/09 → 20/09/2026), commit moteur `f1677b62` : échelle top 5 = 63,4 / 33,3 /
20,1 / 9,1 % ; 3/3 trio joint 20,1 % vs 19,2 % (3 premiers moteur) vs 18,6 % (marché) ; terciles
A / B / C → 3/3 = 33,6 / 15,9 / 10,6 %. Voir `rapports/backtest/2026-09-21_T_MATIN_since-2026-08-25.md`.

_Gelé le 21/09/2026 — session développeur Bases. Seul le champ « Date de début » sera complété,
automatiquement, par la première exécution planifiée._

## Annexe factuelle — activation (ajoutée le 23/09/2026 sur décision du mentor ; critères et seuils inchangés)

- **Jour 1 = 22 septembre 2026**, maintenu : la règle « jamais réécrite » prime.
- Passe fondatrice : `matin` servie par le **filet cron GitHub** à **14:00:22 UTC** (cron `7 9 * * *` servi avec environ cinq heures de retard), run `matin-2026-09-22-e4606b`, commit du dépôt `e284c28`, **11 courses** éligibles publiées en mode ombre, annotation « Métronome silencieux » émise (le Worker n'était pas encore déployé). Le second cron du jour (14:09 UTC) est sorti en répétition.
- Métronome **actif dès le jour 2** : passe `matin · metronome` du 23/09/2026 à 09:05:26 UTC, 24 courses, `repetition = 0`, sans répétition ni annotation.
- Fenêtre d'observation : **du 22/09/2026 au 19/10/2026** (28 jours) ou 800 courses éligibles notées, la première échéance atteinte. **Verdict attendu le 20/10/2026.**
- Note : l'en-tête du palmarès affichait un gabarit brut jusqu'au 23/09 (défaut de présentation corrigé, commit `366f78d`) ; `palmares.json` portait la bonne date dès la passe fondatrice.

## Annexe factuelle — bascule R2 du moteur (ajoutée le 25/09/2026 sur décision du mentor ; critères et seuils inchangés)

- **24/09/2026, 07:16 GMT** : bascule R2 du moteur. La copie Git de `turf_bench.db` est figée depuis le commit `afa32242` (07:01:20 UTC), blob `653cc3c8`, identique dans `7483bd25` (09:01:20 UTC), commit cité par l'édition du 24/09.
- Les **25 T_MATIN du 24/09** ont été verrouillées entre **06:30:23 et 06:30:29 UTC**, avant le gel : l'édition du 24/09 a lu les entrées verrouillées. Édition d'origine : 23 éditions calculées entre **09:06:03 et 09:06:07 UTC** et publiées à **09:06:07 UTC** par la passe du métronome (run `matin-2026-09-24-9086fb`, instantané `7483bd25`) ; les 2 autres courses sont des abstentions (peloton de moins de 8 partants, no-bet). Aucune édition du 24/09 n'a été remplacée ni recalculée : la page affiche une régénération du 25/09 à 09:23:56Z, qui ne fait que réafficher ces éditions.
- **Preuve par empreinte** : `prediction_hash` des 25 lignes, copie Git (référence `rapports/annexe/2026-09-24_empreintes_copie_git.json`, extraite le 25/09 avant la vérification) contre la base R2, par la commande ponctuelle `annexe-empreintes` exécutée dans GitHub Actions. Règle fixée avant la vérification : une course dont l'empreinte diffère est retirée du palmarès, les autres comptent. Résultat consigné dans `rapports/annexe/2026-09-24_verification_empreintes.md` : **25 empreintes identiques sur 25**, aucune course retirée du palmarès (run GitHub Actions `annexe-empreintes` du 25/09 à 10:41 UTC, base R2 sha256 `bcd85dbdac01`, poussée 2026-09-25T10:31:29Z).
- **25/09/2026** : la copie figée ne contient ni course ni prédiction du jour ; aucune édition servie par la passe planifiée de 09:05 (run `matin-2026-09-25-46571e`, arrêt au test de contrat).
- **Source depuis le 25/09/2026** : objet `turf_bench.db` du bucket R2 `turf-engine-data`, en lecture seule, empreinte sha256 vérifiée contre la métadonnée posée par le moteur et `PRAGMA integrity_check` avant tout calcul, plus les JSON publics de résultats. La porte de publication est reconstituée sur les champs de la base, avec les mêmes motifs ; la sélection moteur est lue dans `predictions.selection_json`, identique à celle du rapport public sur 574 courses comparées (08/09 → 24/09). Le contrôle croisé des arrivées porte sur `race_results` de la base R2. Chaque édition stocke l'en-tête de sa source (« Source moteur R2 · sha256 · poussée · run · commit »).

## Amendement n°1 — décidé le 25/09/2026, avant tout verdict, pour une cause extérieure aux résultats

- **Aucun rattrapage rétroactif** : une édition non publiée avant les départs n'est jamais calculée après coup pour le protocole, même depuis les T_MATIN verrouillés sur R2.
- **Journée perdue** = aucune édition valide servie par une passe planifiée. Une journée partielle (passe planifiée tardive, courses à plus de 20 minutes du départ) compte normalement, comme le 22/09.
- Chaque journée perdue **repousse la fin de fenêtre d'un jour**. L'arrêt à 800 courses est inchangé.
- **Au-delà de 7 journées perdues au total**, le protocole est déclaré compromis et redémarre à zéro, mêmes paramètres.
- Critères, seuils et paramètres gelés : **inchangés**.
- Les journées perdues restent visibles dans l'archive (« journée perdue · source moteur indisponible »), et le palmarès affiche la fin de fenêtre repoussée.

## Changements externes de la porte de publication (décision du mentor du 25/09/2026)

- La porte de publication reconstituée par Bases copie la logique du moteur, dont le propriétaire est le développeur Radar ; elle doit évoluer après le 06/10/2026, pendant la fenêtre du protocole.
- **Surveillance** : chaque passe soir compare les verdicts de la porte reconstituée du jour (OK, course annulée, cotes par défaut, pas de T_MATIN) à ce que le moteur a réellement publié. Au premier écart : annotation « Porte divergente », ligne au journal et dans `ALERTES.md`, incident compté dans le rapport hebdomadaire.
- **Alignement** : toute ligne datée de l'annexe du pont Radar qui touche la porte, relayée par Steph, est appliquée par Bases le jour même et consignée ci-dessous comme changement externe (date, ligne relayée, commit Bases). Les paramètres gelés ne sont jamais touchés.
- **Source de la publication réelle du moteur** : à désigner. Elle ne figure ni dans la base R2 ni dans les JSON publics de résultats. Tant qu'elle manque, le soir l'écrit au journal (« comparaison de porte non disponible »).

| Date | Ligne relayée (annexe du pont Radar) | Commit Bases |
|---|---|---|
| — | aucune à ce jour | — |

