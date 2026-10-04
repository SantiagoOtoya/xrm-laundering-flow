"""Derive UTC hourly OHLCVT from retained Kraken minute candles, without filling gaps."""
import argparse
import csv
import json
import tempfile
from collections import Counter
from decimal import Decimal, localcontext
from pathlib import Path

from build_prices import VOLUME_METHOD, iso, sha256, validate_bar
from price_pairs import (ROOT, START, END, coin_symbol, minute_columns,
                         minute_path, open_text, volume_column)

OUTPUT = ROOT / 'data/analysis/xmr_usd_1h.csv'
COLUMNS = [
    'timestamp_unix', 'timestamp_utc', 'open_usd', 'high_usd', 'low_usd',
    'close_usd', 'volume_xmr', 'trade_count', 'observed_minutes', 'missing_minutes',
    'first_observed_minute_utc', 'last_observed_minute_utc',
    'open_delay_seconds', 'close_age_seconds', 'volume_usd_estimate',
    'volume_method', 'source',
]


def hourly_path(coin):
    return ROOT / f'data/analysis/{coin_symbol(coin).lower()}_usd_1h.csv'


def hourly_columns(coin):
    return [volume_column(coin_symbol(coin)) if key == 'volume_xmr' else key
            for key in COLUMNS]


def hourly_rows(rows, start=START, end=END, coin='XMR'):
    """Emit every UTC hour in [start, end); prices describe observed trades only."""
    if start % 3600 or end % 3600 or start >= end:
        raise ValueError('Hourly bounds must be ordered, whole UTC hours')
    coin = coin_symbol(coin)
    volume_key = volume_column(coin)
    hour = start
    bar = None
    last = None

    def result():
        row = dict.fromkeys(hourly_columns(coin), '')
        row.update(timestamp_unix=hour, timestamp_utc=iso(hour),
                   trade_count=0, observed_minutes=0, missing_minutes=60,
                   volume_method=VOLUME_METHOD)
        if bar is not None:
            row.update(open_usd=bar['open'], high_usd=str(bar['high']),
                       low_usd=str(bar['low']), close_usd=bar['close'],
                       trade_count=bar['trades'],
                       observed_minutes=bar['minutes'], missing_minutes=60-bar['minutes'],
                       first_observed_minute_utc=iso(bar['first']),
                       last_observed_minute_utc=iso(bar['last']),
                       open_delay_seconds=bar['first']-hour,
                       close_age_seconds=hour+3600-bar['last'],
                       volume_usd_estimate=str(bar['usd_volume']),
                       source=';'.join(sorted(bar['sources'])))
            row[volume_key] = str(bar['volume'])
        return row

    # Preserve decimal prices and additive volumes without binary-float rounding.
    with localcontext() as context:
        context.prec = 60
        for row in rows:
            t = int(row['timestamp_unix'])
            if not start <= t < end:
                raise ValueError(f'Minute outside requested window: {t}')
            validate_bar((t, *[row[k] for k in
                          ('open_usd', 'high_usd', 'low_usd', 'close_usd',
                           volume_key, 'trade_count', 'source')]), last)
            if row['timestamp_utc'] != iso(t):
                raise ValueError(f'Inconsistent minute UTC timestamp: {t}')
            last = t
            while t >= hour + 3600:
                yield result()
                hour += 3600
                bar = None
            volume = Decimal(row[volume_key])
            usd_volume = Decimal(row['close_usd']) * volume
            if bar is None:
                bar = dict(open=row['open_usd'], high=Decimal(row['high_usd']),
                           low=Decimal(row['low_usd']), close=row['close_usd'],
                           volume=volume, usd_volume=usd_volume,
                           trades=int(row['trade_count']), minutes=1,
                           first=t, last=t, sources={row['source']})
            else:
                bar['high'] = max(bar['high'], Decimal(row['high_usd']))
                bar['low'] = min(bar['low'], Decimal(row['low_usd']))
                bar['close'] = row['close_usd']
                bar['volume'] += volume
                bar['usd_volume'] += usd_volume
                bar['trades'] += int(row['trade_count'])
                bar['minutes'] += 1
                bar['last'] = t
                bar['sources'].add(row['source'])
        if last is None:
            raise ValueError('No observed minute candles in requested window')
        while hour < end:
            yield result()
            hour += 3600
            bar = None


