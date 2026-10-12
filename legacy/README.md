# Legacy code (quarantined 2026-10-12, master mission P0)

Nothing in this folder is imported by the system (`main.py`, `scripts/daily_run.py`, `scheduler.py`) or by the
tests. The files were moved here with `git mv` (history kept) so that no production path can use them by
accident. They no longer run as they are (their relative imports point to `src/`). To reuse an idea, rewrite it
inside `src/` under the data rules of `docs/DATA_POLICY.md`, with tests; do not move a file back unchanged.

## `legacy/src/` — modules never called by the pipeline

| Module | Why it is quarantined |
|---|---|
| `scoring_signal.py` | Old combiner: missing scores default to 50 (`.get('technical_score', 50)`); replaced by `scoring_signal_fixed.py`. |
| `scoring_confidence.py`, `scoring_reliability.py` | Return fixed numbers (50, 75, 90, 95...) as "confidence" / "reliability": not measured. |
| `conflict_detection.py` | Example prices hardcoded in the code (150.25 / 150.50, 2.50). |
| `options_analyzer.py` | Neutral baseline score 50; superseded by option snapshots in `external_sources.py` (positioning section). |
| `model_calibration.py` | Defaults such as a 50 % win rate when a result is missing; no out-of-sample calibration. |
| `sector_analysis.py` | Peer P/E from `yfinance .info` without provenance; replaced by the weekly `sector` section. |
| `analyst_consensus.py`, `short_interest.py`, `calendar_events.py`, `earnings_nlp.py`, `relative_strength.py`, `data_validation.py` | Never wired in; their functions are covered (with provenance) by `external_sources.py`, the weekly sections and `pipeline_audit.py`, or not implemented yet. |
| `backtester_fixed.py`, `backtester_no_bias.py`, `walk_forward_test.py` | Earlier validation attempts, replaced by `walk_forward.py` and `src/research/`. |
| `report_saver.py`, `scheduler.py`, `test_day1.py` | Old helpers / smoke script; replaced by `report_generator.py`, `scripts/daily_run.py`, `tests/`. |

## `legacy/scripts/` — ad-hoc scripts from the project root

Manual experiments (`test_*.py`, `debug_news.py`, `audit_phase4.py`) that were not part of the test suite
(`pytest.ini` runs `tests/` only). `audit_phase4.py` called `backtester_no_bias`.

## `legacy/initial_snapshots/`

`diagnostic_*.txt`, `structure*.txt`: text copies of the source files of the initial commit (2026-10-05).
