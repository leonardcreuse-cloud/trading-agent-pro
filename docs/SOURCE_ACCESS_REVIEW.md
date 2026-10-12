# Review of the network-blocked data providers (2026-10-12)

**Scope.** The 10 official or secondary providers that `python main.py sources` reports as refused by the cloud
environment's network policy (gateway 403 on CONNECT, probe of 2026-10-12).

**Question.** For each one: would it materially improve the weekly analyst, given what the system already obtains
from reachable official sources?

**Where it matters.** Production runs on the owner's PC (`scripts/daily_run.py`), where these hosts may already be
reachable. Run `python main.py sources` there to see which are. Allowing a domain in the cloud environment only
matters for development and testing here.

| Provider (blocked host) | Report requirement it would support | Exact data / endpoint needed | Already available from a reachable official source? | Free and legal for this use | Effort | Value | Recommendation |
|---|---|---|---|---|---|---|---|
| USGS minerals (www.usgs.gov, pubs.usgs.gov, www.sciencebase.gov) | Part 7 (commodities) and 5 (geopolitics, supply chains): rare earths and lithium, currently DATA UNAVAILABLE. Directly relevant to MP (focus ticker) and ALB. | Mineral Commodity Summaries annual data release (CSV): world mine and refinery production by country, U.S. import reliance, annual average prices (rare-earth oxides, lithium carbonate); rare-earths and lithium chapters | No: FRED / IMF carry no rare-earth or lithium price series | Yes: U.S. government work, public domain | Moderate: annual CSV, one parser, stored with its release date | Medium. Annual, so it gives the structural context (China's share of supply, import reliance, annual price level), not weekly moves. It fills an explicit gap for a focus company. | **Yes (priority 1)** |
| US Treasury FiscalData (api.fiscaldata.treasury.gov) | Part 4 (macro: fiscal policy and liquidity), 18 (risk) | `v1/accounting/dts/operating_cash_balance` (daily Treasury General Account), `v1/accounting/od/auctions_query` (auction results: bid-to-cover, high yield), `v2/accounting/od/debt_to_penny` | Partly. FRED has the monthly deficit (MTSDS133FMS, in the report), debt (GFDEBTN, quarterly) and the Treasury account weekly from H.4.1. Daily cash and auction results are not on FRED. | Yes: public domain, open API, no key | Low to moderate: JSON API, daily | Medium-low. It adds a daily fiscal and liquidity view and auction demand, useful context for rates; not essential. | **Optional (priority 2)**, only if a fiscal / liquidity paragraph is wanted |
| OFR Financial Stress Index (data.financialresearch.gov) | Part 3 (regime) and 18 | `v1/series/timeseries?mnemonic=FSI-OFR_FSI` and its five components | Largely: NFCI (Chicago Fed, weekly) is in the report; the regime already uses VIX, high-yield spread, curve and real yields | Yes: public | Low | Low: overlaps the existing stress measures | No |
| University of Michigan consumer surveys (www.sca.isr.umich.edu) | Part 6 (socioeconomic): consumer sentiment and its publication dates (a stated limitation) | `files/tbmics.csv` (index), the components and inflation-expectations tables | Mostly: FRED carries UMCSENT and MICH (1-year inflation expectations) with vintages. The free files carry final monthly values; the mid-month preliminary reading is a press release, not a stable free file. | Free download; redistribution terms set by the university (internal analysis only) | Low | Low: the files would not provide the preliminary reading that is actually missing | No |
| ECB Data Portal (data-api.ecb.europa.eu) | Part 4 (central banks), 5 | e.g. `FM/D.U2.EUR.4F.KR.DFR.LEV` (deposit rate), HICP, €STR, euro-area yields | Mostly: FRED has ECBDFR (in the report), euro-area HICP and EUR/USD | Yes: ECB reuse policy | Low | Low for a US-equity universe | No |
| US Census API (api.census.gov) | Part 6 (consumption, housing, trade) | `timeseries/eits/marts` (retail), `resconst` (housing), trade | Yes: FRED carries RSAFS, HOUST, durable goods and trade, with ALFRED vintages (better point-in-time than the Census API) | Yes | Low | Low: redundant | No |
| New York Fed Markets API (markets.newyorkfed.org) | Part 4 (money markets) | `api/rates/all/latest.json` (SOFR, EFFR, OBFR), repo operations | Yes: FRED has SOFR, EFFR (DFF, in the report), reverse repo (RRPONTSYD) | Yes | Low | Low: redundant | No |
| IMF data API (api.imf.org) | Part 7 (commodities), 5 | PCPS commodity prices, WEO projections | Mostly: the IMF commodity series used in the report come through FRED (PCOPPUSDM and others) | Yes, under IMF terms | Moderate (SDMX) | Low. WEO projections are forecasts, outside the report's fact base. | No |
| World Bank Indicators API (api.worldbank.org) | Part 5 / 6 (global growth), 7 (Pink Sheet) | e.g. `country/WLD/indicator/NY.GDP.MKTP.KD.ZG` | Partly: annual global aggregates are on FRED; the monthly Pink Sheet is a spreadsheet on another host | Yes: CC BY 4.0 | Low | Low: annual, slow | No |
| Stooq (stooq.com) | Part 2 / 11 (prices): a third price source | `q/d/l/?s=<ticker>.us&i=d` | Yes in substance: the Cboe delayed daily history is now integrated as the second source and agrees with yfinance on 40 of 41 tickers | Free for personal use; terms unclear for systematic use | Low | Low now: a third vote would rarely change a conclusion (the HON split was settled by SEC data and Cboe) | No |

## Recommendation

1. **USGS minerals data (allow `www.usgs.gov`, `pubs.usgs.gov`, `www.sciencebase.gov`).** It is the only blocked
   provider that fills a gap the report states today (rare earths and lithium) for a focus company, from an
   official, public-domain source.
   - Implementation after the domains are allowed:
     - a `collect` step for the annual data release, stored with its publication date;
     - a few commodity-section rows (production shares, import reliance, annual prices).
   - Rare earths stay "annual context", never a weekly signal.
2. **US Treasury FiscalData (`api.fiscaldata.treasury.gov`), optional.** Add it only if a daily fiscal and
   liquidity paragraph is wanted. Otherwise the FRED series already in the report cover fiscal policy at the
   frequency the analysis needs.

The other eight are not recommended. They duplicate series the report already takes from FRED / ALFRED (which
also keeps revision vintages, the better point-in-time source), or they add little to a weekly US-equity analysis.

**How to allow a domain.** Environment settings, Network access, Allowed domains
(https://code.claude.com/docs/en/cloud-environments#network-access). Then run `python main.py sources` again; the
registry in `src/source_registry.py` already lists these endpoints. No source is used until it is integrated,
tested and documented.
