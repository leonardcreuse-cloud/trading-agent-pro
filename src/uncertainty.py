"""
How much the interim figures of stage 3 and PT1 can mean (consigne of 2026-10-14, phase 0.3; audit of 2026-10-14).
Shown next to those figures in the dashboard, the weekly report and `python main.py paper report`. Read-only: the
stage 3 constants are only read, and nothing here changes stage 3 or PT1.

stage3_power()
  Design power of the two pre-registered stage 3 tests (docs/research/STAGE3_PREREGISTRATION.md: 40 tickers, 52
  weekly records, n_eff = 52 × min(1, 5 / H), confirmed when the mean IC > 0 and the two-sided p < 0.025).
  - Assumption: the SD of one week's cross-sectional Spearman IC is its minimum, 1 / √(N − 1) (no common factor).
    Real weekly ICs disperse more, so the real power is LOWER than shown.
  - Normal approximation, as the test's p-value (scoring_signal_fixed.two_sided_p).
  - Computed from the design only, never from a result.

pt1_noise_band(weeks)
  95% band of PT1's cumulative excess return over the equal-weight 40-ticker universe expected from chance alone:
  ±1.96 × WEEKLY_EXCESS_SD × √weeks.
  - WEEKLY_EXCESS_SD is the median weekly SD of (8 tickers drawn at random − the 40-ticker average) over 2021-10 to
    2026-10.
  - Computed by scripts/estimate_pt1_noise.py from stored yfinance closes (2,000 draws, seed 1), on 2026-10-14.
  - It describes portfolio noise, not the strategy: no signal and no PT1 result is used.
"""

import math
from statistics import NormalDist

WEEKLY_EXCESS_SD = 0.01605         # scripts/estimate_pt1_noise.py, 2026-10-14 (1.6050%)
WEEKLY_EXCESS_SD_SOURCE = 'scripts/estimate_pt1_noise.py (stored yfinance closes 2021-10 to 2026-10, 2,000 draws)'
IC_GRID = (0.02, 0.03, 0.05, 0.10)

# rule R10 of docs/REGLES_FONDATRICES.md (labels only: no figure is changed)
SELECTION_BIAS_LABEL = ('Univers choisi en 2026 : biais de sélection (règle R10). The 40 tickers were chosen by hand '
                        'in 2026; PT1 and stage 3 continue unchanged as controls.')
SURVIVORSHIP_LABEL = ('Avec biais du survivant, période 2017–2026 : ne valide rien (règle R10). Current index members '
                      'only, over a period already examined; descriptive.')


def stage3_power():
    from . import prospective as s3
    n = len(s3.UNIVERSE)
    sd = 1 / math.sqrt(n - 1)
    alpha = s3.ALPHA / len(s3.HYPOTHESES)
    z = NormalDist().inv_cdf(1 - alpha / 2)
    z80 = NormalDist().inv_cdf(0.80)
    out = []
    for name, h in s3.HYPOTHESES.items():
        n_eff = s3.MIN_RECORDS * min(1.0, s3.STEP / h)
        se = sd / math.sqrt(n_eff)
        out.append({'hypothesis': name, 'horizon_sessions': h, 'n_effective': round(n_eff, 1),
                    'power': {f'{ic:.2f}': round(1 - NormalDist().cdf(z - ic / se), 2) for ic in IC_GRID},
                    'mde_80': round((z + z80) * se, 3)})
    return {'tickers': n, 'records': s3.MIN_RECORDS, 'required_p': round(alpha, 4), 'tests': out,
            'note': ('design power, optimistic: it assumes the minimum dispersion of a weekly IC (1/sqrt(N-1)); the '
                     'real power is lower')}


def stage3_power_text():
    p = stage3_power()
    parts = [f"{t['hypothesis']} ({t['horizon_sessions']} sessions): power "
             + ', '.join(f"{v:.0%} at IC {k}" for k, v in t['power'].items())
             + f"; 80% power only from IC {t['mde_80']}" for t in p['tests']]
    return ('Stage 3 design power (optimistic upper bound, 40 tickers, 52 records): ' + '; '.join(parts)
            + '. A realistic IC (about 0.03) is unlikely to be confirmed: "not confirmed" will not mean "no effect".')


def pt1_noise_band(weeks):
    """95% half-width (percent) of the cumulative excess return over the equal-weight universe from chance alone."""
    if not weeks or weeks <= 0:
        return None
    return round(1.96 * WEEKLY_EXCESS_SD * math.sqrt(weeks) * 100, 1)


def pt1_noise_text(excess_pct, sessions):
    weeks = (sessions or 0) / 5
    band = pt1_noise_band(weeks)
    if band is None:
        return 'PT1 noise band: no mark yet.'
    excess = 'unknown' if excess_pct is None else f'{excess_pct:+.2f}%'
    inside = excess_pct is not None and abs(excess_pct) <= band
    return (f'PT1 vs the equal-weight universe: {excess} after about {weeks:.1f} week(s); chance alone gives ±{band}% '
            f'(95%) at this length' + (' — the difference is within the noise' if inside else '')
            + f' (±{pt1_noise_band(52)}% after 52 weeks). The band comes from random 8-stock portfolios '
              '(src/uncertainty.py).')
