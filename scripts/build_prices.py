"""Build Kraken minute files and UTC daily summaries without filling missing data."""
import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
from contextlib import contextmanager
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from price_pairs import (ROOT, RAW, OUT, START, BOUNDARY, END, PAIRS, coin_symbol,
                         trade_dir, archive_path, open_text, minute_path,
                         volume_column, minute_columns, validation_dir)

UTC = dt.timezone.utc
VOLUME_METHOD = 'sum_minute_close_times_base_volume_estimate'


def iso(t):
    return dt.datetime.fromtimestamp(t, UTC).isoformat().replace('+00:00', 'Z')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def aggregate_trade(bars, row):
    price, volume, timestamp = Decimal(row[0]), Decimal(row[1]), Decimal(row[2])
    if not price.is_finite() or not volume.is_finite() or price <= 0 or volume <= 0:
        raise ValueError('Nonpositive or nonfinite trade')
    minute = int(timestamp) // 60 * 60
    if minute not in bars:
        bars[minute] = [price, price, price, price, volume, 1]
    else:
        b = bars[minute]
        b[1], b[2], b[3] = max(b[1], price), min(b[2], price), price
        b[4] += volume
        b[5] += 1


def id_gap_responses(coin, directory=None):
    folder = Path(directory) if directory else validation_dir(coin)
    for path in sorted(folder.glob('trade-id-gap-*.json')):
        if '.meta.' in path.name:
            continue
        meta = json.loads(path.with_suffix('.json.meta.json').read_text())
        if sha256(path) != meta['sha256']:
            raise ValueError(f'ID-gap response checksum mismatch: {path}')
        response = json.loads(path.read_text(), parse_float=Decimal)
        if response.get('error'):
            raise ValueError(f'Invalid ID-gap response: {path}')
        yield path, meta, response['result'][PAIRS[coin][1]]


def source_reference(path, meta):
    return {'file': path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name,
            'sha256': meta['sha256']}


def recover_id_gap(coin, left, right, directory=None):
    """Recover actual omitted records from hashed rechecks, preserving raw pages.

    All missing IDs must be recovered, anchors must agree with the primary page,
    and conflicting or out-of-order records fail instead of changing history.
    """
    expected = range(left[6] + 1, right[6])
    recovered = {}
    sources = []
    for path, meta, rows in id_gap_responses(coin, directory):
        selected = [row for row in rows if row[6] in expected]
        if not selected:
            continue
        anchors = {row[6]: row for row in rows if row[6] in (left[6], right[6])}
        if anchors.get(left[6]) != left or anchors.get(right[6]) != right:
            raise ValueError(f'Recovery anchors conflict or are missing: {path}')
        for row in selected:
            if len(row) != 7:
                raise ValueError('Invalid recovery trade schema')
            if row[6] in recovered and recovered[row[6]] != row:
                raise ValueError(f'Conflicting recovered trade ID {row[6]}')
            recovered[row[6]] = row
        sources.append(source_reference(path, meta))
    if not recovered:
        return [], None
    if len(recovered) != len(expected):
        raise ValueError('Partial recovery of trade-ID gap; additional API evidence required')
    ordered = [recovered[tid] for tid in sorted(recovered)]
    times = [Decimal(row[2]) for row in [left, *ordered, right]]
    if times != sorted(times) or not all(BOUNDARY <= t < END for t in times):
        raise ValueError('Invalid recovery trade timestamps')
    return ordered, {'left_id': left[6], 'right_id': right[6], 'recovered_ids': sorted(recovered),
                     'sources': sources, 'interpretation': 'Actual trades recovered from stored Kraken API rechecks; original pages retained'}


