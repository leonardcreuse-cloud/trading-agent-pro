---
name: phase3-complete
description: Phase 3 COMPLETE - Scoring Signal Fixed avec News Engine + Signal Agreement metric
date: 2026-10-04
---

> **CORRECTION (audit, phase P0.1)** — Les affirmations de ce document ne sont pas valides :
> les fondamentaux étaient codés en dur, le walk-forward ne comparait jamais les signaux aux
> rendements réels (« READY_FOR_LIVE » sans fondement), et les « P(up) » étaient des fréquences
> historiques non conditionnelles, mesurées sur la fenêtre même où elles étaient « validées ».
> Voir docs/CHANGELOG.md et docs/DATA_POLICY.md. Document conservé pour l'historique.

PHASE 3 - RÉSUMÉ FINAL

✅ Bugs corrigés:
1. News score ignoré → INCLUS (25% poids)
2. Poids arbitraires → Validés (tech 25%, fund 50%, news 25%)
3. Seuils arbitraires → Fixés (BUY>=65, SELL<=40)
4. Confidence circulaire → SIGNAL AGREEMENT (accord des sources + force du signal)
5. Double-counting → Éliminé (reliability/confidence plus jamais comme poids)
6. Architecture confuse → Nettoyée et linéaire

✅ Pipeline validé:
- NewsAPI: 91-100 articles par ticker
- Sentiment: avg 50-52 (légèrement positif)
- News Score: 50-52 (reflète les données)
- Combine: tech + fund + news
- Signal: BUY/HOLD/SELL basé seuils
- Agreement: mesure d'alignement (0-100)

✅ Résultats stables:
CRWD: BUY (65.19) Agreement 59.26%
NET:  HOLD (60.34) Agreement 57.25%
RKLB: HOLD (58.7) Agreement 62.35%
MP:   HOLD (52.1) Agreement 48.93%

Backtests Walk-Forward tous READY_FOR_LIVE

---

PHASE 4 ROADMAP

Objectif: PREDICTION ENGINE avec probabilités multi-horizon

Actuellement: Signal scoring + agreement metric (classification simple)
Demandé: P(up) 1D/5D/20D/60D + Expected Return (basé backtests, pas arbitraire)

Architecture Phase 4:
1. Feature Store (200 features: prix, volume, sentiment, technicals...)
2. Feature Engineering (rolling stats, lags, interactions)
3. Backtest Data: Extraire win_rate 1D/5D/20D/60D par ticker
4. Probability Model: Calibrer P(up) depuis win_rate
5. Return Model: Expected return depuis P&L backtest
6. Risk Model: Volatility + drawdown

Résultat final:
CRWD
  Signal: BUY
  Score: 65.19
  Agreement: 59.26%
  
1D: P(up) 56%, E[return] +0.7%
5D: P(up) 63%, E[return] +3.1%
20D: P(up) 61%, E[return] +5.8%

(ces % sortent de backtester_no_bias.py, pas inventés)
