"""
Phase P1.5 - debt / equity XBRL mapping (offline). Values are the real SEC figures quoted in
src/sec_xbrl.py, used here only to check the arithmetic of each definition.
"""

import pytest


def inst(**tags):
    """{tag: {date: row}} from tag=(date, value) pairs."""
    out = {}
    for tag, pairs in tags.items():
        for day, value in (pairs if isinstance(pairs, list) else [pairs]):
            out.setdefault(tag, {})[day] = {'value': value}
    return out


def test_combined_total_is_used_as_is():
    from src.sec_xbrl import debt_at
    d = '2024-05-31'   # ORCL
    i = inst(DebtLongtermAndShorttermCombinedAmount=(d, 86.87), LongTermNotesAndLoans=(d, 76.26),
             NotesPayableCurrent=(d, 10.61), ShortTermBorrowings=(d, 1.0))
    debt = debt_at(i, d)
    assert debt['definition'] == 'combined_total' and debt['value'] == 86.87


def test_notes_and_loans_plus_current_matches_reported_total():
    from src.sec_xbrl import debt_at
    d = '2024-05-31'   # ORCL without the combined total
    debt = debt_at(inst(LongTermNotesAndLoans=(d, 76.26), NotesPayableCurrent=(d, 10.61)), d)
    assert debt['definition'] == 'notes_and_loans'
    assert debt['value'] == pytest.approx(86.87)


def test_finance_lease_definition_is_flagged_and_debt_current_not_double_counted():
    from src.sec_xbrl import debt_at
    d = '2023-09-30'   # GE
    debt = debt_at(inst(LongTermDebtAndCapitalLeaseObligations=(d, 19.49), DebtCurrent=(d, 1.33),
                        ShortTermBorrowings=(d, 0.5)), d)
    assert debt['value'] == pytest.approx(20.82)                 # DebtCurrent includes short-term
    assert debt['includes_finance_leases'] is True
    assert 'ShortTermBorrowings' not in debt['tags']


def test_short_term_borrowings_added_once_commercial_paper_never_on_top():
    from src.sec_xbrl import debt_at
    d = '2024-10-27'   # HD-like: commercial paper is part of short-term borrowings
    debt = debt_at(inst(LongTermDebt=(d, 50.0), ShortTermBorrowings=(d, 1.34), CommercialPaper=(d, 1.30)), d)
    assert debt['tags'] == ['LongTermDebt', 'ShortTermBorrowings']
    assert debt['value'] == pytest.approx(51.34)
    only_cp = debt_at(inst(LongTermDebt=(d, 5.435), CommercialPaper=(d, 2.1)), d)
    assert only_cp['value'] == pytest.approx(7.535)


def test_short_term_only_is_not_debt():
    from src.sec_xbrl import debt_at
    d = '2026-06-30'   # CVX quarter-end: only short-term borrowings tagged
    assert debt_at(inst(ShortTermBorrowings=(d, 0.401)), d) is None


def test_balance_sheet_falls_back_to_latest_date_with_debt_and_flags_nci_equity():
    from src.sec_xbrl import balance_sheet
    i = inst(StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest=[
                 ('2025-12-31', 20.0), ('2026-06-30', 18.7)],
             LongTermDebtNoncurrent=('2025-12-31', 27.0), ShortTermBorrowings=('2025-12-31', 4.0))
    sheet = balance_sheet(i)                                     # CAT-like: debt only in the 10-K
    assert sheet['latest_equity_date'] == '2026-06-30' and sheet['date'] == '2025-12-31'
    assert sheet['debt']['value'] == 31.0 and sheet['equity']['value'] == 20.0
    assert sheet['equity_tag'].endswith('NoncontrollingInterest')


def test_balance_sheet_too_old_debt_is_unavailable():
    from src.sec_xbrl import balance_sheet
    i = inst(StockholdersEquity=[('2024-01-31', 10.0), ('2026-06-30', 12.0)],
             LongTermDebt=('2024-01-31', 3.0))
    sheet = balance_sheet(i)
    assert sheet['debt'] is None and sheet['date'] == '2026-06-30'


def test_parent_equity_preferred_over_nci_equity():
    from src.sec_xbrl import equity_at
    d = '2026-06-30'
    row, tag = equity_at(inst(StockholdersEquity=(d, 10.0),
                              StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest=(d, 11.0)), d)
    assert tag == 'StockholdersEquity' and row['value'] == 10.0
