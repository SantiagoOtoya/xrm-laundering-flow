# Hourly Monero prices

`data/analysis/xmr_usd_1h.csv` derives Kraken spot XMR/USD hourly OHLCVT from
the retained `data/prices/xmr_usd_1m.csv.gz` minute candles. The requested window
is **2017-01-02 00:00 UTC through 2026-10-03 00:00 UTC, exclusive**, including
all of October 2, 2026. Every calendar hour has one row, ordered chronologically.

| Coverage | Count |
| --- | ---: |
| Calendar hours | 85,464 |
| Hours with observed trades | 83,919 |
| Empty hours | 1,545 |
| Hours with 1–59 observed minutes | 83,468 |
| Hours with all 60 minutes observed | 451 |
| Source minute candles aggregated | 2,053,386 |
| Source trades represented | 12,259,214 |

The first observed hour starts **2017-01-02 19:00 UTC**; its first observed
minute is 19:14. The last observed hour starts **2026-10-02 23:00 UTC**; its
last observed minute is 23:57. Earlier empty hours in the requested window are
retained with blank prices.

## Aggregation and fields

Each row describes `[timestamp_utc, timestamp_utc + 1 hour)`. The timestamp is
the hour's start; full-hour high, low, close and volume are available only after
the hour ends. An intraday model must use completed prior hours for features.

| Fields | Meaning |
| --- | --- |
| `timestamp_unix`, `timestamp_utc` | UTC hour start, as Unix seconds and ISO 8601 |
| `open_usd` | First observed minute's open inside the hour |
| `high_usd`, `low_usd` | Maximum minute high and minimum minute low |
| `close_usd` | Last observed minute's close inside the hour |
| `volume_xmr`, `trade_count` | Sum of observed minute base volume and trade counts |
| `observed_minutes`, `missing_minutes` | Distinct recorded minutes and `60 - observed_minutes` |
| `first_observed_minute_utc`, `last_observed_minute_utc` | Source candle timestamps within this hour |
| `open_delay_seconds` | First observed minute start minus hour start |
| `close_age_seconds` | Hour end minus last observed minute start; at least 60 seconds |
| `volume_usd_estimate`, `volume_method` | Sum of minute close × minute XMR volume, labeled as an estimate |
| `source` | Retained Kraken archive/API source labels, joined with semicolons if needed |

No hourly price is a daily average. No price or volume is forward filled.
For an empty hour, OHLC, both volume fields, source and price timing fields are
blank; observed minutes and recorded trade count are zero. A zero recorded
count does not establish that Kraken had no trades. Partially observed hours
aggregate only available minutes.

Missing minute candles can reflect no trades or missing source records.
Having fewer than 60 recorded minutes does not by itself invalidate the hour.
Even 60 observed minutes does not certify source completeness. The timing
fields measure minute-start timestamps, since exact intraminute trade times
are unavailable in the historical candle archive. No historical quotes, bid/ask
spreads, trade VWAP or exact dollar turnover are reconstructed.

Decimal arithmetic preserves source price precision and additive quantities.
The coverage sidecar `data/analysis/xmr_usd_1h.coverage.json` records the source,
builder and output SHA-256 hashes and coverage by year. Existing minute/daily
inputs and model configurations remain the provenance for their frozen runs.

## Reproduction and validation

Run from the repository root with Python 3.10+ and its standard library:

```sh
python scripts/build_hourly_prices.py
python scripts/build_hourly_prices.py --verify
python -m unittest discover -s tests -p 'test_*price*.py'
```

The builder checks the source checksum against the existing minute coverage
manifest, validates minute ordering, OHLCVT and source boundaries, and verifies
that every source minute is counted once. `--verify` rebuilds in a temporary
directory and compares the hourly CSV and coverage sidecar byte for byte.
The six hourly tests cover sparse OHLC, blank hours and window edges,
UTC/archive boundaries, full-hour counts, invalid source rows and BTC volume fields.
The shared builder accepts `--pair BTC` for the separate Bitcoin hourly dataset;
the default remains XMR.

`docs/xmr_hourly_validation.json` records an additional independent grouping
check of every output hour against its source minutes and a reconciliation with
all 3,561 existing daily XMR rows. Daily close and observed-minute counts must
match exactly. Daily estimated USD volume uses an absolute tolerance of
USD 0.00000001 because the older daily builder uses a smaller decimal context.

## Research interpretation

Hourly rows provide finer timing, intraday ranges and volume for shorter-window
research. The table has 24 times as many calendar bins as the daily table,
while describing the same underlying minute observations. It does not create
additional independent incidents. An hourly prediction experiment needs a
separate target and temporal validation, with overlapping event windows kept
together or purged at split boundaries. Most existing incident timestamps have
day-level precision; hourly prices alone do not establish their detection hour.

This derivation computes prices and coverage only. It does not compute incident
outcomes, train an hourly model or measure strategy performance.
