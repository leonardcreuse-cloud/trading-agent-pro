# Consigne pour l'agent — version 3 (14/10/2026), en phases

Remplace les versions 1 et 2 de cette consigne.

Références :
- `REGLES_FONDATRICES.md` (version 1), à commiter dans `docs/` **après validation du propriétaire** ;
- audit indépendant du 14/10/2026 sur le commit `d48ef69` ;
- `docs/AUDIT_FIABILITE_2026-10-14.md`.

Chaque phase se termine par un compte rendu et un `git push`. **Ne pas commencer une phase avant la validation de la
précédente par le propriétaire.** La phase 0 peut commencer immédiatement.

---

## Règles permanentes

1. **Ne pas modifier** le signal actuel, PT1, le Stage 3, leurs paramètres, leurs univers ni leurs journaux.
2. Aucun résultat n'est calculé pour une hypothèse **avant** son inscription au registre (R3) et le commit de son
   pré-enregistrement.
3. Aucun ordre réel. L'API IBKR est utilisée en **lecture seule**, de préférence sur le compte de démonstration.
4. Tout changement est daté dans `docs/CHANGELOG.md` **avant** d'être activé.
5. En cas de doute ou si une tâche obligerait à enfreindre une règle : **s'arrêter et demander**.

---

## Phase 0 — Audit réel et remise à plat (immédiat)