def build(output=None, coin='XMR'):
    coin = coin_symbol(coin)
    source = minute_path(coin)
    coverage_path = ROOT / 'data/prices/price_coverage.json'
    coverage = json.loads(coverage_path.read_text(encoding='utf-8'))
    source_hash = sha256(source)
    if source_hash != coverage['coins'][coin]['sha256_csv_gz']:
        raise ValueError('Minute input checksum differs from its coverage manifest')
    if (coverage['requested_start_utc'], coverage['requested_end_exclusive_utc']) != (iso(START), iso(END)):
        raise ValueError('Minute coverage does not match requested hourly bounds')
    output = Path(output) if output is not None else hourly_path(coin)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.resolve() in (source.resolve(), coverage_path.resolve()):
        raise ValueError('Hourly output must not overwrite a source input')
    counts = Counter()
    years = {}
    first = final = None
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                     dir=output.parent, delete=False) as handle:
        temp = Path(handle.name)
        try:
            writer = csv.DictWriter(handle, fieldnames=hourly_columns(coin))
            writer.writeheader()
            with open_text(source) as f:
                reader = csv.DictReader(f)
                if reader.fieldnames != minute_columns(coin):
                    raise ValueError(f'Unexpected {coin} minute schema')
                for row in hourly_rows(reader, coin=coin):
                    writer.writerow(row)
                    n = row['observed_minutes']
                    counts['calendar_hours'] += 1
                    counts['observed_minutes'] += n
                    counts['trade_count'] += row['trade_count']
                    category = 'empty_hours' if n == 0 else 'hours_with_60_observed_minutes' if n == 60 else 'partially_observed_hours'
                    counts[category] += 1
                    yearly = years.setdefault(row['timestamp_utc'][:4], Counter())
                    yearly['calendar_hours'] += 1
                    yearly[category] += 1
                    yearly['observed_minutes'] += n
                    if n:
                        counts['observed_hours'] += 1
                        first = first or row['timestamp_utc']
                        final = row['timestamp_utc']
            if counts['observed_minutes'] != coverage['coins'][coin]['observed_candles']:
                raise ValueError('Hourly aggregation lost or duplicated minute candles')
            if sha256(source) != source_hash:
                raise ValueError('Minute input changed during aggregation')
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    temp.replace(output)
    summary = {
        'pair': f'{coin}/USD', 'venue': 'Kraken spot', 'bar_seconds': 3600,
        'requested_start_utc': iso(START), 'requested_end_exclusive_utc': iso(END),
        'hour_timestamp': 'UTC interval start; the full candle is available only after the hour ends',
        'forward_filled': False, 'cross_exchange_aggregate': False,
        'source_path': source.relative_to(ROOT).as_posix(), 'source_sha256_csv_gz': source_hash,
        'builder_sha256': sha256(Path(__file__)), 'sha256_csv': sha256(output),
        'first_observed_hour_utc': first, 'last_observed_hour_utc': final,
        **{key: counts[key] for key in ('calendar_hours', 'observed_hours', 'empty_hours',
           'partially_observed_hours', 'hours_with_60_observed_minutes', 'observed_minutes', 'trade_count')},
        'volume_method': VOLUME_METHOD,
        'empty_hour_policy': 'blank OHLC and volumes; zero observed minutes and trade count',
        'open_delay_seconds': 'first observed minute start minus hour start',
        'close_age_seconds': 'hour end minus last observed minute start; not the exact last-trade age',
        'yearly': years,
        'limitations': [
            'An unobserved minute may mean no trades or missing source records; it does not prove exchange downtime.',
            '60 observed minutes does not certify complete exchange records or historical bid/ask coverage.',
            'USD volume is an estimate using minute close times base volume, not exact traded dollar notional.',
            'Hourly rows do not increase the independent incident count or establish a predictive advantage.',
        ],
    }
    output.with_suffix('.coverage.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pair', default='XMR', help='Coin or USD pair; defaults to XMR')
    parser.add_argument('--output', type=Path, help='Defaults to data/analysis/<coin>_usd_1h.csv')
    parser.add_argument('--verify', action='store_true', help='Rebuild in isolation and compare CSV and manifest bytes')
    args = parser.parse_args()
    coin = coin_symbol(args.pair)
    output = args.output if args.output is not None else hourly_path(coin)
    if args.verify:
        with tempfile.TemporaryDirectory(prefix='gqh-hourly-verify-') as folder:
            rebuilt = Path(folder) / output.name
            summary = build(rebuilt, coin)
            for a, b in ((rebuilt, output), (rebuilt.with_suffix('.coverage.json'), output.with_suffix('.coverage.json'))):
                if sha256(a) != sha256(b):
                    raise ValueError(f'Hourly rebuild differs: {b}')
        print('Hourly CSV and coverage manifest reproduce byte for byte')
    else:
        summary = build(output, coin)
    print(json.dumps({key: summary[key] for key in
                     ('calendar_hours', 'observed_hours', 'empty_hours', 'observed_minutes', 'sha256_csv')}, indent=2))


if __name__ == '__main__':
    main()
