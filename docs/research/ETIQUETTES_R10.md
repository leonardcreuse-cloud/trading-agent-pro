# Étiquettes de biais (règle R10), ajoutées le 15/10/2026

Les règles fondatrices (`docs/REGLES_FONDATRICES.md`, version 1, commit eadef14) imposent d'étiqueter les résultats
existants sans en modifier aucun chiffre.

**Méthode.**
- **Fichiers de résultats JSON : non modifiés.** Ils restent identiques octet pour octet, et l'étiquette figure dans
  ce registre. Leur empreinte SHA-256, recalculée le 15/10/2026, prouve qu'ils n'ont pas changé.
- **Documents de résultats (.md) : étiquette ajoutée en tête**, sans toucher au reste.
- **Pré-enregistrements : jamais modifiés** (Stage 2, Stage 3). L'étiquette du Stage 3 est affichée à côté de ses
  chiffres dans le rapport hebdomadaire et dans le tableau de bord.

| Résultat | Fichier | SHA-256 au 15/10/2026 | Étiquette |
|---|---|---|---|
| Stage 1 | `reports/research_stage1.json` (inchangé) | `c4ee56bea6ee931b0d8f7c033a7eb4e7f90b44e715dd5cd5e8f6b62cd9f41d81` | Avec biais du survivant, période 2017–2026 : ne valide rien |
| Stage 1 | `docs/research/STAGE1_RESULTS.md` | étiquette en tête | idem |
| Stage 2 | `reports/research_stage2.json` (inchangé) | `478f1f7ef414a2513190be94bc30f6881ca250a330fa02f412854ee0fadecf9d` | idem |
| Stage 2 | `docs/research/STAGE2_RESULTS.md` | étiquette en tête | idem |
| Validation walk-forward | `reports/walk_forward.json` (inchangé ; son empreinte est citée par HEURISTIC_EVALUATION.md) | `98e1f88fc6856500e71a1971c85bb1f71efdbda92ed63369bc1eed4995610f0e` | Avec biais du survivant, période 2017–2026 : ne valide rien ; univers choisi en 2026 : biais de sélection |
| Évaluation de l'heuristique | `reports/heuristic_evaluation.json` (inchangé) | `0e2d0b6bae701e774b24eef2cfea761d05db65b0d3e11d0e2bf3d53f33474a60` | idem |
| Évaluation de l'heuristique | `docs/research/HEURISTIC_EVALUATION.md` | étiquette en tête ; le générateur `src/heuristic_evaluation.py` la reproduit | idem |
| PT1 | `docs/research/PAPER_STRATEGY_PT1.md` | entrée datée à la fin (journal en ajout seul) | Univers choisi en 2026 : biais de sélection |
| PT1 | rapport hebdomadaire, tableau de bord, `main.py paper report` | affichage | idem |
| Stage 3 | `docs/research/STAGE3_PREREGISTRATION.md` (**non modifié** : pré-enregistrement), `d3ff5c03d497b8518b355f788bb13674ac861a84cda534b5b8c8045cfb15196c` | — | Univers choisi en 2026 : biais de sélection |
| Stage 3 | rapport hebdomadaire et tableau de bord | affichage | idem |

**Futurs résultats.** Les prochains fichiers produits par `src/research/experiment.py` et
`src/heuristic_evaluation.py` contiendront un champ `label_r10`. `src/walk_forward.py` n'a pas été modifié,
car le Stage 3 importe ce module : son étiquette passe uniquement par ce registre.