def confirm_source_id_gaps(coin, gaps, directory=None):
    """Require a separately stored Kraken response to reproduce each ID gap.

    An absent identifier is not proof of an omitted trade. Preserve the source
    sequence, report the uncertainty, and never fabricate a replacement record.
    """
    checks = []
    for gap in gaps:
        confirmed = None
        for path, meta, rows in id_gap_responses(coin, directory):
            for left, right in zip(rows, rows[1:]):
                if (left[6], right[6], str(left[2]), str(right[2])) == (
                        gap['left_id'], gap['right_id'], gap['left_timestamp_unix'], gap['right_timestamp_unix']):
                    confirmed = {**gap, 'confirmation_file': path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name,
                                 'confirmation_sha256': meta['sha256'],
                                 'interpretation': 'ID gap reproduced by independent Kraken request; no records invented'}
                    break
            if confirmed:
                break
        if confirmed is None:
            raise ValueError(f'{coin}: unconfirmed missing trade IDs: {gap}')
        checks.append(confirmed)
    return checks


def tail_candles(pair='XMR', directory=None, confirmation_directory=None):
    """Follow and authenticate every saved cursor; deduplicate page overlap by ID.

    API pages must be ordered by time and ID. Only the overlap with the preceding
    page is retained in memory, so BTC does not require holding millions of trades.
    """
    coin = coin_symbol(pair)
    directory = Path(directory) if directory else trade_dir(coin)
    checkpoint = json.loads((directory / 'checkpoint.json').read_text())
    if int(checkpoint.get('start_ns', 0)) != BOUNDARY * 10**9:
        raise ValueError('Wrong trade collection start')
    if int(checkpoint.get('end_exclusive_ns', 0)) != END * 10**9:
        raise ValueError('Wrong trade collection cutoff')
    if int(checkpoint['since']) < END * 10**9:
        raise ValueError(f'{coin} trade collection has not reached the cutoff')
    cursor = BOUNDARY * 10**9
    bars = {}
    pages = duplicates = unique = missing_ids = raw_missing_ids = recovered_count = 0
    previous_page = {}
    last_id = last_time = first_time = last_included_id = last_included_time = None
    id_gaps = []
    recoveries = []
    last_included_row = None
    while cursor < END * 10**9:
        path = directory / f'{cursor}.json'
        if not path.exists():
            path = directory / f'{cursor}.json.gz'
        raw = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
        meta = json.loads((directory / f'{cursor}.meta.json').read_text())
        if hashlib.sha256(raw).hexdigest() != meta['sha256']:
            raise ValueError(f'Trade page checksum mismatch: {path}')
        data = json.loads(raw, parse_float=Decimal)
        if data.get('error'):
            raise ValueError(f'Kraken API error: {path}')
        result = data['result']
        trades = result[PAIRS[coin][1]]
        this_page = {}
        for row in trades:
            if len(row) != 7:
                raise ValueError('Missing trade ID or unexpected trade schema')
            tid, ts = row[6], Decimal(row[2])
            if tid in previous_page or tid in this_page:
                prior = this_page.get(tid, previous_page.get(tid))
                if row != prior:
                    raise ValueError(f'Conflicting trade ID {tid}')
                duplicates += 1
                continue
            if last_id is not None and (tid <= last_id or ts < last_time):
                raise ValueError('Unordered trades or overlap beyond preceding page')
            this_page[tid] = row
            last_id, last_time = tid, ts
            if not BOUNDARY <= ts < END:
                continue
            if first_time is None:
                first_time = ts
            if last_included_id is not None:
                if tid > last_included_id + 1:
                    gap_size = tid - last_included_id - 1
                    raw_missing_ids += gap_size
                    recovered, proof = recover_id_gap(coin, last_included_row, row, confirmation_directory)
                    if proof:
                        recoveries.append(proof)
                        for recovered_row in recovered:
                            aggregate_trade(bars, recovered_row)
                        recovered_count += len(recovered)
                        unique += len(recovered)
                    else:
                        missing_ids += gap_size
                        id_gaps.append({'left_id': last_included_id, 'right_id': tid,
                                        'left_timestamp_unix': str(last_included_time), 'right_timestamp_unix': str(ts),
                                        'missing_trade_ids': gap_size})
            last_included_id = tid
            last_included_time = ts
            last_included_row = row
            unique += 1
            aggregate_trade(bars, row)
        previous_page = this_page
        next_cursor = int(result['last'])
        if next_cursor <= cursor:
            raise ValueError('Non-advancing Kraken cursor')
        cursor = next_cursor
        pages += 1
    if cursor != int(checkpoint['since']) or pages != checkpoint['pages']:
        raise ValueError('Checkpoint does not match complete saved cursor chain')
    checks = confirm_source_id_gaps(coin, id_gaps, confirmation_directory)
    audit = {
        'api_pages': pages, 'unique_trades_in_requested_tail': unique,
        'duplicate_trades_removed': duplicates,
        'missing_trade_ids_between_observed_ids': missing_ids,
        'tail_complete_to_cutoff': True, 'all_page_hashes_verified': True,
        'cursor_chain_verified': True, 'last_api_cursor': str(cursor),
        'first_tail_trade_at_utc': iso(int(first_time)) if first_time is not None else None,
    }
    if checks:
        audit['source_id_gap_checks'] = checks
    if recoveries:
        audit['raw_page_missing_trade_ids'] = raw_missing_ids
        audit['recovered_trades_from_api_rechecks'] = recovered_count
        audit['trade_recoveries'] = recoveries
    return bars, audit


