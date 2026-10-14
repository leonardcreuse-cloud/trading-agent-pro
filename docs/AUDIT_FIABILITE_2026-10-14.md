# Audit de fiabilité de l'agent (14/10/2026)

**Méthode.**
- J'ai lu le code pour savoir quelles sources alimentent réellement le signal, le portefeuille PT1 et le rapport.
- J'ai mesuré la fiabilité sur les données stockées (octobre 2025 → octobre 2026).
- Aucun résultat de stratégie n'a été consulté pour cet audit. Les deux mesures de puissance (sections 3 et 4)
  utilisent des formules ou des portefeuilles tirés au hasard, jamais le signal.

## 1. Verdict honnête

1. **La mesure est fiable.** Les données qui servent au signal et à PT1 sont officielles (SEC) ou recoupées entre
   deux fournisseurs. Les journaux sont infalsifiables, et il n'y a ni anticipation (look-ahead) ni donnée inventée.
2. **La rentabilité n'est pas démontrée et, à ce jour, aucun élément ne l'indique.**
   - Les tests sur le passé (Stage 1 et Stage 2, 430 tests au total) n'ont trouvé **aucun avantage
     statistiquement fiable**.
   - Le signal suivi depuis le 09/10 est une heuristique **sans preuve historique**.
3. **Les 52 semaines ne pourront probablement pas prouver la rentabilité.**
   - Le Stage 3 n'a que **6 % à 19 % de chances** de confirmer un avantage réaliste (corrélation de 0,03).
   - PT1 devrait battre les 40 titres à poids égal d'environ **+23 % en un an** pour que ce ne soit pas
     attribuable au hasard.
   - Le résultat le plus probable à 52 semaines est donc : « non confirmé ». Ce ne sera pas la preuve qu'il n'y a
     pas d'effet ; ce sera la preuve qu'on ne peut pas trancher.

Être fiable et être rentable sont deux choses différentes. L'agent est aujourd'hui un **instrument de mesure
fiable**. Ce n'est pas encore un système rentable, et rien ne permet de le présenter comme tel.

## 2. Fiabilité des sources (mesurée)

| Niveau | Source | Sert à | Fiabilité constatée |
|---|---|---|---|
| **A, officiel** | SEC EDGAR : dépôts, XBRL, formulaires 4, heures d'acceptation | Signal (fondamentaux, initiés), rapport | Source primaire, chaque donnée datée au moment où elle est devenue publique. Limite : les données XBRL sont saisies par les entreprises elles-mêmes, qui font parfois des erreurs de balisage. Le contrôle des splits implicites (HON) en a détecté une. |
| **A, officiel** | FRED/ALFRED, BLS, BEA, EIA, CFTC, FINRA, Réserve fédérale, Federal Register | Rapport (macro, positionnement) | Sources primaires. FRED/ALFRED conserve les révisions successives (vintages). Les clés BLS, BEA et EIA fonctionnent sur ton PC depuis le 13/10. |
| **B, marché recoupé** | yfinance : clôtures et plus bas | Signal technique, stops et valorisation de PT1 | **Clôtures identiques à Cboe dans 100 % des cas, plus bas dans 99,4 %** (écart maximal 0,03 %), sur 10 320 séances. Aucune des 192 853 valeurs brutes n'a changé d'une récupération à l'autre. |
| **B, marché recoupé** | Cboe : historique quotidien différé | 2e source de prix (audit) | Concorde avec yfinance (ci-dessus). Limite : accès par une adresse non documentée, conditions d'usage floues. |
| **C, à surveiller** | yfinance : ouvertures | Prix d'exécution de PT1 | **Seulement 39 % identiques à Cboe.** 12 % des séances diffèrent de plus de 0,25 %, 3 % de plus de 0,5 %, jusqu'à 1,74 %. L'écart moyen est de 9,5 points de base, sans biais (−1,75 pb en moyenne). L'« ouverture » diffère selon le fournisseur (enchère d'ouverture ou premier échange). C'est du bruit du même ordre que les frais simulés, sans biais systématique. |
| **C, à surveiller** | yfinance : dividendes et splits | Ajustements de PT1 | Non officiel, sans contre-vérification automatique pour les dividendes (petit impact, environ 1 %/an). Les splits sont recoupés avec le nombre d'actions déclaré à la SEC. |
| **C, à surveiller** | yfinance (service en général) | Toute la partie prix | Non officiel ; Yahoo peut changer ou bloquer l'accès. C'est le **point unique de défaillance** de PT1. |
| **C** | Liste S&P 500 (compilation GitHub) | Univers des recherches | Non officielle (S&P est sous licence). Membres actuels seulement : biais du survivant. |
| **D, indicatif** | NewsAPI (sentiment), GDELT, options et calendrier des résultats yfinance | Rapport seulement | Pas fiables à 100 %. **Exclus du signal** (signal « hors news »), affichés avec leurs réserves. |

**À retenir :** le signal ne repose sur aucune source de niveau D. PT1 ne dépend que de yfinance (niveaux B et C).

## 3. Fiabilité de la conclusion du Stage 3

Le protocole a été fixé à l'avance et ne peut pas être modifié : 40 titres, 52 relevés, corrélation à 20 jours
(P1) et à 5 jours (P2), seuil de 2,5 %.

| Corrélation réelle du signal | Chance de confirmer P1 (20 jours) | Chance de confirmer P2 (5 jours) |
|---|---|---|
| 0,02 | 4 % | 9 % |
| 0,03 (réaliste) | 6 % | 19 % |
| 0,05 | 13 % | 50 % |
| 0,10 | 50 % | 99 % |

Ces chiffres sont optimistes : ils supposent une dispersion minimale des corrélations hebdomadaires. Seul un signal
exceptionnellement fort serait confirmé. Le protocole le reconnaissait déjà (« only a large and stable IC can be
confirmed ») ; ces chiffres le quantifient.

## 4. Ce que PT1 pourra montrer en 52 semaines

- **Bruit mesuré** : un portefeuille de 8 titres tirés au hasard parmi les 40 s'écarte de la moyenne des 40 de
  1,6 % par semaine, soit environ **11,6 % sur un an**. Données 2021–2026, 2 000 tirages, sans le signal.
- Pour que l'écart soit significatif après un an, il faudrait **environ +23 %** de surperformance. Une stratégie
  réellement compétente fait plutôt +2 à +5 %/an.
- **Le résultat de PT1 à 52 semaines reflétera surtout le marché, les secteurs de l'univers (très orienté
  technologie) et la chance.** Il validera le fonctionnement (ordres, stops, frais, journaux), pas la rentabilité.

