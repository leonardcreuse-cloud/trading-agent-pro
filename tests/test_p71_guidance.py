"""
Gap round G1: company guidance quoted from the 8-K earnings release (synthetic HTML, logic only).
"""

RELEASE = """<html><body>
<p>ACME reports results</p>
<p>&bull; Revenue grew 20%. We expect strong demand.</p>
<p>Financial Outlook</p>
<p>For the third quarter of fiscal 2027, we expect:</p>
<table><tr><td>Total revenue</td><td>$100.0 - $102.0&nbsp;million</td></tr>
<tr><td>Non-GAAP operating income</td><td>$10.0 million</td></tr></table>
<p>These statements are forward-looking.</p>
<p>Conference Call Information</p>
<p>ACME will host a call to discuss its outlook.</p>
</body></html>"""

INDEX = """<table>
<tr><td>1</td><td>8-K</td><td><a href="/ix?doc=/Archives/edgar/data/1/000000000126000001/acme-8k.htm">acme-8k.htm</a></td><td>8-K</td></tr>
<tr><td>2</td><td>PRESS RELEASE</td><td><a href="/Archives/edgar/data/1/000000000126000001/ex991.htm">ex991.htm</a></td><td>EX-99.1</td></tr>
</table>"""


def test_text_lines_and_outlook_section():
    from src.guidance import find_outlook, text_lines
    lines = text_lines(RELEASE)
    assert 'Total revenue | $100.0 - $102.0 million' in lines
    heading, body = find_outlook(lines)
    assert heading == 'Financial Outlook'                                   # the bullet with 'expect' is not a heading
    assert body == ['For the third quarter of fiscal 2027, we expect:', 'Total revenue | $100.0 - $102.0 million',
                    'Non-GAAP operating income | $10.0 million', 'These statements are forward-looking.']
    assert find_outlook(['Results', 'Revenue grew.']) == (None, [])


def test_exhibit_from_index_and_point_in_time_release():
    from src.guidance import exhibit_from_index, latest_release
    assert exhibit_from_index(INDEX) == '/Archives/edgar/data/1/000000000126000001/ex991.htm'
    assert exhibit_from_index('<table></table>') is None
    filings = [{'form': '8-K', 'items': ['2.02', '9.01'], 'accession_number': 'a1', 'published_at': '2026-08-06T20:04:33+00:00'},
               {'form': '8-K', 'items': ['2.02'], 'accession_number': 'a2', 'published_at': '2026-11-05T21:00:00+00:00'},
               {'form': '8-K', 'items': ['5.02'], 'accession_number': 'a3', 'published_at': '2026-09-01T12:00:00+00:00'},
               {'form': '10-Q', 'items': [], 'accession_number': 'a4', 'published_at': '2026-08-07T12:00:00+00:00'}]
    assert latest_release(filings, '2026-10-10T05:00:00+00:00')['accession_number'] == 'a1'    # a2 is after T
    assert latest_release(filings, '2026-08-01T00:00:00+00:00') is None


class Sec:
    def __init__(self, pages):
        self.pages, self.last_error, self.calls = pages, None, []

    def _get(self, url, as_json=False, max_age=None):
        self.calls.append(url)
        page = self.pages.get(url)
        if page is None:
            self.last_error = 'HTTP 404'
        return page


def test_guidance_statuses():
    from src.guidance import guidance
    filings = [{'form': '8-K', 'items': ['2.02'], 'accession_number': '0000000001-26-000001',
                'filing_date': '2026-08-06', 'published_at': '2026-08-06T20:04:33+00:00'}]
    index = 'https://www.sec.gov/Archives/edgar/data/1/000000000126000001/0000000001-26-000001-index.htm'
    exhibit = 'https://www.sec.gov/Archives/edgar/data/1/000000000126000001/ex991.htm'
    ok = guidance(Sec({index: INDEX, exhibit: RELEASE}), '0000000001', filings, '2026-10-10T05:00:00+00:00')
    assert ok['status'] == 'OK' and ok['heading'] == 'Financial Outlook' and ok['url'] == exhibit
    assert ok['filing']['accession_number'] == '0000000001-26-000001'
    none = guidance(Sec({index: INDEX, exhibit: '<p>Results only.</p>'}), '1', filings, '2026-10-10T05:00:00+00:00')
    assert none['status'] == 'NOT REPORTED' and 'no outlook' in none['reason']
    down = guidance(Sec({}), '1', filings, '2026-10-10T05:00:00+00:00')
    assert down['status'] == 'DATA UNAVAILABLE' and 'HTTP 404' in down['reason']
    early = guidance(Sec({}), '1', filings, '2026-08-01T00:00:00+00:00')
    assert early['status'] == 'NOT REPORTED' and 'no 8-K with item 2.02' in early['reason']
