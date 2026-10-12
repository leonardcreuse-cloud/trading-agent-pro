"""
PT1 sector lookup: the SEC SIC code is read from the submissions feed's raw JSON (stub feed, no network).
"""


class Feed:
    def __init__(self, db=None):
        pass

    def get_filings(self, ticker):
        if ticker == 'BAD':
            raise RuntimeError('feed unavailable')
        sic = {'NVDA': '3674', 'MSFT': '7372', 'GOOGL': '7370'}.get(ticker)
        return {'raw': {'sic': sic} if sic else {}, 'filings': [], 'fetch': None}


def paper():
    from src.paper import Paper
    p = Paper.__new__(Paper)
    p.db = None
    return p


def test_sic_major_group_from_raw_feed(monkeypatch):
    import src.sec_parser as S
    monkeypatch.setattr(S, 'SECParser', Feed)
    p = paper()
    assert p._sector('NVDA') == 'SIC 36'
    assert p._sector('MSFT') == p._sector('GOOGL') == 'SIC 73'


def test_unknown_sector_is_never_pooled(monkeypatch):
    import src.sec_parser as S
    monkeypatch.setattr(S, 'SECParser', Feed)
    p = paper()
    assert p._sector('XOM') == 'unknown XOM'                       # no SIC in the feed
    assert p._sector('BAD') == 'unknown BAD'                       # feed error
    assert p._sector('XOM') != p._sector('BAD')
