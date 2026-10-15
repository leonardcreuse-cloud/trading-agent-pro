# Règles fondatrices de l'agent d'analyse et de trading (version 1, proposée le 14/10/2026)

Statut : **proposition à valider par le propriétaire.** Une fois validé, ce fichier est commité dans
`docs/REGLES_FONDATRICES.md` ; son SHA-256 et la date du commit font foi. Toute modification ultérieure crée une
version 2 datée, jamais appliquée rétroactivement à un test déjà commencé.

Les valeurs marquées **(proposée)** sont des choix de méthode raisonnables, pas des vérités : le propriétaire peut
les changer **avant** validation, jamais après avoir vu un résultat.

---

## R0. Ce que ces règles promettent, et ce qu'elles ne promettent pas

- Elles garantissent que **tout résultat annoncé est vrai** : sans anticipation, sans biais du survivant, avec
  les coûts réels, et corrigé pour le nombre de tests réalisés.
- Elles **ne garantissent pas** un bénéfice. Un résultat « aucun avantage démontré » est un résultat valable.
- **Référence à battre** : ce que le propriétaire ferait sans agent, c'est-à-dire acheter et conserver un ETF
  S&P 500 de type UCITS (achetable par un particulier européen), en euros, après frais et impôts. L'agent n'est
  utile que s'il fait mieux que cette référence, de façon prouvée.

---

## R1. Univers : défini par des règles, jamais choisi à la main

| Règle | Valeur |
|---|---|
| Titres admis | Actions ordinaires de sociétés américaines cotées au NYSE, au Nasdaq ou au NYSE American |
| Exclus | ETF, fonds, ADR, SPAC, actions de préférence, unités, warrants, titres de gré à gré |
| Une société = une ligne | Une seule classe d'actions par CIK (la plus liquide à la date T) |
| Prix minimal | 5 $ à la clôture de T **(proposée)** |
| Liquidité minimale | Volume moyen sur 20 séances ≥ 5 M$ par jour, calculé à T **(proposée)** |
| Taille minimale | Capitalisation ≥ 300 M$ à T **(proposée)** |
| Banques, assurances, immobilier | Exclus **uniquement** des hypothèses utilisant des ratios comptables (non comparables) ; admis pour les hypothèses de prix |
| Date d'évaluation | Tous les filtres sont recalculés **à chaque date**, avec les seules données connues à cette date |
| Contrôle de robustesse | Le même test est refait sur les membres du S&P 1500 à chaque date (Norgate), pour comparaison |

**Sorties de cote** : un titre radié, racheté ou fusionné reste dans l'évaluation jusqu'à la fin de ses horizons.
Rendement de sortie, dans cet ordre :
1. prix de rachat en numéraire publié dans les documents SEC, s'il existe ;
2. sinon, dernier cours coté ;
3. si la radiation est due à une faillite ou à un non-respect des règles de cotation et qu'aucun prix n'existe :
   −30 % (NYSE / NYSE American, Shumway 1997) ou −55 % (Nasdaq, Shumway et Warther 1999) depuis le dernier cours.

Chaque cas est journalisé.

---

## R2. Sources : hiérarchie et usage

| Rang | Sources | Usage autorisé |
|---|---|---|
| A — officiel | SEC EDGAR, FRED / ALFRED, BLS, BEA, Réserve fédérale | Signaux, rapports |
| B — sous licence, documenté | Norgate Data (historique, radiés compris), données de marché IBKR (API en lecture seule) | Prix des tests et des relevés |
| C — référence académique | Bibliothèque de Kenneth French, Open Source Asset Pricing (Chen et Zimmermann) | Contrôle des calculs, réserve d'hypothèses, comparaison |
| D — non officiel | yfinance, historique Cboe (adresse non documentée), listes GitHub | **Recoupement et secours seulement**, jamais seule source d'un résultat |
| E — indicatif | NewsAPI, GDELT, sentiment par mots-clés, options et calendrier yfinance | Rapport seulement, **jamais** dans un signal ou un test |

Règles d'usage :
- **Date de disponibilité** : chaque donnée porte l'instant où elle est devenue publique (heure d'acceptation SEC,
  date de version ALFRED, clôture de séance). Un calcul à la date T n'utilise que des données publiques avant T.
- **Stockage au fil de l'eau** : tout prix ou donnée utilisé dans un relevé vers l'avenir est stocké le jour même.
  Aucun résultat vers l'avenir ne dépend d'un re-téléchargement.