**0.1 Suite de tests.** Exécuter la suite complète (`pytest`) sur le PC. Rapporter : nombre de tests réussis,
échoués et ignorés, avec la raison de chaque test ignoré. (Lors de l'audit indépendant, 10 vérifications ciblées
sont passées : dates SEC, données invisibles avant publication, corrections statistiques, rendements à partir de
T+1. La suite complète n'a pas pu être exécutée hors du PC.)

**0.2 Reproduction.** Recalculer, à partir des fichiers bruts stockés, trois chiffres de l'audit du 14/10 :
concordance des clôtures yfinance / Cboe (100 %), concordance des ouvertures (39 %), corrélation des accruals à
252 séances au Stage 1 (+0,054). Rapporter les valeurs obtenues. Un écart doit être expliqué avant la phase 1.

**0.3 Fonctionnement** (aucun effet sur la stratégie) :
- sauvegarde automatique des journaux sur GitHub après chaque passage nocturne (jamais de `--force`) ;
- stockage de l'ouverture, du plus haut et du plus bas Cboe, et écarts avec yfinance affichés dans le rapport ;
- alertes de fraîcheur pour SEC, yfinance, Cboe et FRED ;
- puissance du Stage 3 et bande de bruit de PT1 affichées à côté de leurs chiffres.

**0.4 Étiquetage** (R10) : ajouter les mentions de biais aux résultats des Stages 1 et 2, à `walk_forward.json`, à
`HEURISTIC_EVALUATION.md`, à PT1 et au Stage 3. Ne modifier aucun chiffre.

**0.5 Annulation** : le « Stage 3b » sur environ 400 grandes valeurs, prévu par la version 2 de cette consigne,
n'est pas lancé. Il est remplacé par le cadre des règles fondatrices. Le noter dans le journal des changements.

---

## Phase 1 — Socle de données et registre (après validation des règles)

**1.1 Univers vers l'avenir (R1).** Chaque semaine, construire et stocker l'univers à partir de la liste officielle
de la SEC (`company_tickers_exchange.json`), des données SEC et des prix stockés. Stocker chaque instantané avec
sa date. Rapporter la taille de l'univers obtenu et ses exclusions.

**1.2 Prix.**
- Tester pendant une semaine l'API IBKR en lecture seule (barres quotidiennes « TRADES » et « ADJUSTED_LAST ») sur
  l'univers. Comparer avec Cboe et yfinance (concordance, écart moyen, biais, écart maximal). Mesurer la durée de
  récupération et le respect des limites de débit.
- Si le test est concluant et validé par le propriétaire : IBKR devient la source principale des prix vers
  l'avenir ; yfinance et Cboe servent de recoupement (R2).
- Stocker chaque jour les prix de tous les titres de l'univers, radiés compris jusqu'à la fin de leurs horizons.

**1.3 Sources gratuites** : FRED `DTB3` ; bibliothèque de Kenneth French (facteurs mensuels et quotidiens) ;
Open Source Asset Pricing (liste des signaux, définitions et résultats de réplication). Chaque téléchargement est
journalisé avec son empreinte.

**1.4 Contrôles de qualité** (R2) : recoupement des prix, données aberrantes, variations du nombre d'actions,
journal des sorties de cote avec leur rendement (R1).

**1.5 Coûts** (R7) : module de coûts IBKR (Fixed et Tiered, grille officielle vérifiée et datée), écart estimé par
Corwin et Schultz, change, retenue sur dividendes, impôt. Première utilisation : recalcul en parallèle des
transactions de PT1, en lecture seule, pour plusieurs capitaux.

**1.6 Registre** (R3) : fichier `research/registre_hypotheses.jsonl` chaîné par empreinte, outil d'inscription,
compteur global. Inscrire le signal heuristique actuel et les hypothèses déjà testées aux Stages 1 et 2, avec leur
statut, pour que le compteur parte du vrai nombre de tests déjà réalisés.

**1.7 Premier lot d'hypothèses publiées (L1).** Proposer au propriétaire 5 à 8 hypothèses tirées d'Open Source
Asset Pricing, choisies **sur des critères fixés avant de regarder leurs résultats récents** : publiées dans une
revue, répliquées avec succès par Chen et Zimmermann, calculables avec nos données (prix, SEC, Norgate), rythme
mensuel. Pour chacune : fiche complète du registre et calcul de puissance. Après validation : pré-enregistrement,
puis **démarrage du relevé mensuel vers l'avenir** (R5, P3 anticipée).

---

## Phase 2 — Essai Norgate

**2.1 Préparation, avant d'activer l'essai** : table ticker ↔ CIK ↔ symbole Norgate (attention aux tickers
réutilisés) ; scripts de comparaison des prix (Norgate / Cboe / yfinance / IBKR), des splits et dividendes avec la
SEC, et de la composition historique des indices avec la compilation GitHub `fja05680/sp500` ; **seuils de
décision écrits à l'avance**. Lire la licence (EULA) : ce qui peut être conservé après la fin d'un abonnement.

**2.2 Essai** (21 jours, activé par le propriétaire) : exécuter les comparaisons ; vérifier que la formule
Platinum couvre bien les titres radiés et la composition historique des S&P 500, 400 et 600. Rapport final face
aux seuils. Aucun test de stratégie pendant l'essai.

**2.3 Décision** : achat ou non, par le propriétaire.

---

## Phase 3 — Historique sans biais du survivant (si Norgate est acheté)

**3.1** Construire le panel de 1990 à aujourd'hui selon R1, sorties de cote comprises.

**3.2 Contrôle obligatoire** (R2) : recalcul des facteurs marché, taille, valeur et momentum, et comparaison avec
Kenneth French. Aucun test tant que le seuil n'est pas atteint.

**3.3** Portes P1 (1990–2005) puis P2 (2006–2016, une seule fois) pour le lot L1 et pour le signal heuristique.
Résultats écrits une seule fois, avec le compteur global.

**3.4** Reformuler la proposition Stage 4 selon R1 et R4 ; la soumettre au propriétaire.

---

## Phase 4 — Hypothèses proposées par l'agent

Selon R3 : raison économique obligatoire, budget trimestriel, seuil t ≥ 3, jamais de validation sur 2017–2026,
revue indépendante avant chaque P2. L'agent propose ; le propriétaire valide l'inscription au registre.

---

## Phase 5 — Simulation PT2 (porte P4)

Pour les hypothèses ayant franchi P2 et en cours de P3 : pré-enregistrer un portefeuille papier PT2 selon R6 et R7.
Plus tard, et avec l'accord du propriétaire, envoyer ces ordres au **compte de démonstration** IBKR pour comparer
les exécutions simulées aux exécutions de démonstration.

---

## Phase 6 — Argent réel

Uniquement selon R9, sur décision écrite du propriétaire. L'agent ne prépare rien de cette phase sans demande
explicite.

---

## Actions qui reviennent au propriétaire

1. Relire et valider `REGLES_FONDATRICES.md`, y compris les valeurs **(proposées)**, ou les modifier avant validation.
2. Dans TWS / IB Gateway : activer l'API en mode lecture seule, de préférence sur le compte de démonstration, et
   vérifier quel abonnement aux données de marché est nécessaire et son prix.
3. Décider de passer le dépôt GitHub en privé.
4. Activer l'essai Norgate à la fin de la phase 2.1, puis décider de l'achat.
5. Valider le lot L1 avant son démarrage.