def source_rows(coin, tail):
    with open_text(archive_path(coin)) as f:
        for row in csv.reader(f):
            if len(row) != 7:
                raise ValueError('Unexpected archive schema')
            t = int(row[0])
            if START <= t < BOUNDARY:
                yield t, *row[1:], 'kraken_official_ohlcvt_2026q2'
    for t, bar in sorted(tail.items()):
        yield t, *map(str, bar), 'kraken_public_trades_api'


def validate_bar(row, last=None):
    t, op, hi, lo, cl, vol, n, source = row
    prices = list(map(Decimal, (op, hi, lo, cl)))
    volume = Decimal(vol)
    if t % 60 or not START <= t < END:
        raise ValueError(f'Invalid minute timestamp {t}')
    if last is not None and t <= last:
        raise ValueError(f'Duplicate or unordered candle {t}')
    if not all(x.is_finite() and x > 0 for x in prices + [volume]):
        raise ValueError('Nonpositive or nonfinite observed candle')
    o, h, l, c = prices
    if h < max(o, c, l) or l > min(o, c, h) or int(n) <= 0:
        raise ValueError(f'Bad OHLCVT: {row}')
    if source not in ('kraken_official_ohlcvt_2026q2', 'kraken_public_trades_api'):
        raise ValueError('Unexpected source')
    if (t < BOUNDARY) != (source == 'kraken_official_ohlcvt_2026q2'):
        raise ValueError('Wrong archive/API boundary')


@contextmanager
def deterministic_gzip_text(path):
    with Path(path).open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding='utf-8', newline='') as text:
                yield text


def gzip_writer(path):
    return deterministic_gzip_text(path)


def same_contents(a, b):
    with gzip.open(a, 'rb') as left, gzip.open(b, 'rb') as right:
        while True:
            x, y = left.read(1024 * 1024), right.read(1024 * 1024)
            if x != y:
                return False
            if not x:
                return True