- **Recoupement** : chaque prix utilisé est comparé à une seconde source ; tout écart de plus de 0,5 % est
  journalisé et signalé dans le rapport.
- **Contrôle de calcul obligatoire** : avant tout test sur le passé, l'agent recalcule les facteurs marché, taille,
  valeur et momentum et les compare à ceux de Kenneth French sur la même période. Corrélation mensuelle minimale
  de 0,9 **(proposée)** ; en dessous, aucun test n'est lancé tant que l'écart n'est pas expliqué.
- **Données aberrantes** : valeurs comptables plafonnées aux 1er et 99e centiles de chaque date ; variation de
  nombre d'actions de plus de 50 % non expliquée par un split : donnée écartée et journalisée.

---

## R3. Hypothèses : registre obligatoire

Toute hypothèse est inscrite dans `research/registre_hypotheses.jsonl` (ajout seulement, chaîné par empreinte
SHA-256 comme les journaux actuels) **avant** tout calcul de résultat. Champs obligatoires :

| Champ | Contenu |
|---|---|
| ID | Identifiant unique, jamais réutilisé |
| Origine | Publication scientifique (référence) ou proposition de l'agent |
| Raison économique | Pourquoi l'effet existerait et persisterait : prime de risque, comportement, contrainte |
| Mesure | Formule exacte, données utilisées, date de disponibilité de chaque donnée |
| Sens attendu | + ou −, fixé à l'avance |
| Horizon et rythme | Horizon de mesure ; rééquilibrage mensuel par défaut |
| Univers | R1, avec ou sans exclusion des financières |
| Effet visé | Corrélation de rang attendue, pour le calcul de puissance |
| Statut | proposée → découverte → validation → confirmation → simulation → rejetée / retenue |

Règles :
- **Compteur global** : le registre compte tous les tests jamais réalisés, échecs compris. Ce nombre est rappelé à
  côté de chaque résultat.
- **Pas de seconde chance déguisée** : une hypothèse rejetée ne peut pas être retestée sous un autre nom ou avec un
  paramètre voisin. Une vraie variante est une nouvelle hypothèse, qui compte dans le compteur.
- **Budget** : au plus 20 nouvelles hypothèses par trimestre **(proposée)**, pour garder les corrections
  statistiques gérables.
- **Seuil plus strict pour l'agent** : une hypothèse proposée par l'agent (et non issue d'une publication
  répliquée) doit atteindre t ≥ 3 en validation, recommandation de Harvey, Liu et Zhu (2016).
- **Attente réaliste** : un effet publié perd en moyenne environ la moitié de sa force après publication
  (McLean et Pontiff, 2016). L'effet visé de la colonne « Effet visé » en tient compte.

---

## R4. Périodes : découpage fixé une fois pour toutes

| Période | Rôle | Règle |
|---|---|---|
| 1990–2005 | Découverte | L'agent peut explorer ; aucun résultat n'y est une preuve |
| 2006–2016 | Validation | **Une seule utilisation par hypothèse** ; tout passage est inscrit au registre |
| 2017–2026 | Description seulement | Déjà examinée (Stages 1 et 2) et connue des modèles d'IA : ne valide jamais rien |
| Après la date de pré-enregistrement | Confirmation vers l'avenir | Seule preuve décisive |

Cas particulier : les données comptables XBRL de la SEC ne commencent qu'en 2009–2011. Les hypothèses comptables
n'ont donc pas de période de découverte ; elles sont validées sur 2011–2016, avec une puissance faible
documentée, et reposent surtout sur la confirmation vers l'avenir.

---

## R5. Portes à franchir

| Porte | Test | Critère de passage |
|---|---|---|
| P1 Découverte | Corrélation de rang mensuelle, erreur standard de Newey-West | Sens attendu, t ≥ 2 |
| P2 Validation (une fois) | Même mesure + portefeuille construit selon R6 après coûts (R7) | Correction de Holm sur le lot (p < 0,05) ; t ≥ 3 si hypothèse de l'agent ; portefeuille net > univers à poids égal ; rendement non expliqué par les facteurs de Kenneth French ≥ 0 |
| P3 Confirmation vers l'avenir | Relevé mensuel pré-enregistré, durée fixée par un calcul de puissance (au moins 80 % pour l'effet visé) | Sens attendu et p < 0,05 après correction de Holm sur les hypothèses confirmées en parallèle |
| P4 Simulation | Portefeuille papier sur la même période que P3, coûts IBKR, impôts, en euros | Bat la référence de R0 après frais et impôts |
| P5 Argent réel | Décision du propriétaire seul | R9 |

