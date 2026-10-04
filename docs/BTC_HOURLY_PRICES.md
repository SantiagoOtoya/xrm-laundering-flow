# Hourly Bitcoin prices

`data/analysis/btc_usd_1h.csv` derives Kraken spot BTC/USD hourly OHLCVT from
the retained `data/prices/btc_usd_1m.csv.gz` minute candles. The window is
**2017-01-02 00:00 UTC through 2026-10-03 00:00 UTC, exclusive**, including
all of October 2, 2026. One row represents each calendar hour, in chronological
order, using the same UTC boundaries as the XMR hourly dataset.

| Coverage | Count |
| --- | ---: |
| Calendar hours | 85,464 |
| Hours with observed candles | 85,382 |
| Empty hours | 82 |
| Hours with 1–59 observed minutes | 34,353 |
| Hours with all 60 minutes observed | 51,029 |
| Source minute candles aggregated | 4,852,295 |
| Source trades represented | 109,461,794 |

The first hour starts **2017-01-02 00:00 UTC**; the last starts
**2026-10-02 23:00 UTC**. The final recorded minute is 23:59 UTC.

## Aggregation and gaps

Each row covers `[timestamp_utc, timestamp_utc + 1 hour)`. Open is the first
recorded minute's open, high and low are the extrema of the recorded minutes,
and close is the last recorded minute's close. `volume_btc` and `trade_count`
sum the source minutes. `volume_usd_estimate` sums minute close times BTC volume;
it is an estimate, not exact traded dollar notional.

`observed_minutes` and `missing_minutes` report recorded-minute coverage.
First/last recorded-minute timestamps, `open_delay_seconds`, `close_age_seconds`
and source labels are retained. The field definitions match
[the XMR hourly schema](XMR_HOURLY_PRICES.md#aggregation-and-fields), with
`volume_btc` replacing `volume_xmr`.

Empty hours have blank OHLC, volumes and price timing fields, with zero recorded
minutes and trade count. No prices are forward filled. Partially observed hours
aggregate only available minute candles. A missing candle can reflect no trades
or missing source records; the coverage fields do not certify complete exchange
records. Hour timestamps mark the interval start; complete-hour values are only
available after the hour ends.

## Reproduction and validation

Run from the repository root with Python 3.10+ and its standard library:

```sh
python scripts/build_hourly_prices.py --pair BTC
python scripts/build_hourly_prices.py --pair BTC --verify
python -m unittest discover -s tests -p 'test_*price*.py'
```

`data/analysis/btc_usd_1h.coverage.json` records source, builder and output
SHA-256 hashes, coverage by year and the gap policy. The builder checks the
minute input against its stored checksum, validates ordering and OHLCVT, and
requires every source minute to be counted exactly once.

`docs/btc_hourly_validation.json` records an independent grouping check of
every calendar hour against its source minutes. It also reconciles hourly
rollups to all 3,561 existing daily BTC rows: closes and minute counts match
exactly; estimated USD volume uses a USD 0.00000001 absolute tolerance for
the older daily builder's smaller decimal context.

This derivation produces prices and coverage without calculating incident
outcomes or changing model configurations.