**Écarts avec un vrai compte pour un investisseur en France (non simulés) :**
- le change EUR/USD (±5 à 10 %/an) ;
- les frais de conversion de devises (souvent 0,1 à 0,25 % par opération) ;
- les commissions par ordre d'un courtier de détail ;
- la fiscalité (prélèvement forfaitaire unique de 30 % sur les plus-values).

Avec un rééquilibrage hebdomadaire, ces frais réels peuvent dépasser nettement les 8 pb par côté simulés.

## 5. Fiabilité du fonctionnement

| Risque | État |
|---|---|
| PC éteint un soir de semaine | **Couvert** : Windows relance la tâche manquée à l'allumage (StartWhenAvailable) et PT1 traite les séances en retard. |
| PC éteint tout le week-end | **Corrigé aujourd'hui.** Avant, le relevé du Stage 3 était perdu, même si le PC était rallumé lundi matin. Désormais, l'enregistrement est aussi tenté le lundi : il est valide avant l'ouverture (15:30 heure de Paris) ; après, rien n'est écrit. |
| Sauvegarde des journaux | **Manuelle** (`git push` du lundi). Si le PC est perdu, toutes les données depuis la dernière sauvegarde disparaissent. |
| yfinance indisponible | Non couvert : PT1 s'arrête jusqu'au retour de la source. Cboe fournit pourtant aussi ouverture, plus haut, plus bas et clôture, mais l'agent n'en stocke que la clôture. |
| Bug du secteur de la semaine 1 | Corrigé. La semaine 1 reste sous-investie (60 % de cash ; UBER n'a que 9 actions pour la même raison) et documentée. |

## 6. Plan d'action proposé (par ordre de priorité)

**Sans toucher à la stratégie, faisable tout de suite :**
1. **Sauvegarde automatique** des journaux sur GitHub après chaque passage nocturne.
2. **Stocker l'ouverture, le plus haut et le plus bas de Cboe** et recouper chaque exécution, stop et valorisation
   de PT1. Les écarts seraient signalés dans le rapport, sans changer les prix utilisés.
3. **Afficher dans le rapport hebdomadaire** la puissance du Stage 3 et l'incertitude de PT1 (sections 3 et 4),
   pour qu'aucun chiffre intermédiaire ne soit surinterprété.

**Décisions qui te reviennent :**
4. **Une source de secours en cas de panne de yfinance** (Cboe pour les prix de PT1). C'est un changement
   d'implémentation : il doit être décidé et daté avant d'être utilisé.
5. **Augmenter réellement les chances de conclure.** Ce serait un nouveau protocole fixé à l'avance (« Stage 3b »),
   sans modifier le Stage 3 :
   - le même signal enregistré chaque semaine sur environ 500 titres au lieu de 40 ;
   - la marge d'erreur serait environ 3,5 fois plus petite ;
   - une corrélation de 0,03 deviendrait détectable à 5 jours avec environ 80 % de chances.
   C'est le levier principal pour que les 52 semaines servent à quelque chose.
6. **Tester des effets documentés sur plusieurs décennies** (momentum, qualité, faible volatilité) plutôt qu'une
   heuristique, par de nouveaux protocoles fixés à l'avance.

**À ne jamais faire :** modifier le signal, PT1 ou le Stage 3 en cours de route pour « améliorer » les chiffres.
Cela rendrait les 52 semaines inutilisables.