Une hypothèse qui échoue à une porte est **rejetée définitivement** (R3).

Pour gagner du temps, le relevé vers l'avenir (P3) d'une hypothèse issue d'une publication peut commencer **avant**
P1 et P2. Il ne compte que si l'hypothèse franchit ensuite P2 ; sinon il est clos et archivé.

---

## R6. Construction du portefeuille

| Règle | Valeur |
|---|---|
| Sens | Achat seulement. Pas de vente à découvert, pas de levier, pas de dérivés, pas de CFD |
| Nombre de positions | 20 à 30 **(proposée)** |
| Poids | Égal **(proposée)** |
| Plafond par titre | 6 % à l'achat **(proposée)** |
| Plafond par secteur | 25 % (code SIC de la SEC, grand groupe) **(proposée)** |
| Rythme | Rééquilibrage mensuel, premier jour de bourse du mois |
| Frein au renouvellement | Achat dans les 10 % meilleurs du classement, vente seulement en sortie des 30 % meilleurs **(proposée)** |
| Stops individuels | Aucun par défaut : ils augmentent les frais sans preuve d'utilité. Une règle de stop est une hypothèse à tester comme les autres |
| Exécution | Ordre à l'ouverture (enchère d'ouverture), comme PT1 |
| Liquidités | Rémunérées au taux des bons du Trésor à 3 mois (FRED `DTB3`) dans les calculs |

---

## R7. Coûts : toujours appliqués, jamais un résultat brut seul

| Élément | Règle |
|---|---|
| Commission | Grille officielle IBKR en vigueur (scénarios Fixed et Tiered), vérifiée et datée |
| Écart achat-vente | Selon la liquidité de chaque titre à T : estimation de Corwin et Schultz (2012) à partir des plus hauts et plus bas, avec un minimum de 2 pb **(proposée)** |
| Glissement | 5 pb par ordre **(proposée)** |
| Change | Conversion EUR → USD au départ, aux frais IBKR publiés ; valorisation en euros avec FRED `DEXUSEU` |
| Dividendes | Retenue à la source américaine de 15 % (formulaire W-8BEN) |
| Impôt | Prélèvement forfaitaire unique de 30 % sur les plus-values réalisées, par année civile |
| Taille du portefeuille | Résultats calculés pour plusieurs capitaux, car les commissions minimales en dépendent |

---

## R8. Fonctionnement

- Journaux en **ajout seulement**, chaînés par empreinte (déjà en place) ; aucun résultat ne peut être réécrit.
- **Sauvegarde automatique** sur GitHub après chaque passage ; dépôt à passer en **privé** **(proposée)**, car il
  contient désormais une stratégie et des journaux.
- **Alertes** : source en panne, donnée périmée, part anormale de titres sans donnée, écart entre sources.
- **Aucun secret dans le dépôt** ; API IBKR en mode **lecture seule** tant que R9 n'est pas franchie.
- Suite de tests complète exécutée avant chaque commit ; chaque nouveau module a ses tests.
- **Revue indépendante** à chaque porte P2 à P5 : une session sans historique du projet relit le code et les
  résultats avant que la porte soit déclarée franchie.

---

## R9. Passage à l'argent réel et arrêt

Conditions cumulatives :
1. au moins une hypothèse a franchi P1 à P4 ;
2. la revue indépendante de P4 ne relève aucun défaut bloquant ;
3. le propriétaire donne son accord écrit, daté, dans le dépôt.

Ensuite :
- chaque ordre réel est **validé par le propriétaire** ;
- le montant est choisi par le propriétaire seul ;
- **règles d'arrêt écrites avant le premier ordre réel** : écart du portefeuille réel avec sa simulation, et perte
  relative à la référence de R0 au-delà de seuils fixés à ce moment ;
- revue annuelle : toute hypothèse dont la confirmation vers l'avenir ne tient plus est retirée.

---

## R10. Tests déjà en cours

- **PT1 et Stage 3** continuent sans modification jusqu'à leur terme (52 relevés), comme témoins. Leurs résultats
  sont étiquetés « univers choisi en 2026 : biais de sélection ».
- **Stages 1 et 2, `walk_forward.json`, `HEURISTIC_EVALUATION.md`** : conservés tels quels, étiquetés « avec biais du
  survivant, période 2017–2026 : ne valide rien ».
- **Proposition Stage 4** : reformulée selon ces règles (univers R1, périodes R4) avant toute approbation.
- **Signal heuristique actuel** : traité comme une hypothèse parmi d'autres ; il passe par les mêmes portes.