class Coverage:
    def __init__(self, coin):
        self.coin = coin
        self.first = self.last = None
        self.count = 0
        self.gaps = []
        self.sources = Counter()
        self.days = set()
        self.years = defaultdict(lambda: {'observed_minutes': 0, 'trades': 0, volume_column(coin): Decimal(0)})

    def add(self, row):
        t, op, hi, lo, cl, vol, n, source = row
        validate_bar(row, self.last)
        if self.last is not None and t > self.last + 60:
            self.gaps.append((self.last + 60, t, (t - self.last) // 60 - 1))
        if self.first is None:
            self.first = t
        self.last = t
        self.count += 1
        self.sources[source] += 1
        date = iso(t)[:10]
        self.days.add(date)
        year = self.years[date[:4]]
        year['observed_minutes'] += 1
        year['trades'] += int(n)
        year[volume_column(self.coin)] += Decimal(vol)

    def summary(self):
        if self.first is None:
            raise ValueError(f'No observed candles for {self.coin}')
        days = [iso(t)[:10] for t in range(START, END, 86400)]
        missing_days = [day for day in days if day not in self.days]
        span_missing = [day for day in missing_days if iso(self.first)[:10] <= day <= iso(self.last)[:10]]
        all_gaps = list(self.gaps)
        if START < self.first:
            all_gaps.insert(0, (START, self.first, (self.first - START) // 60))
        if self.last + 60 < END:
            all_gaps.append((self.last + 60, END, (END - self.last - 60) // 60))
        longest = max(all_gaps, key=lambda g: g[2], default=None)
        return {
            'pair': self.coin + '/USD', 'kraken_api_pair': PAIRS[self.coin][0],
            'requested_start_utc': iso(START), 'requested_end_exclusive_utc': iso(END),
            'first_observed_minute_utc': iso(self.first), 'last_observed_minute_utc': iso(self.last),
            'observed_candles': self.count, 'source_counts': dict(self.sources),
            'observed_days': len(self.days), 'missing_days': missing_days,
            'missing_days_count': len(missing_days), 'missing_days_inside_observed_span': span_missing,
            'missing_intervals_inside_observed_span': len(self.gaps),
            'missing_minutes_inside_observed_span': sum(g[2] for g in self.gaps),
            'largest_internal_gap_minutes': max((g[2] for g in self.gaps), default=0),
            'missing_minutes_in_requested_window': (END - START) // 60 - self.count,
            'longest_gap_in_requested_window': dict(zip(('start_utc_inclusive', 'end_utc_exclusive', 'missing_minutes'),
                                                       (iso(longest[0]), iso(longest[1]), longest[2]))) if longest else None,
            'leading_missing_minutes': (self.first - START) // 60,
            'trailing_missing_minutes': (END - self.last - 60) // 60,
            'forward_filled': False,
        }


def build_pair(pair):
    coin = coin_symbol(pair)
    OUT.mkdir(parents=True, exist_ok=True)
    tail, audit = tail_candles(coin)
    coverage = Coverage(coin)
    path = minute_path(coin)
    temp = path.with_name(path.name + '.tmp')
    with gzip_writer(temp) as f:
        writer = csv.writer(f)
        writer.writerow(minute_columns(coin))
        for row in source_rows(coin, tail):
            coverage.add(row)
            writer.writerow([row[0], iso(row[0]), *row[1:]])
    # Retain the original XMR compressed bytes when the shared builder reproduces
    # its complete contents, so the existing evidence audit remains reproducible.
    if path.exists() and same_contents(path, temp):
        temp.unlink()
    else:
        temp.replace(path)
    prefix = '' if coin == 'XMR' else coin.lower() + '_'
    gap_path = OUT / (prefix + 'missing_minute_intervals.csv.gz')
    gap_temp = gap_path.with_name(gap_path.name + '.tmp')
    with gzip_writer(gap_temp) as f:
        writer = csv.writer(f)
        writer.writerow(['start_utc_inclusive', 'end_utc_exclusive', 'missing_minutes', 'interpretation'])
        for a, b, n in coverage.gaps:
            writer.writerow([iso(a), iso(b), n, 'no_trade_record; not a verified executable price'])
    if gap_path.exists() and same_contents(gap_path, gap_temp):
        gap_temp.unlink()
    else:
        gap_temp.replace(gap_path)
    for year, row in coverage.years.items():
        y = int(year)
        a = max(START, int(dt.datetime(y, 1, 1, tzinfo=UTC).timestamp()), coverage.first)
        b = min(END, int(dt.datetime(y + 1, 1, 1, tzinfo=UTC).timestamp()), coverage.last + 60)
        row['minutes_in_observed_span'] = (b - a) // 60
        row['unobserved_minutes_in_span'] = row['minutes_in_observed_span'] - row['observed_minutes']
        row[volume_column(coin)] = str(row[volume_column(coin)])
    with (OUT / (prefix + 'coverage_by_year.csv')).open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['year', *next(iter(coverage.years.values()))])
        writer.writeheader()
        writer.writerows(dict(year=y, **r) for y, r in sorted(coverage.years.items()))
    summary = coverage.summary()
    summary.update(sha256_csv_gz=sha256(path), tail_audit=audit,
                   archive_member=PAIRS[coin][0] + '_1.csv')
    return summary


def daily_rows(coin, rows, start=START, end=END):
    """Same close/notional-estimate aggregation for every coin and every source.

    Emit a calendar row even when there are no observed trades; price and volume
    remain empty on those days. Close is the last observed trade-minute close.
    """
    days = {}
    last = None
    for row in rows:
        t = int(row['timestamp_unix'])
        if not start <= t < end or (last is not None and t <= last):
            raise ValueError('Invalid daily input order or bounds')
        last = t
        day = t // 86400 * 86400
        close, volume = Decimal(row['close_usd']), Decimal(row[volume_column(coin)])
        entry = days.setdefault(day, [None, Decimal(0), 0])
        entry[0] = row['close_usd']
        entry[1] += close * volume
        entry[2] += 1
    for day in range(start, end, 86400):
        close, volume, minutes = days.get(day, [None, None, 0])
        yield {'date_utc': iso(day)[:10], 'coin': coin,
               'close_usd': '' if close is None else close,
               'volume_usd_estimate': '' if volume is None else str(volume),
               'observed_minutes': minutes, 'volume_method': VOLUME_METHOD}


def build_daily(coins):
    output = ROOT / 'data/analysis/prices_daily.csv'
    output.parent.mkdir(parents=True, exist_ok=True)
    result = []
    for coin in coins:
        with open_text(minute_path(coin)) as f:
            result.extend(daily_rows(coin, csv.DictReader(f)))
    with output.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['date_utc', 'coin', 'close_usd', 'volume_usd_estimate', 'observed_minutes', 'volume_method'])
        writer.writeheader()
        writer.writerows(sorted(result, key=lambda r: (r['date_utc'], r['coin'])))
    return {'path': output.relative_to(ROOT).as_posix(), 'sha256': sha256(output),
            'rows': len(result), 'volume_method': VOLUME_METHOD,
            'close_method': 'last_observed_minute_close_in_UTC_day',
            'empty_day_policy': 'empty_close_and_volume; zero_observed_minutes'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pair', type=coin_symbol, help='Build one pair; omit to build all four')
    args = parser.parse_args()
    path = OUT / 'price_coverage.json'
    prior = json.loads(path.read_text()) if path.exists() else {}
    pairs = prior.get('coins', {})
    for coin in ([args.pair] if args.pair else PAIRS):
        print('Building', coin, flush=True)
        pairs[coin] = build_pair(coin)
        print(coin, pairs[coin]['observed_candles'], 'candles', flush=True)
    summary = {'venue': 'Kraken spot', 'cross_exchange_aggregate': False, 'bar_seconds': 60,
               'requested_start_utc': iso(START), 'requested_end_exclusive_utc': iso(END),
               'archive_end_exclusive_utc': iso(BOUNDARY), 'forward_filled': False,
               'coins': pairs,
               'limitations': ['Observed trade minutes only; gaps may reflect no trades or missing source records.',
                               'No historical bid/ask or executable spread.',
                               'USD volume is an estimate: sum of minute close times base volume, not actual traded notional.',
                               'Daily close is the last observed minute close, not necessarily a 23:59 trade.']}
    if set(pairs) == set(PAIRS):
        summary['daily'] = build_daily(PAIRS)
    path.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
