# Audit complet indépendant de l'agent de trading — 17/10/2026

- **Objet audité** : dépôt `leonardcreuse-cloud/trading-agent-pro`, branche `claude/nifty-ramanujan-u1p317`, commit
  `e627899` (tête de la branche le 17/10/2026). La copie locale était un clone partiel sur un ancien commit
  (`363a4cb`) ; elle a été avancée sur `e627899` sans modification (avance rapide, aucune réécriture).
- **Documents lus** : `docs/REGLES_FONDATRICES.md` (v1, SHA-256 `53997a1c…d21d42`, vérifié identique),
  `REGLES_FONDATRICES_v2.md` (fourni), `docs/CONSIGNE_AGENT_2026-10-14.md`, `CONSIGNE_COMPLEMENT_PHASE1_2026-10-17.md`
  (fourni), `docs/AUDIT_FIABILITE_2026-10-14.md`, `docs/CHANGELOG.md`, `docs/HANDOFF.md`, `docs/research/`.
- **Environnement d'exécution** : conteneur Linux, Python 3.13.16, environnement virtuel isolé hors dépôt ;
  versions installées par `requirements.txt` le 17/10 : pandas 3.0.6, numpy 2.5.4, yfinance 1.7.0, scikit-learn 1.9.1,
  pytest 9.1.1, stockstats 0.6.2.
- **Respect des interdictions** : aucun fichier du dépôt modifié, sauf ce rapport. Aucune connexion à un courtier,
  aucun secret affiché. Les résultats intermédiaires de PT1 et du Stage 3 (performances, corrélations, classements,
  scores) **n'ont pas été consultés**. Le seul script exécuté sur leurs fichiers n'affiche que la mécanique : types
  d'entrées, chaînes d'empreintes, horodatages, motifs de rejet (§ C-mécanique). Aucune proposition de ce rapport ne
  s'appuie sur un résultat de stratégie.
- **Statuts** : **vérifié** = preuve fournie (fichier:ligne, commande et sortie, ou calcul refait) ; **probable** =
  indices concordants ; **non vérifiable** = raison donnée. « À vérifier » = source externe non confirmée par une
  source primaire.

---

## 1. Verdict (10 lignes)

1. **Fiabilité : correcte sur l'essentiel.** Les journaux vérifient, les horodatages précèdent l'ouverture, aucun ordre
   réel n'est possible, et aucune anticipation n'apparaît dans les décisions hebdomadaires. Mais trois chiffres affichés
   sont faux : la référence de PT1 perd les dividendes, le test du Stage 3 a environ 4 % de faux positifs (2,5 % annoncés),
   et l'explication de l'écart HON est inversée.
2. **Rentabilité : non démontrée, et pas démontrable avant plusieurs années.** Il n'y a pas d'historique sans biais du
   survivant, et un relevé vers l'avenir demande 2 à 16 ans. Il faudrait battre de +1,3 à +2,5 %/an bruts un ETF
   S&P 500 détenu en PEA : c'est plus que l'effet attendu de la plupart des anomalies publiées sur les grandes valeurs.
3. **Les 3 problèmes les plus graves.** (a) R0 et R7 ignorent la fiscalité réelle : PEA, PFU 2026, dividendes.
   (b) Aucun chemin de preuve n'existe à court terme : pas de Norgate, puissance trop faible. (c) Les sauvegardes sont
   inactives (aucun envoi depuis le 15/10, base jamais copiée) et l'horodatage dépend de l'horloge du PC.

---

## 2. Tableau des constats

Gravité : **B** = bloquant, **M** = majeur, **m** = mineur. Effort : XS < 1 h, S ≤ 1 jour, M ≤ 1 semaine, L > 1 semaine.
Le détail et les preuves complètes de chaque constat suivent le tableau.

