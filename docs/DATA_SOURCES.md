# Data sources

Every source used by this project is listed here and cited in the quant note.

## Prices

| Source | Used for | Access |
| --- | --- | --- |
| Kraken OHLCVT trade-history archive (official downloadable archive) | Hourly XMR/USD and BTC/USD bars: features, entry and exit prices, target | https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data |
| Kraken public REST API | Recent trades not yet in the archive | https://docs.kraken.com/api-reference/market-data/get-recent-trades |
| Binance public spot klines, XMRBTC 1-minute, monthly files 2017-11 to 2024-02 (76 files) | XMR/USD proxy where Kraken has no XMR/USD trade: Binance XMR/BTC close × Kraken BTC/USD close in the same UTC minute (see `HYPOTHESIS.md`, Amendment 1) | https://data.binance.vision/?prefix=data/spot/monthly/klines/XMRBTC/1m/ (column definitions and checksums: https://github.com/binance/binance-public-data) |

Kraken is the primary price source; BTC/USD comes from Kraken only. Binance XMR/BTC covers 2017-11-10 06:12 UTC to 2024-02-20 02:59 UTC, after which Binance delisted XMR. All 76 Binance monthly CSVs were checked against the official ZIPs and Binance's published checksums. Prices are single-venue or cross-venue conversion proxies, not a market-wide average. The Kraken snapshot is tagged `kraken_official_ohlcvt_2026q2`.

## Incidents

| Source | Used for | Access |
| --- | --- | --- |
| DefiLlama hacks dataset | Incident list and reported losses | https://defillama.com/hacks (API: https://api.llama.fi/hacks) |
| SlowMist Hacked | Incident list and dates | https://hacked.slowmist.io/en/ |
| rekt.news leaderboard | Large incidents and loss figures | https://rekt.news/leaderboard/ |
| Linked primary sources | Report times and loss claims (news, X/Twitter, Medium, Reddit, block explorers, DOJ releases, issuer statements) | Per incident, recorded in the catalog |

The catalog (`incidents_over_1m.csv`) holds 588 incident groups with losses over $1M. Only incidents with a known loss strictly above $5M qualify for the model.

## Costs

| Source | Used for | Access |
| --- | --- | --- |
| Kraken Pro fee schedule (checked 2026-10-04) | 80 bps taker fee per side in the 200 bps round-trip cost | https://www.kraken.com/features/fee-schedule |

The 20 bps per side spread and slippage allowance is a planning estimate, not a measurement.

## Licensing

Raw Kraken archive files, Binance monthly files, API responses and full captures of news pages are **not** committed. The repository contains download instructions and SHA-256 checksums of the derived files (see `data/README.md`), so anyone can rebuild and verify the same inputs.
