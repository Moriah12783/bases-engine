# Protocole pré-enregistré — service Bases (mode ombre)

Rédigé le 21 septembre 2026, **avant** la première exécution en mode ombre, à partir du §10 du
`BRIEF_SERVICE_BASES.md`. Rien de ce protocole ne se modifie après la première exécution. Toute
évolution de paramètre pendant la période est consignée avec date dans `CHANGELOG.md` et n'affecte
que les éditions postérieures. Le palmarès n'est jamais retouché ni filtré.

## Période

**Date de début : à renseigner par la première exécution planifiée.**

**Commit du dépôt `bases-engine` à l'activation : à renseigner par la première exécution planifiée.**

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