| ID | Grav. | Dom. | Constat | Preuve (résumé) | Statut | Impact | Correction proposée | Effort |
|---|---|---|---|---|---|---|---|---|
| C01 | B | G, D | Aucune preuve d'avantage exploitable, et aucune démonstration possible avec les données actuelles avant plusieurs années | Stages 1–2 : 0 résultat significatif ; Stage 3 : puissance de conception 6 % / 19 % ; PT1 : bande de bruit ±22,7 % ; pas de données sans biais du survivant ; calcul de puissance de P3 (§ C11) | vérifié | Le projet ne peut pas justifier d'argent réel avant des relevés de plusieurs années | Lancer au plus tôt les relevés vers l'avenir de L1 ; décider de Norgate ; voir plan § 7 | — |
| C02 | B | E, G, H | R0 et R7 ne décrivent pas la vraie fiscalité d'un particulier français : PEA ignoré, PFU 30 % périmé (31,4 % en 2026, à vérifier), prélèvements sociaux sur dividendes oubliés, report des pertes sur 10 ans absent, effet du report d'imposition ignoré | Texte R0 (v1 l. 17–19), R7 (l. 160–163) ; calcul refait : seuil de +1,3 à +2,5 %/an bruts pour égaler un ETF en PEA | vérifié (calcul) ; taux 2026 à vérifier | Le critère P4 / R9 compare à une mauvaise référence : risque de déclarer rentable une stratégie qui ne l'est pas | Réécrire R0 et R7 (§ 3, R0 et R7) | S |
| C03 | B | F | Sauvegardes inopérantes : aucune branche `sauvegarde/journaux-pc` sur GitHub ; dernier envoi le 15/10 ; journaux PT1 sur GitHub arrêtés à la valorisation du 13/10 ; base SQLite et fichiers bruts jamais sauvegardés hors du PC | `git ls-remote origin` ; API GitHub `pushed_at` = 2026-10-15T07:05:33Z ; `docs/LOCAL_RUN.md` (aucune sauvegarde de `data/`) | vérifié (GitHub) ; état du PC non vérifiable | Une panne du PC détruit les preuves vers l'avenir (journaux, registre, prix stockés le jour même au titre de R2) | Vérifier le premier envoi réel ; sauvegarde chiffrée quotidienne de `data/` hors PC ; alerte si aucun envoi depuis 24 h | S |
| C04 | M | E, C | Les références de PT1 (SPY et univers à poids égal) sont calculées **sans dividendes** : la base est figée sur un prix ajusté d'une ancienne version Yahoo | `src/paper.py:508-520` ; calcul synthétique : −1,00 % calculé au lieu de 0,00 % | vérifié | Biais en faveur de PT1 d'environ le rendement du dividende (≈ 1 %/an) | Recalculer les références à partir des clôtures non ajustées et des dividendes stockés (vue en lecture seule), ou rebaser à chaque passage ; déviation datée dans `PAPER_STRATEGY_PT1.md` sur décision du propriétaire | S |
| C05 | M | D | Le test P1 du Stage 3 (H = 20, n_eff = 13) utilise la loi normale : sa taille réelle est d'environ **4,0 %** au lieu de 2,5 % | `src/scoring_signal_fixed.py:38-40`, `src/walk_forward.py:100-118` ; simulation de 200 000 tirages sous l'hypothèse nulle | vérifié (modèle de recouvrement idéalisé) | Une « confirmation » P1 serait moins probante qu'annoncé ; risque global d'environ 7 % au lieu de 5 % | Protocole figé, donc rien à modifier dans le Stage 3, mais publier la taille réelle à côté du résultat ; pour l'avenir, loi t et valeurs critiques calibrées par simulation | XS |
| C06 | M | B | HON : la prémisse du point 1.0b.1 est **inversée**. Le 29/06/2026, HON a scindé Honeywell Aerospace et regroupé ses actions (1 pour 2). Cboe sert l'historique ajusté de ce regroupement (×2) ; la conversion de PT1 donne les prix traités et égale Cboe sur toute la période de PT1 | 8-K SEC du 29/06/2026 (rubriques 2.01 et 5.03) ; ratio Cboe/Yahoo : 2,0233 → 1,907 → 1,000 ; ratios yfinance 1,061 (30/10/2025) et 0,9535 (29/06/2026) | vérifié (SEC, données) ; niveau absolu « traité » probable | CHANGELOG, audit et script de reproduction se trompent d'explication ; le point 1.0b.1 provoquerait un arrêt à tort | Erratum daté ; réécrire 1.0b.1 (§ 4) ; troisième source de prix réellement traités (IBKR TRADES) | XS |
| C07 | M | D, H | Le nombre de tests est sous-estimé : au moins **852 statistiques t** dans les trois fichiers de résultats (walk-forward 388, Stage 1 220, Stage 2 244), contre « 430 tests » annoncés. Les versions antérieures du walk-forward sont écrasées. L'unité de « test » n'est pas définie | Comptage des champs `t_stat` ; `.gitignore` (`reports/history/`) ; R3 | vérifié | Le compteur global de R3 partirait d'un chiffre faux | Définir l'unité de test (§ 3, R3) ; inscrire ≥ 852 comme borne basse ; reconstituer les versions depuis l'historique git | S |
| C08 | M | D, F | La validité « avant l'ouverture » des relevés repose sur l'horloge du PC et sur des dates de commit locales. Le registre chaîné détecte une modification, pas une reconstruction complète | `src/prospective.py:263` (`utc_now_iso()`), `src/backup.py` (dates de commit locales) | vérifié | La preuve vers l'avenir (Stage 3, futur P3) est contestable | Jeton d'horodatage RFC 3161 (ou OpenTimestamps) sur l'empreinte de chaque relevé et de chaque lot d'ordres, stocké dans le registre | S |
| C09 | M | C, E | PT1 s'arrête entièrement dès qu'une barre manque pour une position détenue (radiation, rachat, trou de Yahoo) : plus de stops ni de valorisation, et aucune alerte | `src/paper.py:352-355` ; `src/freshness.py` ne surveille pas la dernière séance traitée par PT1 | vérifié | PT1 peut rester figé sans que personne ne le sache | Alerte si la dernière séance de PT1 a plus d'une séance de retard sur SPY ; règle écrite pour les sorties de cote (déviation datée) | S |
| C10 | M | F, C | Dépendances non figées (`>=`), sans fichier de verrouillage ; pandas 2 ou 3, versions de yfinance changeantes | `requirements.txt:2-11` ; versions installées le 17/10 : pandas 3.0.6, yfinance 1.7.0 | vérifié | Résultats non reproductibles ; changements de comportement silencieux sur le PC | Fichier de verrouillage avec empreintes (`pip-compile --generate-hashes`) ; versions écrites dans `last_run.json` et dans chaque relevé | S |
| C11 | M | H, G | Puissance de P3 : 2 à 16 ans pour t ≥ 1,96 et 3 à 30 ans pour t ≥ 3, pour une corrélation de 0,02–0,03. Or R12 impose « changement de modèle = nouvelle hypothèse » : IA-1 ne pourra très probablement pas aboutir avec un modèle d'API figé | Calcul refait (§ C11) ; R5 et R12 de la v2 | vérifié (calcul ; dispersion supposée) | Des portes impossibles à franchir dans un délai utile | Écrire la durée attendue dans chaque fiche ; modèle à poids ouverts figé par empreinte, ou succession de modèles pré-enregistrée (§ 3, R12) | S |
| C12 | M | H | Le contrôle obligatoire des facteurs Fama-French (R2) est infaisable tel qu'écrit : pas de données comptables à date avant 2009 sans Compustat, et l'univers R1 exclut les petites valeurs | R2 v1 l. 65–67 ; R4 v1 l. 113–115 | probable | Bloque tout test sur le passé, ou pousse à contourner la règle | Contrôle par facteur et par période (§ 3, R2) | XS |
| C13 | M | H | R4 et R11 : pour une hypothèse publiée, la « validation 2006–2016 » est souvent dans l'échantillon de l'article original : ce n'est pas une preuve indépendante | R4 ; McLean et Pontiff (2016) | probable | Fausse impression de validation hors échantillon | Valider sur la période postérieure aux données de l'article (§ 3, R4) | XS |
| C14 | M | A, H | R2 classe yfinance au rang D (« jamais seule source d'un résultat »). Pourtant PT1, le Stage 3, la composante technique et le calendrier des séances en dépendent seuls, et le code le classe « SECONDARY » | `src/source_registry.py:74` ; `src/paper.py`, `src/prospective.py` | vérifié | Contradiction R2 / R10 non écrite | Exemption explicite dans R10 et étiquette « source unique non officielle » (§ 3) | XS |
| C15 | M | H | v2 : la condition 1 de R9 (« P1 à P4 franchies ») exclut par construction les hypothèses R12, qui ne passent ni P1 ni P2 | v2 R5 l. 139–141, R9 l. 197 | vérifié | IA-1 ne peut jamais mener à de l'argent réel | Corriger R9 (§ 3) | XS |
| C16 | M | B | Heures d'acceptation SEC : les libellés du flux ont changé de convention en octobre 2026. Le code déduit la convention de 3 dépôts par flux ; si un flux mélange deux conventions, un dépôt peut être daté 4 à 10 h trop tôt | `src/sec_parser.py:39-47, 288-316` ; échantillon du 17/10 : HON 9/9 et AAPL 9/9 en `utc_plus_ny_offset` | vérifié (échantillon) ; risque probable faible | Sans effet sur le signal hebdomadaire ; critique pour le Stage 4 et IA-1 (fenêtres de quelques heures) | Lire la page d'index de **chaque** dépôt utilisé dans une étude d'événement, ou retenir l'instant le plus tardif plausible | S |
| C17 | M | D | Stages 1–2 : Newey-West (Bartlett, retard ⌈H/5⌉−1) avec loi normale, donc erreurs standard sous-estimées. À H = 252, 407 dates qui se chevauchent ne représentent qu'environ 8 périodes indépendantes | `src/research/stats.py:57-84` ; `power_v4.py` (environ 8 % de faux positifs au retard 1, trouvé par l'agent) | vérifié (code) ; ampleur probable | La « piste » des accruals du Stage 1 (t = 2,87) n'était pas fiable ; leçon de méthode pour P1 et P2 | Échantillonnage sans recouvrement, ou Hansen-Hodrick / Newey-West à retard ≥ 2 × recouvrement, avec loi t | S |
| C18 | m | C | Suite de tests : **627 réussis, 1 échoué, 1 ignoré** (629 annoncés le 15/10). `test_p80_freshness::test_statuses` est daté : il échoue après le 15/10/2026 22:00 UTC | Sortie de pytest ; `tests/test_p80_freshness.py:33-43` ; `src/database.py:348,362` | vérifié | Bloque la règle R8 « suite complète avant chaque commit » ; le passage sur le PC (1.0b.2) échouera | Rendre le test indépendant de l'horloge (instant de récupération figé) | XS |
| C19 | m | C | Les dividendes de yfinance sont ajustés des splits postérieurs, alors que PT1 les multiplie par des actions réellement détenues | HON : 1,248034 × 0,9535 = 1,1900 ; 1,116972 × 1,061 × 0,9535 = 1,1300 ; `src/paper.py:92-93, 377-382` | vérifié (arithmétique) ; latent | Montant faux si PT1 traite un dividende en retard après un split | Convertir les dividendes comme les prix (`as_traded`) | XS |
| C20 | m | C | yfinance code les scissions comme des « splits » ; à une scission future, PT1 multiplierait le nombre d'actions (approximation de valeur non documentée) | Ratios HON 1,061 et 0,9535 ; `src/paper.py:369-376` | vérifié | Écart avec un vrai compte (ligne séparée pour la société scindée) | Documenter dans `PAPER_STRATEGY_PT1.md` ; journaliser l'événement comme scission | XS |
| C21 | m | B | Code de recherche : une trésorerie manquante compte pour 0 dans la valeur d'entreprise, et les lignes Form 4 sans prix comptent pour 0. Les errata sont publiés, mais le code n'a pas changé | `src/research/panel.py:179` ; `src/research/insider_history.py:131` | vérifié | Contaminerait les futurs tests s'il est réutilisé (phase 3) | Remplacer par `None` avant toute réutilisation | XS |
| C22 | m | F | Tâche Windows : limite de 4 h pour toute la tâche, contre 3 h par étape et 8 étapes ; pas de réveil du PC ; le lundi, l'enregistrement du relevé ne démarre qu'après `collect` et `analyze` et peut manquer 13:30 UTC | `scripts/install_windows_task.ps1:30` ; `scripts/daily_run.py:46, 50-63` | vérifié | Semaine perdue ; sauvegarde coupée | Lancer `prospective` puis `paper` en premier le week-end et le lundi ; limite cohérente ; option de réveil (`-WakeToRun`) | XS |
| C23 | m | F | Alertes passives (code de sortie, tableau de bord) : aucune notification active | `scripts/daily_run.py`, `src/freshness.py` | vérifié | Une panne peut durer des jours | Courriel ou notification en cas de code de sortie ≠ 0 ou d'absence d'envoi | S |
| C24 | m | F | Dépôt **public** ; l'adresse e-mail du propriétaire figure dans les métadonnées des commits | API GitHub `visibility: public` ; commit `b8d99db` | vérifié | Vie privée ; journaux et stratégie visibles | Passer en privé (R8, décision du propriétaire) | XS |
| C25 | m | C | Sur le PC, `code_version` vaudra toujours « -dirty », puisque les journaux sont modifiés avant le commit : l'information est inutile | `src/weekly/core.py:185-191` | probable | Traçabilité affaiblie | Ignorer `reports/paper` et `reports/prospective` dans le calcul de « dirty » ; enregistrer l'empreinte du code du signal | XS |
| C26 | m | C | Le recoupement « stop check: low » compare un plus bas Yahoo **non converti** en prix traités | `src/paper_report.py:188-190, 211` | vérifié | Fausses alertes après un split futur | Utiliser `Paper.frame()` | XS |
| C27 | m | E | Coûts de PT1 (8 pb par côté) : plausibles pour des grandes valeurs avec 100 000 USD, mais sans change, retenue à la source, impôts, ni minimum IBKR (1 USD, à vérifier) qui pèse sur les petits capitaux ; l'ouverture Yahoo n'est pas le prix de l'enchère | `scheduler_config.json` (risk) ; audit du 14/10 (39 % d'ouvertures identiques) | probable | Résultat net surestimé pour un compte réel | Module R7 (phase 1.5) ; recalcul en parallèle en lecture seule | M |
| C28 | m | D | Les chiffres intermédiaires de PT1 et du Stage 3 sont montrés chaque semaine au propriétaire (pas d'aveugle) | `src/weekly/sections/track_record.py:8-10` | vérifié | Tentation d'intervenir en cours de test | N'afficher que la mécanique (nombre de relevés, validité, écarts de prix) jusqu'au terme | S |
| C29 | m | C | `exchange_calendars` absent des dépendances : le test du calendrier NYSE est toujours ignoré | Sortie de pytest (1 ignoré) | vérifié | La règle de calendrier du Stage 4 n'est pas testée sur le vrai calendrier | Ajouter à `requirements-dev.txt` | XS |
| C30 | m | F | Depuis le cloud, Ken French, Open Source Asset Pricing et IBKR sont injoignables | `curl` → code 000 pour les trois | vérifié | Phase 1.3 impossible dans le cloud | Ajouter les domaines à la liste autorisée, ou télécharger depuis le PC | XS |
| C31 | m | A, H | L'en-tête de la v1 validée dit encore « proposition à valider » ; le complément de consigne ajoute au registre des champs R11 absents du texte des règles | v1 l. 1–5 ; complément § 1.6 | vérifié | Statut ambigu du texte qui fait foi | Fichier séparé de validations (empreinte, date, signature) ; règles autonomes | XS |
| C32 | m | G | Le signal heuristique n'a ni raison économique ni publication. La note « taille du chiffre d'affaires » est constante (80) pour toutes les grandes valeurs. La moyenne est recalculée sur les seules composantes disponibles | `src/scoring_fundamentals.py:45-54` ; `src/scoring_signal_fixed.py:174-181` | vérifié | Faible a priori ; ne remplit pas R3 (raison économique) | L'inscrire au registre comme hypothèse de l'agent sans justification économique ; ne pas lui consacrer d'effort au-delà du témoin | — |
| C33 | m | A, G | La proposition Stage 4 v4 porte sur 2016–2025, contrairement à R4, et sur la dérive après annonce de résultats, que la littérature récente juge absente pour les grandes valeurs depuis 2006 (Martineau 2022, contesté) | `STAGE4_PREREGISTRATION_PROPOSAL_v4.md:25, 307` | vérifié (texte) ; littérature contestée | Effort à faible espérance | Ne la reformuler qu'en relevé vers l'avenir, et après L1 | — |

### Conformités vérifiées (aucun écart)

- **Aucun chemin vers un courtier** : aucune trace de `ib_insync`, `ibapi` ni `placeOrder` dans `src/`, `scripts/` et
  `main.py` (recherche textuelle).
- **Journaux PT1 et registre du Stage 3** : chaînes valides (20 entrées de transactions et 40 prédictions ; 1 entrée de
  registre vérifiée). Le relevé du 09/10 a été généré le 12/10 à 06:45:13 UTC, avant l'échéance de 13:30 UTC. Les ordres
  ont été créés à 07:59:54 UTC et exécutés à l'ouverture du 12/10. L'empreinte du relevé utilisé par le rééquilibrage est
  égale à celle du registre (script `journal_mech.py`, sortie au § C-mécanique).
- **Code du signal, de PT1 et du Stage 3 inchangé depuis `d48ef69`** : `git diff --stat d48ef69 e627899` sur les fichiers
  du signal, de PT1, du Stage 3, de la configuration et des journaux ne renvoie rien. Après le premier relevé, 7 commits
  ont touché des modules lus par le signal (`insider_tracker`, `sec_parser`, `sec_xbrl`, `scoring_signal_fixed`). Les
  différences lues sont additives ou d'affichage ; l'absence d'effet sur les scores reste **probable** (§ 6).
- **Données comptables XBRL à date** : publication = heure d'acceptation vérifiée, ou sinon fin du jour de dépôt
  (prudent) (`src/sec_xbrl.py:149-156`). Les séances incomplètes sont écartées (`src/market_data.py:115-118`). Les
  versions ALFRED sont conservées (`src/macro_fred.py:14-17`).
- **Aucun secret dans l'historique git** : seules des valeurs de test fictives apparaissent (`git log --all -p`). Aucun
  fichier `.env` n'a jamais été commité.
- **Signal et score fondamental** : aucune valeur manquante remplacée par 50 ou par 0 dans le chemin du signal ; une
  composante absente est exclue.

---

### Détail et preuves des constats

#### C01 — Aucune preuve d'avantage ; aucune démonstration possible à court terme

- **Résultats sur le passé, consultables (ni PT1 ni Stage 3).**
  - `docs/research/STAGE1_RESULTS.md:9-12` : 205 tests, 0 significatif après correction.
  - `docs/research/STAGE2_RESULTS.md:9-13` : 0 confirmé sur 4, 225 tests.
  - `docs/research/HEURISTIC_EVALUATION.md:13-14` : AUC d'environ 0,50.
  - Tous portent l'étiquette « biais du survivant, 2017–2026 : ne valide rien » (R10).
- **Les deux tests ouverts ne peuvent pas conclure.**
  - Stage 3 : puissance de conception de 6 % (P1) et 19 % (P2) pour une corrélation de 0,03 (`src/uncertainty.py`,
    CHANGELOG 0.3d).
  - PT1 : bande de bruit de ±22,7 % sur 52 semaines.
- **Sur le passé, R1 et R4 exigent des données incluant les sociétés radiées** (Norgate, non acheté). Sans elles,
  aucune porte P1 ou P2 n'est franchissable légitimement.
- **Le seul chemin restant est P3, vers l'avenir**, dont les durées sont calculées en C11.

#### C02 — Fiscalité française et référence R0

- **Ce qui manque dans R0 et R7.**
  - R0 : la référence « ETF S&P 500 UCITS en euros après frais et impôts » ne précise ni l'enveloppe ni le moment de
    l'imposition. Des ETF S&P 500 synthétiques éligibles au PEA existent (à confirmer par le propriétaire auprès de son
    courtier). Après 5 ans de PEA, seuls les prélèvements sociaux sont dus, et seulement au retrait.
  - R7 l. 162 : « PFU 30 % ». Plusieurs sources secondaires concordantes indiquent que la loi de financement de la
    sécurité sociale pour 2026 porte les prélèvements sociaux de 17,2 % à 18,6 % sur les dividendes, intérêts et
    plus-values mobilières (PFU de 31,4 %), PEA compris pour les prélèvements sociaux. **À vérifier sur une source
    officielle.** Exemples : [actu-juridique.fr](https://www.actu-juridique.fr/fiscalite/fiscal-finances/la-csg-en-hausse-sur-les-revenus-du-capital/),
    [LCL Banque privée](https://www.lcl.fr/banque-privee/actualites/juridique-fiscalite/adoption-definitive-du-budget-de-la-securite-sociale),
    [auguste-patrimoine.fr](https://www.auguste-patrimoine.fr/blog/pea-et-hausse-de-la-csg-en-2026-impact-calcul-et-strategies-de-retrait).
  - R7 l. 161 retient la retenue américaine de 15 %, mais pas l'imposition française des dividendes. Selon la règle
    habituelle des conventions fiscales (à vérifier auprès d'un fiscaliste), le crédit d'impôt de 15 % ne s'impute que
    sur la part d'impôt sur le revenu (12,8 %) ; les prélèvements sociaux restent dus. La charge totale est d'environ
    15 % + 18,6 % ≈ 33,6 %.
  - Le report des moins-values sur 10 ans et l'option pour le barème progressif sont absents.
- **Calcul refait** (`scratchpad/scripts/tax_drag.py`, hypothèses écrites dans le script).
  - Hypothèses : marché à 7 %/an ; ETF capitalisant en PEA à 0,15 % de frais, imposé à la sortie sur le gain ;
    stratégie active sur compte-titres avec rendement du dividende de 1,3 %, coûts de 8 pb par côté, gains réalisés et
    imposés chaque année au PFU, liquidation au terme.
  - Surperformance brute nécessaire pour égaler l'ETF :

  | Rotation / part des gains réalisée chaque année | 10 ans, PFU 30 % | 20 ans, PFU 30 % | 10 ans, PFU 31,4 % | 20 ans, PFU 31,4 % |
  |---|---|---|---|---|
  | 0,3 / 30 % | 1,31 %/an | 1,54 %/an | 1,35 %/an | 1,60 %/an |
  | 1,0 / 100 % | 1,66 %/an | 1,96 %/an | 1,72 %/an | 2,05 %/an |
  | 4,0 / 100 % | 2,14 %/an | 2,44 %/an | 2,20 %/an | 2,53 %/an |

- **Conséquence.** Une stratégie en rééquilibrage mensuel doit battre le marché d'environ **1,5 à 2,5 points par an
  avant impôts**. C'est l'ordre de grandeur de la prime publiée, après division par deux, de la plupart des anomalies
  sur des grandes et moyennes valeurs, souvent moins (§ 5).

#### C03 — Sauvegardes

- `git ls-remote origin` ne liste que `main` et `claude/nifty-ramanujan-u1p317` : la branche `sauvegarde/journaux-pc`
  (`src/backup.py:25`) n'existe pas.
- `GET /repos/leonardcreuse-cloud/trading-agent-pro` → `pushed_at: 2026-10-15T07:05:33Z`.
- Dernier commit des journaux PT1 sur GitHub : `0398033` (« PT1: mark of 2026-10-13 »). Les valorisations du 14 au
  16/10 n'existent donc que sur le PC, si les passages ont eu lieu.
- Cause probable : le propriétaire n'a pas encore récupéré le code de la phase 0 (`git pull`) ; le CHANGELOG précise
  qu'un changement ne devient actif qu'après récupération. Non vérifiable depuis ici.
- `docs/LOCAL_RUN.md:46` : les seules sauvegardes de la base sont locales (`data\backups\`). La base SQLite et les
  fichiers bruts (environ 550 Mo) ne sont sauvegardés nulle part ailleurs. Or ce sont eux qui prouvent le « stockage au
  fil de l'eau » exigé par R2.

#### C04 — Références de PT1 sans dividendes

- **Mécanisme.** `src/paper.py:508-509` : `spy_open_start` est l'ouverture **ajustée** de la première séance, lue dans
  la version Yahoo du jour et stockée dans `bench_state`. Chaque passage relit ensuite la clôture ajustée **de la
  version courante** (`l. 516-518`). Yahoo réduit les prix antérieurs à chaque détachement de dividende
  (`src/market_data.py:9-11`). Le rapport « clôture du jour / base figée » est donc un rendement **de prix** : les
  dividendes postérieurs au départ sont perdus. Il en va de même pour l'univers à poids égal, rebasé à chaque séance
  d'exécution (`l. 511-515`).
- **Pendant ce temps, PT1 encaisse les dividendes** (`l. 377-382`).
- **Calcul synthétique** (`scratchpad/scripts/bench_dividend.py`, qui appelle la vraie méthode `_benchmarks`) : prix à
  100, dividende de 1, prix à 99 le jour du détachement. Le code affiche **−1,00 %**, alors que le rendement total est de
  **0,00 %**.
- **Correction** dans la couche de rapport, sans toucher aux journaux : recalculer les deux références à partir des
  clôtures non ajustées stockées et des dividendes (même traitement que le portefeuille). La consigner comme déviation
  datée, sur décision du propriétaire.

#### C05 — Taille réelle du test du Stage 3

- **Formule figée.** t = moyenne / écart-type × √(n·min(1, 5/H)) ; p = erfc(|t|/√2) (loi normale) ; confirmation si
  p < 0,025 et moyenne > 0 (`src/prospective.py:315-329`, `src/walk_forward.py:111-118`,
  `src/scoring_signal_fixed.py:38-40`).
- **Simulation** (`scratchpad/scripts/stage3_alpha_sim.py`, 200 000 tirages) : corrélations hebdomadaires sous
  l'hypothèse nulle ; à H = 20, chacune est la moyenne de 4 morceaux hebdomadaires consécutifs (recouvrement de
  4 fenêtres).

  ```
  H=20: P(confirmed, mean>0) = 0.0200 (nominal one-sided 0.0125); P(p<0.025 two-sided) = 0.0398 (nominal 0.025)
  H=5:  P(confirmed, mean>0) = 0.0146 (nominal one-sided 0.0125); P(p<0.025 two-sided) = 0.0292 (nominal 0.025)
  P(|t12|>2.241) = 0.0447
  ```

- **Lecture.** La taille réelle de P1 est d'environ 1,6 fois la taille annoncée. Une dépendance plus forte que le seul
  recouvrement (persistance des facteurs) l'aggraverait.

#### C06 — HON : explication inversée, conversion de PT1 correcte

- **Événements, vérifiés à la SEC.** 8-K de Honeywell, accession `0000773840-26-000084`, accepté le 29/06/2026 :
  - « Effective as of 12:01 a.m. … June 29, 2026, the Company completed the Spin-Off … one share of Aerospace Common
    Stock for every two shares » ;
  - « At 12:02 a.m. … June 29, 2026 … reverse stock split … every two shares … combined into one share ».
- **Ratio clôture Cboe / clôture Yahoo « brute »** (`scratchpad/scripts/hon_check.py`, téléchargements du 17/10) :
  - 2,0233 jusqu'au 29/10/2025 ;
  - 1,907 du 30/10/2025 au 26/06/2026 ;
  - 1,000 depuis juillet 2026.
- **Ratios de split dans yfinance** : 1,061 le 30/10/2025 (scission de Solstice) et 0,9535 le 29/06/2026
  (= 0,5 × 1,907 : regroupement et scission combinés).
- **Interprétation cohérente.**
  - Cboe = prix traité × 2 avant le 29/06/2026 : historique ajusté du regroupement. Le code le dit lui-même :
    « split-adjusted as served », `src/external_sources.py:411`.
  - Yahoo brut = prix traité ÷ (produit des ratios postérieurs). `as_traded()` (`src/paper.py:56-67`) retrouve donc le
    prix traité.
  - Contrôle : 2 × 1,061 × 0,9535 = 2,0233, égal au ratio observé.
- **Pour PT1, démarré le 12/10/2026 :** sur toute sa période, `as_traded` = Cboe = Yahoo (ratio 1,000). Le calcul de
  l'ATR et du volume moyen à s0 ne porte que sur des séances postérieures à juillet 2026. **Aucun écart sur PT1.**
- **Ce qui est faux.**
  - `docs/CHANGELOG.md:17-18` : « Yahoo's raw HON prices are split-adjusted and Cboe's are as traded ».
  - `scripts/reproduce_audit_figures.py:16,38` (`SPLIT_ADJUSTED_ONLY_IN_YAHOO`).
  - Le complément de consigne, point 1.0b.1 (« ceux de Cboe sont les prix réellement traités »).
- **Probable seulement : le niveau absolu du prix traité.** Les dividendes versés en sont un indice concordant :
  1,248034 × 0,9535 = 1,19 USD ; 1,116972 × 1,061 × 0,9535 = 1,13 USD. Il reste à le confirmer par une troisième source
  non ajustée (barres TRADES d'IBKR).

#### C07 — Compteur de tests

- **Comptage récursif des champs `t_stat`** (hors échantillons) :
  - `reports/walk_forward.json` : 388 ;
  - `reports/research_stage1.json` : 220 ;
  - `reports/research_stage2.json` : 244 ;
  - total : **852**.
- **Ce chiffre est une borne basse.**
  - Plusieurs versions antérieures du walk-forward (4 titres, 40 titres, modèle ridge ajusté ; commits `f9c3343`,
    `e4185f7`, `134da2a`) ont été remplacées.
  - `reports/history/` est ignoré par git.
  - L'évaluation heuristique et les simulations de puissance ne sont pas comptées.
- **L'audit du 14/10 (l. 14) annonce « 430 tests »,** soit Stage 1 + Stage 2 seulement.

#### C08 — Horodatage

- `generated_at = utc_now_iso()` (`src/prospective.py:263`) : c'est l'horloge du PC.
- Les commits de sauvegarde portent la date locale du PC.
- La préinscription du Stage 3 le reconnaît (`STAGE3_PREREGISTRATION.md:97-99`), mais présente le commit comme un
  horodatage externe. Il ne l'est pas : seule l'heure d'envoi enregistrée par GitHub l'est, et elle n'est ni conservée
  ni durable.

#### C09 — Blocage de PT1

- `src/paper.py:352-355` : si une position détenue n'a pas de barre pour la séance, la fonction renvoie `None` et
  `update()` s'arrête (`l. 293-294`).
- Aucune règle ne traite les sorties de cote (R1).
- `freshness` ne regarde que SPY.

#### C10 — Dépendances

- `requirements.txt` : uniquement des contraintes `>=` (yfinance ≥ 0.2.40, pandas ≥ 2.1, etc.).
- Le jour de l'audit, cela installe pandas 3.0.6, une version majeure dont le comportement de copie a changé.
- Aucune trace de versions dans les relevés ni dans `last_run.json`.

#### C11 — Puissance de P3 et de R12

- **Formule.** n = ((z + 0,84) × σ / IC)², où σ est la dispersion des corrélations de rang mensuelles. σ ≈ 0,05–0,10
  est une **hypothèse** : à mesurer sur la période de découverte, sans regarder la moyenne.

  | IC visé | σ = 0,05 | σ = 0,08 | σ = 0,10 |
  |---|---|---|---|
  | 0,02 | 49 mois (t ≥ 1,96) / 92 mois (t ≥ 3) | 126 / 236 | 196 / 369 |
  | 0,03 | 22 / 41 | 56 / 105 | 87 / 164 |
  | 0,04 | 12 / 23 | 31 / 59 | 49 / 92 |

- **Conséquence pour P3.** Avec l'effet visé de R11.1 (moitié de l'effet publié, souvent 0,02–0,03), P3 dure de 2 à
  16 ans. La correction de Holm entre hypothèses parallèles l'allonge encore.
- **Conséquence pour R12.** Avec t ≥ 3, il faut de 3 à 30 ans. Un modèle d'API reste disponible 1 à 2 ans
  (**à vérifier** sur les calendriers de retrait publiés). La règle « changement de modèle = nouvelle hypothèse » rend
  donc IA-1 presque impossible à conclure, sauf effet fort et stable.

#### C16 — Conventions d'horodatage de la SEC

- **Échantillon du 17/10** (`scratchpad/scripts/sec_conv.py`, qui utilise les fonctions `label_convention` et
  `index_accepted` du dépôt) : 9 dépôts répartis sur tout le flux « recent » de HON (2020–2026) et 9 d'AAPL
  (2015–2026). Les 18 sont en `utc_plus_ny_offset` (libellé = vrai UTC + 4 ou 5 h).
  - Exemple : 8-K de HON du 23/07/2026, libellé `14:01:36Z` ; page d'index « Accepted 2026-07-23 06:01:36 », heure de
    New York.
- Le 11/10, le module notait des flux en `utc` (MP, RKLB) (`src/sec_parser.py:41-44`). La convention d'un flux change
  donc dans le temps.
- La calibration sur 3 dépôts est prudente, mais elle ne garantit rien pour les dépôts non échantillonnés pendant une
  transition.

#### C18 — Test daté

- `pytest -q -rs` : `1 failed, 627 passed, 1 skipped in 26.88s`. L'échec est
  `tests/test_p80_freshness.py:43` (`'STALE' == 'OK'`).
- **Cause.**
  - `record_fetch` renvoie `retrieved_at = utc_now_iso()` (`src/database.py:348,362`) ; le test date l'enregistrement
    par une requête SQL, mais l'observation garde l'heure réelle d'insertion.
  - La requête de fraîcheur filtre `retrieved_at <= now` (`src/freshness.py:84-86`). Avec `now` = 15/10 22:00 UTC, le
    test ne passe que s'il est lancé avant cet instant.
- **Ignoré** : `tests/test_p78_stage4_timing_rule.py:62`, faute de `exchange_calendars`.

#### C-mécanique — Sortie du script de contrôle des journaux (aucun chiffre de performance)

Sortie de `scratchpad/scripts/journal_mech.py`. Les lignes « fills/rejections » résument 8 lignes identiques en
structure ; les autres lignes sont recopiées telles quelles.

```
transactions verify: {'n': 20, 'ok': True, 'problem': None}
predictions verify: {'n': 40, 'ok': True, 'problem': None}
entry types: {'start': 1, 'rebalance': 1, 'order': 8, 'fill': 3, 'order_rejected': 5, 'mark': 2}
fills/rejections: 8 orders created 2026-10-12T07:59:54+00:00, session 2026-10-12, open_after_order=True (8/8);
                  5 rejections 'sector unknown already at 40.0% of equity' (bug documented 12/10)
mark sessions: ['2026-10-12', '2026-10-13']
ledger: {'n_entries': 1, 'chain_ok': True, 'verified': ['2026-10-09'], 'problems': []}
record 2026-10-09 generated_at 2026-10-12T06:45:13+00:00, deadline 2026-10-12T13:30:00+00:00, in_window True,
       code_version 318ef56…-dirty
rebalance s0 2026-10-09 sha_matches_ledger True
```

---

## 3. Propositions de changement des règles (version 3, à ne pas appliquer)

Chaque proposition remplace ou complète le texte indiqué. Les numéros renvoient à la v2 proposée.

**R0 — Référence à battre.** Remplacer le 3e point par :
> « Référence à battre : un ETF S&P 500 capitalisant, éligible au PEA si le propriétaire dispose d'un PEA avec de la
> place, sinon un ETF UCITS capitalisant sur compte-titres. Il est valorisé en euros, avec ses frais réels, et imposé
> **au moment où il le serait réellement** : à la sortie seulement, aux taux en vigueur à la date du calcul. L'ETF exact
> (code ISIN) et l'enveloppe sont inscrits dans `docs/REFERENCE_R0.md` avant le premier relevé P4. »

Remplacer aussi « garantissent que tout résultat annoncé est vrai » par :
> « imposent des contrôles destinés à ce que tout résultat annoncé soit exempt d'anticipation, de biais du survivant
> et de coûts omis ; les risques résiduels connus sont listés à côté de chaque résultat. »

*Justification : C02 ; une promesse invérifiable ne peut pas être auditée.*

**R1 — Définition de « société américaine ».** Remplacer :
> « Titres admis : actions ordinaires d'émetteurs qui déposent des formulaires 10-K et 10-Q à la SEC (pas de 20-F ni de
> 40-F), cotées sur XNYS, XNAS ou XASE à la date T, d'après le code SIC et le type de formulaire de la SEC. »

Ajouter :
> « Sans données incluant les titres radiés (Norgate ou équivalent), R1 ne s'applique qu'aux relevés vers l'avenir.
> Aucun test sur le passé n'est alors autorisé. »

*Justification : ambiguïté des sociétés domiciliées à l'étranger qui déposent des 10-K ; C01, C12.*

**R2 — Sources.**
- Ajouter au rang D :
  > « Les tests déjà en cours (R10) qui reposent sur yfinance seul en sont exemptés. Leurs résultats portent la
  > mention « source unique non officielle ». »
- Remplacer le recoupement par :
  > « Chaque prix est comparé à une seconde source **sur la même base d'ajustement** : prix traités avec prix traités,
  > ou ajustés avec ajustés. Les opérations sur titres de la période (splits, regroupements, scissions) sont
  > rapprochées des dépôts SEC avant de déclarer un écart. »
- Remplacer le contrôle Fama-French par :
  > « Facteurs de prix (marché, momentum) : à recalculer sur toute la période testée, corrélation mensuelle ≥ 0,95.
  > Facteurs comptables (taille, valeur) : seulement là où des données comptables à date existent, au moins 0,80 sur
  > l'univers commun. Si un facteur n'est pas calculable, l'écrire, sans bloquer les hypothèses qui ne l'utilisent pas. »

*Justification : C06, C12, C14.*

**R3 — Registre.**
- Ajouter une définition :
  > « Un test est une décision statistique (hypothèse, horizon, univers, période, statistique) qui pourrait faire
  > franchir ou échouer une porte. Les statistiques descriptives sont comptées à part, dans un second compteur. »
- Ajouter :
  > « Le compteur part de la borne basse reconstituée par l'audit du 17/10/2026 (≥ 852 statistiques t déjà produites),
  > corrigée après inventaire. »
- Ajouter :
  > « Chaque entrée du registre et chaque relevé reçoit un jeton d'horodatage externe (RFC 3161 ou OpenTimestamps),
  > stocké avec l'entrée. »
- Définir le lot :
  > « Le lot de la correction de Holm est l'ensemble des P2 lancées au cours d'un même trimestre civil. Aucune P2 n'est
  > lancée seule pour échapper au lot. »

*Justification : C07, C08.*

**R4 — Périodes.** Ajouter :
> « Pour une hypothèse publiée, la validation P2 se fait sur la période **postérieure à la dernière donnée de l'article
> original**. Si cette période est entièrement après 2016, P2 est remplacée par P3. Le chevauchement avec l'échantillon
> de l'article est écrit dans la fiche. »

*Justification : C13 ; McLean et Pontiff (2016).*

**R5 — Portes.**
- Ajouter :
  > « Chaque fiche donne, avant tout calcul, la puissance de P1, P2 et P3 et la durée attendue de P3. Une porte dont
  > la puissance est inférieure à 50 % n'est pas lancée. On passe alors directement à P3, avec sa durée écrite. »
- Remplacer le critère P4 par :
  > « P4 est une porte de mise en œuvre : écart moyen entre la simulation P4 et le relevé P3 d'au plus 50 pb par an
  > après coûts, et aucun défaut bloquant à la revue. Battre la référence de R0 est mesuré avec un intervalle de
  > confiance à 90 %, qui doit exclure une sous-performance de plus d'un point par an. »
- Ajouter :
  > « Les tests utilisent une loi t ou des valeurs critiques calibrées par simulation sur la structure de recouvrement
  > réelle, jamais la loi normale quand le nombre effectif d'observations est inférieur à 60. »

*Justification : C05, C11, C17 ; un critère ponctuel n'a pas de sens face à ±11 %/an de bruit.*

**R6 — Construction.** Préciser :
> « Achat : les titres les mieux classés jusqu'à 20 à 30 positions, parmi les 10 % meilleurs. Vente : un titre est
> vendu seulement s'il sort des 30 % meilleurs. »

Préciser aussi « grand groupe » : « grand groupe SIC (2 chiffres) ». Ajouter :
> « La rémunération des liquidités suit la règle d'intérêts publiée par IBKR pour la taille du compte (seuil et marge),
> à défaut le taux DTB3 diminué de 0,5 point. »

*Justification : ambiguïtés de R6 ; à vérifier sur la grille IBKR.*

**R7 — Coûts et impôts.** Remplacer les lignes Dividendes et Impôt par :
> « Dividendes : retenue américaine de 15 % (W-8BEN), puis imposition française au taux du PFU en vigueur. Le crédit
> d'impôt conventionnel s'impute sur la part d'impôt sur le revenu ; les prélèvements sociaux restent dus.
> Plus-values : PFU au taux en vigueur l'année de la cession (texte et date de la source officielle cités dans le
> module de coûts). Les moins-values s'imputent sur les plus-values de la même année et des 10 années suivantes.
> L'option pour le barème progressif est calculée à côté. Change : frais IBKR de conversion publiés, avec leur
> minimum. »

Ajouter :
> « Tout résultat P4 est donné à côté de la même stratégie sans impôts, pour isoler l'effet fiscal. »

*Justification : C02.*

**R8 — Fonctionnement.**
- Remplacer la sauvegarde par :
  > « Après chaque passage : journaux sur GitHub, avec contrôle que l'envoi a réussi. Chaque jour : copie chiffrée de
  > la base et des fichiers bruts hors du PC. Alerte active (courriel ou notification) si l'un des deux manque depuis
  > plus de 24 h. »
- Ajouter :
  > « Environnement figé : fichier de verrouillage des dépendances avec empreintes ; versions enregistrées dans chaque
  > relevé et chaque résultat. »
- Ajouter :
  > « La suite de tests complète s'applique aux commits de code ; les commits automatiques de journaux en sont
  > dispensés. Un test qui dépend de l'horloge réelle est un défaut. »
- Ajouter :
  > « Aveugle : jusqu'au terme d'un test vers l'avenir, les rapports n'affichent que sa mécanique (nombre de relevés,
  > validité, écarts entre sources), pas son résultat intermédiaire. »

*Justification : C03, C10, C18, C28.*

**R9 — Argent réel.** Remplacer la condition 1 par :
> « au moins une hypothèse a franchi toutes les portes qui s'appliquent à son parcours (P1 à P4, ou pour R12 : P3
> renforcée et P4) ».

Ajouter :
> « montant initial plafonné par le propriétaire avant le premier ordre ; arrêt automatique de tout nouvel ordre si la
> perte relative à la référence dépasse le seuil écrit. »

*Justification : C15.*

**R10 — Tests en cours.** Ajouter :
> « Le résultat du Stage 3 est publié avec la taille réelle de son test, estimée par simulation (environ 4 % pour P1
> au lieu de 2,5 %). Les références de PT1 sont présentées en rendement total, recalculé en lecture seule. »

*Justification : C04, C05.*

**R11 — Apprentissage.**
- Remplacer R11.1 par :
  > « l'effet attendu est la moitié de l'effet publié **sur un univers comparable à R1** (grandes et moyennes valeurs,
  > pondération par la capitalisation si l'article la donne). À défaut, le quart de l'effet publié toutes tailles
  > confondues. »
- Préciser R11.3 :
  > « poids observé = poids de départ × max(0, IC moyen observé) / IC attendu, calculé sur des mois sans
  > recouvrement ».
- Ajouter à R11.5 :
  > « Le classement « erreur de processus » est validé par le propriétaire. Une correction ne réécrit jamais une entrée
  > de journal : elle ajoute une entrée datée. »

*Justification : Hou, Xue et Zhang (2020) ; risque de conflit d'intérêts dans l'auto-classement.*

**R12 — Analyste IA.**
- Ajouter :
  > « Le modèle est soit un modèle à poids ouverts exécuté localement et identifié par l'empreinte de ses poids, soit
  > un modèle d'API pour lequel une **succession pré-enregistrée** est écrite d'avance (modèle de remplacement, période
  > de recouvrement d'au moins 3 mois où les deux notent les mêmes documents, critère de concordance). Le relevé n'est
  > alors pas clos. »
- Remplacer « température 0 » par :
  > « réglages déterministes les plus stricts que le modèle accepte, figés et écrits ; ceux que le modèle n'accepte pas
  > sont notés « non réglable » ».
- Ajouter :
  > « La fiche donne la durée attendue de P3 renforcée ; si elle dépasse 5 ans pour l'effet visé, l'hypothèse n'est pas
  > lancée sans accord écrit du propriétaire. »

*Justification : C11.*

**En-tête.** Ajouter un fichier `docs/VALIDATIONS.md`, en ajout seulement, qui liste pour chaque version validée son
SHA-256, la date et la mention du propriétaire. Le texte des règles reste ainsi identique à celui qui a été validé.
*Justification : C31.*

---

## 4. Propositions pour la consigne et l'ordre des phases

1. **Réécrire le point 1.0b.1 (HON)** :
   > « Vérifier que les prix utilisés par PT1 pour HON correspondent aux prix réellement traités sur la période de PT1
   > (depuis le 12/10/2026), par comparaison avec une source non ajustée (barres TRADES d'IBKR quand elle sera
   > disponible), et documenter les événements du 30/10/2025 et du 29/06/2026 (dépôts SEC). Cboe est ajusté du
   > regroupement du 29/06/2026 et ne peut pas servir de référence de prix traités avant cette date. »

   Ajouter un erratum daté pour `docs/CHANGELOG.md:17-18` et `scripts/reproduce_audit_figures.py:16`.
2. **Ajouter une phase 0.6 « correctifs mécaniques »** (avant la phase 1, chacun daté dans le CHANGELOG et consigné
   comme déviation d'implémentation sur décision du propriétaire, aucun journal réécrit) :
   - références de PT1 en rendement total, en lecture seule (C04) ;
   - alerte de blocage de PT1 (C09) ;
   - test daté (C18) ;
   - conversion des dividendes (C19) ;
   - ordre des étapes du week-end et limite de la tâche Windows (C22) ;
   - fichier de verrouillage (C10).
3. **Prouver la sauvegarde avant la phase 1.** Critère : la branche `sauvegarde/journaux-pc` existe sur GitHub et
   contient les valorisations PT1 depuis le 14/10 ; une copie chiffrée de `data/` existe hors du PC (C03).
4. **Avancer ce qui fait courir le temps.** Le facteur limitant est la durée des relevés vers l'avenir (C11).
   Ordre proposé :
   - 1.1 (instantanés de l'univers) ;
   - 1.6 (registre) ;
   - 1.7 (lot L1, relevés vers l'avenir) ;
   - puis seulement 1.2 à 1.5.
   - Le choix de L1 est **mécanique** pour neutraliser ce que l'agent sait déjà des performances récentes : toutes les
     hypothèses d'Open Source Asset Pricing de catégorie « clear » dans l'article original, reproduites avec t ≥ 3,
     calculables avec les données SEC et de prix, à rythme mensuel. On les retient toutes, ou on en tire un
     sous-ensemble au hasard avec une graine publiée, au lieu de « 5 à 8 choisies ».
5. **Décider de Norgate plus tôt** (phase 2), car sans données incluant les titres radiés, aucune porte P1 ou P2 n'est
   possible (C01). Avant l'essai, vérifier dans le contrat de licence la conservation des données après résiliation
   (lien avec R8 v2).
6. **IA-1 (1.7b).**
   - Ne pré-enregistrer qu'après avoir écrit la durée attendue (C11) et une solution au retrait du modèle (§ 3, R12).
   - Le relevé lui-même est peu coûteux à démarrer tôt si le propriétaire l'accepte.
   - Préciser l'agrégation mensuelle des événements, concentrés en janvier, avril, juillet et octobre.
   - Mesurer l'heure de publication du communiqué (fil de presse), pas seulement l'heure d'acceptation SEC.
   - Lire la page d'index de chaque dépôt (C16).
7. **Stage 4.** Le mettre en attente. Le reformuler uniquement en relevé vers l'avenir, après L1, compte tenu de R4 et
   de Martineau (2022) (C33).
8. **1.0b.2 (tests sur le PC).** Prévenir que la suite actuelle échouera sur `test_p80_freshness` tant que C18 n'est pas
   corrigé.
9. **Environnement cloud.** Ajouter à la liste autorisée `mba.tuck.dartmouth.edu`, `www.openassetpricing.com` (et
   l'hébergement de ses fichiers, à vérifier) et `www.interactivebrokers.com` (C30).

---

## 5. Hypothèses proposées pour le registre (domaine G)

Il s'agit de propositions d'inscription, **pas de résultats**. Contexte commun : achat seulement, rythme mensuel, univers
R1 (grandes et moyennes valeurs américaines), compte-titres français. Effet visé selon R11.1 : moitié de l'effet publié
sur un univers comparable. Hou, Xue et Zhang (2020) montrent que beaucoup d'anomalies disparaissent hors des petites
capitalisations ; l'effet visé est donc souvent **inférieur** au seuil de rentabilité fiscale de C02. **Priorité aux
signaux à faible rotation.**

| ID proposé | Hypothèse (sens) | Mesure (données, date de disponibilité) | Raison économique | Testabilité avec les données actuelles | Références |
|---|---|---|---|---|---|
| L1-GP | Rentabilité brute élevée → rendement supérieur (+) | (Chiffre d'affaires − coût des ventes) / actif total, XBRL du dernier 10-K ou 10-Q, publié à l'heure d'acceptation | Prime de qualité ; marché lent à valoriser la rentabilité | XBRL depuis 2009–2011 : surtout P3 ; rotation faible | Novy-Marx (2013), *Journal of Financial Economics* 108(1) ; reproduite par Chen et Zimmermann (2022) |
| L1-NSI | Émission nette d'actions élevée → rendement inférieur (−) ; achat du quintile de rachat | Variation sur 12 mois du nombre d'actions ajusté des splits (couverture SEC `dei`, ou Norgate) | Les dirigeants émettent quand l'action est chère et rachètent quand elle est bon marché | XBRL ou Norgate ; rotation faible | Pontiff et Woodgate (2008), *Journal of Finance* ; Daniel et Titman (2006), *Journal of Finance* |
| L1-AG | Croissance de l'actif élevée → rendement inférieur (−) | Croissance annuelle de l'actif total, XBRL | Surinvestissement ; prime d'investissement (facteur CMA) | XBRL : P3 surtout | Cooper, Gulen et Schill (2008), *Journal of Finance* ; Fama et French (2015), *Journal of Financial Economics* |
| L1-MOM | Rendement de t−12 à t−1 élevé → rendement supérieur (+) | Prix seuls ; dernier mois exclu | Sous-réaction et diffusion lente de l'information | Prix seuls, donc P1 et P2 possibles avec Norgate ; **rotation élevée, fort coût fiscal** ; risque de krach | Jegadeesh et Titman (1993), *Journal of Finance* ; Asness, Moskowitz et Pedersen (2013), *Journal of Finance* ; Daniel et Moskowitz (2016), *Journal of Financial Economics* ; coûts : Novy-Marx et Velikov (2016), *Review of Financial Studies* |
| L1-LV | Faible volatilité ou faible bêta → rendement ajusté du risque supérieur (+) | Volatilité sur 12 mois de rendements quotidiens, prix seuls | Contrainte de levier des investisseurs (« betting against beta ») | Prix seuls ; **attention** : peut gagner en ratio de Sharpe mais perdre face à la référence R0, qui est un rendement brut | Frazzini et Pedersen (2014), *Journal of Financial Economics* ; Ang, Hodrick, Xing et Zhang (2006), *Journal of Finance* |
| L1-QMJ | Qualité composite (rentabilité, croissance, sécurité) → rendement supérieur (+) | Moyenne des rangs de composantes XBRL, définition de l'article | Prime de qualité | XBRL : P3 ; à inscrire **après** ses composantes, car c'est une combinaison | Asness, Frazzini et Pedersen (2019), *Review of Accounting Studies* |
| L1-INS | Achats d'initiés « opportunistes » → rendement supérieur (+) | Formulaires 4, code P, initiés sans schéma calendaire récurrent sur 3 ans ; heure d'acceptation | Information privée des dirigeants | Formulaires 4 depuis 2003 : P1 et P2 possibles sur l'univers R1, mais l'effet est concentré sur les petites valeurs, donc faible a priori sur R1 | Cohen, Malloy et Pomorski (2012), *Journal of Finance* ; Lakonishok et Lee (2001), *Review of Financial Studies* |
| L1-SEAS | Saisonnalité : rendement du même mois civil les années précédentes → rendement du mois (+) | Prix seuls, moyenne des mois de même rang sur 2 à 20 ans | Persistance de flux ou de risques saisonniers | Prix seuls ; rotation élevée ; **reproduction à vérifier** dans Open Source Asset Pricing | Heston et Sadka (2008), *Journal of Financial Economics* |
| IA-1 | Note d'un modèle de langage sur le communiqué de résultats → rendement après la fenêtre de réaction (+) | Pièce EX-99.1 des 8-K (rubrique 2.02) ; heure d'acceptation vérifiée par la page d'index | Lecture rapide et exhaustive de l'information textuelle | Uniquement vers l'avenir (R12) ; durée probablement de plusieurs années (C11) ; prévisibilité décroissante avec l'adoption des modèles | Lopez-Lira et Tang (2023, versions révisées jusqu'en 2025), arXiv:2304.07619 ; biais d'anticipation : Glasserman et Lin (2023), arXiv:2309.17322 |

Hypothèses déconseillées à ce stade :
- **Retournement à court terme** : les coûts dominent.
- **Accruals** : affaiblissement documenté par Green, Hand et Soliman (2011, *Management Science*), à vérifier.
- **Dérive après annonce de résultats sur les grandes valeurs** : Martineau (2022, *Critical Finance Review* 11) la juge
  absente depuis 2006, résultat contesté par des travaux de 2025 (à vérifier).

**Références générales vérifiées** (recherches du 17/10/2026, sources secondaires et pages des éditeurs) :
- **McLean et Pontiff (2016), *Journal of Finance*** : rendements inférieurs de 26 % hors échantillon et de 58 % après
  publication, sur 97 prédicteurs.
- **Harvey, Liu et Zhu (2016), *Review of Financial Studies*** : seuil t ≈ 3.
- **Chen et Zimmermann (2022), *Critical Finance Review* 11(2), p. 207–264** : 319 caractéristiques ; 98 % des 161
  « clairement significatives » reproduites avec t > 1,96.
- **Hou, Xue et Zhang (2020), *Review of Financial Studies*** : 452 anomalies ; environ 65 % échouent à t ≥ 1,96 avec
  seuils NYSE et pondération par la capitalisation (chiffre rapporté par des sources secondaires, à vérifier dans
  l'article).
- **Shumway et Warther (1999), *Journal of Finance* 54(6)** : −55 % pour le Nasdaq.
- **Shumway (1997), *Journal of Finance* 52(1)** : le chiffre de −30 % cité par R1 n'a **pas** été trouvé dans les
  résumés ; à vérifier dans le texte intégral.

### Ce que le système ne pourra jamais prouver avec les données actuelles

1. **Aucun test sur le passé valable selon R1 et R4** sans données incluant les titres radiés : la liste des tickers de
   la SEC et les membres actuels du S&P 500 ne contiennent que les survivants.
2. **Aucune hypothèse comptable avant 2009–2011** : XBRL seulement, pas de Compustat. Les facteurs comptables de
   Fama-French ne peuvent donc pas être recalculés sur 1990–2008.
3. **Aucune hypothèse fondée sur les prévisions d'analystes** (surprise par rapport au consensus, révisions) : pas
   d'historique à date gratuit (`STAGE1_RESULTS.md:21`).
4. **Aucune vérification exacte de l'exécution à l'enchère d'ouverture** : l'ouverture Yahoo et celle de Cboe ne
   coïncident que dans 39 % des cas, et aucune donnée intrajournalière ni d'enchère n'est disponible.
5. **Aucune conclusion sur le Stage 3 ni sur PT1** (puissance et bruit, C01) ; aucune évaluation d'un modèle de langage
   sur le passé (R12).
6. **L'impôt exact du propriétaire** (autres plus- et moins-values, option pour le barème) reste hors du système.

---

## 6. Ce qui n'a pas pu être vérifié, et ce qu'il faudrait

| Point | Pourquoi | Ce qu'il faut |
|---|---|---|
| État du PC : passages depuis le 13/10, journaux locaux, sauvegarde, version du code, suite de tests sur le PC | Aucun accès au PC | Sortie de `git log -3`, `python main.py backup`, `pytest -q -rs` et `data/logs/last_run.json` |
| Absence d'effet sur les scores des 7 commits postérieurs au premier relevé | Recalculer le relevé du 09/10 exige de retélécharger les données SEC et de prix des 40 titres, et de lire les scores | Test de non-régression automatique : à chaque commit touchant le code du signal, recalcul du dernier relevé avec comparaison d'empreinte des scores, sans les afficher |
| Prix réellement traités de HON avant juin 2026 | Pas de troisième source non ajustée accessible | Barres TRADES non ajustées d'IBKR (phase 1.2), ou cours historiques d'une bourse |
| Grille IBKR exacte (Fixed, Tiered, frais réglementaires, change, intérêts) | Site IBKR injoignable depuis le conteneur | Page officielle datée, enregistrée avec son empreinte (phase 1.5) |
| Taux du PFU 2026, imposition des dividendes américains, prélèvements sociaux sur le PEA | Seules des sources secondaires ont été trouvées | Texte de la LFSS 2026 sur Légifrance, BOFiP, ou un fiscaliste |
| Chiffre de −30 % attribué à Shumway (1997) | Seul le résumé a été consulté | Texte intégral de l'article |
| Dispersion réelle σ des corrélations mensuelles (C11) | Il faudrait des données sans biais | La mesurer sur la période de découverte (Norgate), sans regarder la moyenne |
| Mélange de conventions d'horodatage SEC dans un même flux | Échantillon de 18 dépôts seulement | Contrôle exhaustif d'un flux complet par les pages d'index (déjà stockées par le code) |
| Comportement de la tâche Windows (limite de 4 h, réveil, session fermée) | Pas de Windows | Rapport `last_run.json` d'une semaine complète |

---

## 7. Plan d'action par priorité

**Priorité 1 — cette semaine, sans toucher à la stratégie**

1. Sur le PC : `git pull`, puis vérifier la sauvegarde : branche `sauvegarde/journaux-pc` visible sur GitHub,
   valorisations PT1 depuis le 14/10 (C03). Mettre en place une copie chiffrée quotidienne de `data/` hors du PC.
2. Corriger le test daté (C18) et ajouter `exchange_calendars` aux dépendances de développement (C29). Effort XS.
3. Erratum HON dans le CHANGELOG et réécriture du point 1.0b.1 (C06, § 4.1).
4. Décisions du propriétaire : dépôt privé (C24) ; validation de la phase 0.6 (§ 4.2).

**Priorité 2 — avant la phase 1 (phase 0.6 proposée)**

5. Références de PT1 en rendement total, en lecture seule (C04), et publication de la taille réelle du test du Stage 3
   (C05), toutes deux dans la couche de rapport.
6. Alerte de blocage de PT1 et règle écrite pour les sorties de cote (C09) ; conversion des dividendes (C19) ;
   documentation des scissions (C20).
7. Fichier de verrouillage des dépendances, et versions dans chaque relevé (C10) ; horodatage RFC 3161 des relevés et
   des lots d'ordres (C08).
8. Ordre des étapes du week-end et limite de la tâche Windows (C22) ; alerte active (C23).

**Priorité 3 — règles v3, avant toute nouvelle hypothèse**

9. Valider ou amender la v2 avec les corrections du § 3 : au minimum R0 et R7 (fiscalité, C02), R9 (C15), R12
   (succession de modèles, C11), R2 (contrôle Fama-French faisable, C12), R3 (unité de test, compteur ≥ 852, C07).
10. Écrire `docs/REFERENCE_R0.md` (ETF, enveloppe, ISIN), puis faire produire par le module de coûts R7 le seuil de
    rentabilité fiscal pour le capital réel du propriétaire.

**Priorité 4 — phase 1 réordonnée**

11. Instantanés hebdomadaires de l'univers (1.1), registre (1.6), puis lot L1 choisi mécaniquement (§ 4.4, § 5), avec
    fiches, durée attendue de P3 et démarrage des relevés vers l'avenir.
12. Ensuite seulement : essai IBKR en lecture seule (1.2), sources gratuites (1.3), contrôles (1.4), coûts (1.5).
    Décision sur Norgate (phase 2), au vu de C01.

**Priorité 5 — attentes à fixer avec le propriétaire**

13. Écrire noir sur blanc que le résultat le plus probable des 2 à 5 prochaines années est « aucun avantage démontré ».
    La rentabilité après impôts exige environ +1,5 à +2,5 points par an avant impôts face à un ETF en PEA. Tant
    qu'aucune hypothèse n'a franchi P3, l'option la plus rationnelle pour l'argent réel reste la référence R0
    elle-même.

---

*Fichiers de travail de l'audit (hors dépôt, non commités) : `hon_check.py`, `sec_conv.py`, `stage3_alpha_sim.py`,
`bench_dividend.py`, `tax_drag.py`, `journal_mech.py` et la sortie complète de pytest, dans le répertoire de travail
temporaire de la session.*
