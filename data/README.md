# Data

Raw licensed data is not committed. This file lists the inputs the code expects, how to get them, and their checksums.

Snapshot span: **2017-01-02 00:00 UTC to 2026-10-03 00:00 UTC** (end exclusive), 85,464 calendar hours.

## Model inputs (hourly)

| File | Contents | SHA-256 |
| --- | --- | --- |
| `data/analysis/xmr_usd_btc_combined_1h.csv` | Hourly XMR/USD closes: Kraken first, Binance XMR/BTC × Kraken BTC/USD where Kraken has no trade (see `HYPOTHESIS.md`, Amendment 1) | `daec6f4c098c7c8267a705973afbd0f51e4ba5f18338f0524242420a4d1e4c45` |
| `data/analysis/btc_usd_1h.csv` | Hourly Kraken BTC/USD bars | `fdbbfb377438eff77c3d98e56b66094b0782506d997be5a679a73533bf16deaf` |
| `data/incidents_over_1m.csv` | Incident catalog (588 groups over $1M) | TBD |

Both price files have 85,464 rows. Price columns used by the model: `timestamp_utc` (start of the hour), `close_usd`, `close_age_seconds`. A bar stamped with its starting hour is usable only after it ends (`available_after_utc`). The combined XMR file also records each close's source (`close_usd_source`, `close_uses_usd_proxy`) and a `needs_price_review` flag.

Incident columns used by the model: canonical incident ID, `detection_available_at_utc`, `loss_known_at_detection_usd` (see `HYPOTHESIS.md`, Incidents).

## Raw inputs (not committed)

| File | Contents | SHA-256 |
| --- | --- | --- |
| `data/prices/xmr_usd_1m.csv.gz` | Kraken XMR/USD 1-minute candles, normalized from the Kraken OHLCVT archive and public trades API | `fc59f062a11123e4b98e1aa760feacea2c8a1c3b9a3d21b07dbbcb1af1ef20e0` |
| `data/prices/btc_usd_1m.csv.gz` | Kraken BTC/USD 1-minute candles, same sources | `af2130d776262732718623e5b6bd38f0e6c548e60d78e903e15a53c9f2aa2466` |
| `data/raw/binance/Binance_XMRBTC_1m_2017-11_to_2024-02.zip` | 76 Binance XMRBTC 1-minute monthly CSVs, unchanged from data.binance.vision | `98ff40eb67261b5bd33fa92a964b8e8af3fbc8b5d1039afd44010d31f4dd3e67` |

## How to get them

1. **Kraken:** download the Kraken OHLCVT archive and recent trades (see `docs/DATA_SOURCES.md`), normalized into the two `*_1m.csv.gz` files above.
2. **Binance:** download the 76 monthly ZIPs from `https://data.binance.vision/?prefix=data/spot/monthly/klines/XMRBTC/1m/` (2017-11 to 2024-02) and check each against Binance's `.CHECKSUM` file.
3. **Build the hourly files** (TBD: exact commands added with the build scripts).
4. **Verify:** `sha256sum data/analysis/*.csv` must match the table above.
