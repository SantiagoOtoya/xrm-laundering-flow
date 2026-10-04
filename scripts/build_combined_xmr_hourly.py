"""Compare venues and derive source-labelled hourly XMR USD/BTC close series.

USD proxies use exact matching traded minutes, never carried-forward BTC prices.
Binance zero-trade candles are retained in coverage counts, not fresh prices.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from price_pairs import ROOT, START, END
from build_prices import iso, sha256

DEFAULT_ARCHIVE = ROOT / 'data/raw/binance/Binance_XMRBTC_1m_2017-11_to_2024-02.zip'
OUTPUT = ROOT / 'data/analysis/xmr_usd_btc_combined_1h.csv'
NAMES = ['timestamp_ms', 'open', 'high', 'low', 'close', 'volume_xmr',
         'close_time_ms', 'quote_volume_btc', 'trades', 'taker_xmr', 'taker_btc', 'ignore']


def check_prices(frame, columns):
    prices = frame[columns].to_numpy()
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError('Prices must be finite and positive')
    o, h, l, c = prices.T
    if (l > h).any() or (o < l).any() or (o > h).any() or (c < l).any() or (c > h).any():
        raise ValueError('Inconsistent OHLC')


def grid_index(timestamps):
    t = np.asarray(timestamps, dtype=np.int64)
    if len(t) == 0 or (t % 60).any() or (np.diff(t) <= 0).any() or (t < START).any() or (t >= END).any():
        raise ValueError('Minute timestamps must be ordered, distinct and within the UTC bounds')
    return (t - START) // 60


def binance_timing_mask(frame):
    """Admit only full UTC-minute candles; do not repair irregular source clocks."""
    return ((frame.timestamp_ms % 60000 == 0) &
            (frame.close_time_ms == frame.timestamp_ms + 59999)).to_numpy()


def read_inputs(archive):
    size = (END - START) // 60
    coverage = json.loads((ROOT / 'data/prices/price_coverage.json').read_text())
    inputs = {'binance_archive': sha256(archive), 'price_coverage': sha256(ROOT / 'data/prices/price_coverage.json')}
    closes = {}
    for coin in ('xmr', 'btc'):
        path = ROOT / f'data/prices/{coin}_usd_1m.csv.gz'
        inputs[coin + '_minute'] = sha256(path)
        if inputs[coin + '_minute'] != coverage['coins'][coin.upper()]['sha256_csv_gz']:
            raise ValueError('Kraken source checksum differs from its coverage manifest')
        frame = pd.read_csv(path, usecols=['timestamp_unix', 'open_usd', 'high_usd', 'low_usd', 'close_usd', 'trade_count'])
        check_prices(frame, ['open_usd', 'high_usd', 'low_usd', 'close_usd'])
        if (frame.trade_count <= 0).any() or (frame.trade_count % 1 != 0).any():
            raise ValueError('Kraken retained minutes must contain trades')
        values = np.full(size, np.nan)
        values[grid_index(frame.timestamp_unix)] = frame.close_usd
        closes[coin] = values
        del frame
    b = np.full(size, np.nan)
    candles = np.zeros(size, dtype=bool)
    traded = np.zeros(size, dtype=bool)
    source_present = np.zeros(size,dtype=bool)
    quarantined_hours = np.zeros(size // 60, dtype=np.int32)
    members = []
    native_parts = []
    last = None
    with zipfile.ZipFile(archive) as z:
        if len(set(z.namelist())) != len(z.namelist()):
            raise ValueError('Duplicate archive member names')
        sources = list(csv.DictReader(io.StringIO(z.read('SOURCES.csv').decode())))
        by_name = {r['csv']: r for r in sources}
        selected = sorted(n for n in z.namelist() if re.fullmatch(r'monthly_csv/XMRBTC-1m-\d{4}-\d{2}\.csv', n))
        expected = [f'monthly_csv/XMRBTC-1m-{m}.csv' for m in pd.period_range('2017-11', '2024-02', freq='M')]
        if selected != expected or len(by_name) != len(selected):
            raise ValueError('Expected the 76 declared monthly CSV files')
        for name in selected:
            raw = z.read(name)
            frame = pd.read_csv(io.BytesIO(raw), header=None, names=NAMES)
            if frame.shape[1] != 12 or frame.isna().any().any() or not isinstance(frame.index,pd.RangeIndex):
                raise ValueError('Unexpected Binance schema: ' + name)
            if (frame.timestamp_ms % 1).any() or (frame.close_time_ms % 1).any():
                raise ValueError('Unexpected Binance timestamp unit')
            t = (frame.timestamp_ms // 1000).to_numpy(np.int64)
            timing_ok = binance_timing_mask(frame)
            idx = grid_index(t[timing_ok])
            if (np.diff(frame.timestamp_ms) <= 0).any():
                raise ValueError('Binance rows must be strictly ordered')
            if last is not None and t[0] <= last:
                raise ValueError('Monthly source files overlap')
            last = t[-1]
            month = pd.Period(name[-11:-4], freq='M')
            lo, hi = month.start_time.timestamp(), (month + 1).start_time.timestamp()
            if (t < lo).any() or (t >= hi).any():
                raise ValueError('Candle outside its declared month')
            source_present[(t-START)//60] = True
            quarantined_hours += np.bincount((t[~timing_ok]-START)//3600, minlength=size//60).astype(np.int32)
            check_prices(frame, ['open', 'high', 'low', 'close'])
            for key in ('volume_xmr', 'quote_volume_btc', 'trades', 'taker_xmr', 'taker_btc'):
                if not np.isfinite(frame[key]).all() or (frame[key] < 0).any():
                    raise ValueError('Invalid Binance volume/trade count')
            if (frame.trades % 1 != 0).any() or ((frame.trades == 0) != (frame.volume_xmr == 0)).any():
                raise ValueError('Inconsistent Binance zero-trade candle')
            active = (frame.trades > 0).to_numpy()
            source = by_name[name.split('/')[-1]]
            if (len(frame), int((~active).sum())) != tuple(int(source[k]) for k in ('rows','zero_trade_minutes')):
                raise ValueError('Provided source counts do not reconcile: ' + name)
            expected_url = 'https://data.binance.vision/data/spot/monthly/klines/XMRBTC/1m/' + name.split('/')[-1].replace('.csv','.zip')
            if source['source_zip_url'] != expected_url:
                raise ValueError('Unexpected source URL')
            members.append(dict(source, csv_sha256=hashlib.sha256(raw).hexdigest(),
                                quarantined_timing_rows=int((~timing_ok).sum()),
                                quarantined_traded_rows=int((active&~timing_ok).sum()),
                                off_grid_start_rows=int((frame.timestamp_ms%60000!=0).sum()),
                                nonstandard_close_rows=int((frame.close_time_ms!=frame.timestamp_ms+59999).sum()),
                                first_minute_utc=iso(int(t[0])), last_minute_utc=iso(int(t[-1]))))
            candles[idx] = True
            traded[idx] = active[timing_ok]
            fresh_mask=active&timing_ok
            b[idx[active[timing_ok]]] = frame.close.to_numpy()[fresh_mask]
            fresh = frame.loc[fresh_mask].copy()
            fresh['hour'] = (t[fresh_mask] // 3600) * 3600
            native_parts.append(fresh.groupby('hour').agg(
                binance_open_xmr_btc=('open','first'), binance_high_xmr_btc=('high','max'),
                binance_low_xmr_btc=('low','min'), binance_close_xmr_btc=('close','last'),
                binance_volume_xmr=('volume_xmr','sum'), binance_quote_volume_btc=('quote_volume_btc','sum'),
                binance_trade_count=('trades','sum')))
    coverage_window=np.zeros(size,dtype=bool)
    first=int(pd.Timestamp(members[0]['first_minute_utc']).timestamp())
    final=int(pd.Timestamp(members[-1]['last_minute_utc']).timestamp())
    coverage_window[(first-START)//60:(final-START)//60+1]=True
    closes.update(binance=b, binance_candles=candles, binance_traded=traded,
                  binance_source_present=source_present,binance_archive_window=coverage_window,
                  binance_quarantined_hour_counts=quarantined_hours)
    return closes, pd.concat(native_parts).sort_index(), members, inputs


def stats(values):
    values = np.asarray(values)
    values = values[np.isfinite(values)]
    if not len(values):
        return {'minutes': 0}
    absolute = np.abs(values)
    return dict(minutes=len(values), median_signed_difference_pct=float(np.median(values)),
                median_absolute_difference_pct=float(np.median(absolute)),
                p95_absolute_difference_pct=float(np.quantile(absolute, .95)),
                p99_absolute_difference_pct=float(np.quantile(absolute, .99)),
                max_absolute_difference_pct=float(absolute.max()),
                share_over_1pct=float(np.mean(absolute > 1)), share_over_5pct=float(np.mean(absolute > 5)))


def conversions(k, btc, b):
    proxy = b * btc
    combined = np.where(np.isfinite(k), k, proxy)
    implied = k / btc
    ratio = np.where(np.isfinite(b), b, implied)
    return proxy, combined, implied, ratio


def hourly_close(values, start=START):
    """Return last fresh minute close and its exact minute key, including empty hours."""
    values = np.asarray(values)
    if len(values) % 60 or start % 3600:
        raise ValueError('Hourly conversion requires complete UTC-hour bounds')
    grid = values.reshape(-1,60)
    valid = np.isfinite(grid)
    last = np.where(valid,np.arange(60),-1).max(axis=1)
    index = np.arange(len(grid))*60 + np.maximum(last,0)
    close = np.where(last>=0,values[index],np.nan)
    minute = np.where(last>=0,start+index*60,np.nan)
    return close, minute, valid.sum(axis=1), index


def utc_column(seconds):
    return pd.to_datetime(seconds,unit='s',utc=True).strftime('%Y-%m-%dT%H:%M:%SZ').fillna('')


def hourly_dataset(closes, native, start=START):
    k, btc, b = (closes[key] for key in ('xmr','btc','binance'))
    proxy, combined, implied, ratio = conversions(k,btc,b)
    count = lambda mask: np.asarray(mask).reshape(-1,60).sum(axis=1)
    c, c_at, c_n, c_idx = hourly_close(combined,start)
    r, r_at, r_n, r_idx = hourly_close(ratio,start)
    p, p_at, p_n, _ = hourly_close(proxy,start)
    k_hour, _, k_n, _ = hourly_close(k,start)
    btc_hour, _, _, _ = hourly_close(btc,start)
    hours = np.arange(start,start+len(c)*3600,3600,dtype=np.int64)
    c_source = np.where(np.isfinite(c),np.where(np.isfinite(k[c_idx]),'kraken_xmr_usd',
                        'binance_xmr_btc_times_kraken_btc_usd'),'')
    r_source = np.where(np.isfinite(r),np.where(np.isfinite(b[r_idx]),'binance_xmr_btc',
                        'kraken_xmr_usd_divided_by_kraken_btc_usd'),'')
    basis = 100*(proxy/k-1)
    common = np.isfinite(basis)
    max_basis = np.where(common.reshape(-1,60),np.abs(basis).reshape(-1,60),-1).max(axis=1)
    max_basis = np.where(max_basis>=0,max_basis,np.nan)
    shared_latest,_,_,_ = hourly_close(basis,start)
    # A diagnostic threshold, never an instruction to delete observations.
    large = count(common & (np.abs(basis)>5))
    end = hours+3600
    frame = pd.DataFrame(dict(
        timestamp_unix=hours,timestamp_utc=utc_column(hours),available_after_utc=utc_column(end),
        close_usd=c,close_usd_source=c_source,close_usd_minute_utc=utc_column(c_at),
        close_age_seconds=end-c_at,observed_minutes=c_n,missing_minutes=60-c_n,
        kraken_minutes=k_n,binance_fill_minutes=count(~np.isfinite(k)&np.isfinite(proxy)),
        close_uses_usd_proxy=(c_source=='binance_xmr_btc_times_kraken_btc_usd').astype(int),
        close_source_changed_from_prior_hour=np.r_[False,(c_source[1:]!=c_source[:-1])&(c_source[1:]!='')&(c_source[:-1]!='')].astype(int),
        close_xmr_btc=r,close_xmr_btc_source=r_source,close_xmr_btc_minute_utc=utc_column(r_at),
        ratio_close_age_seconds=end-r_at,ratio_observed_minutes=r_n,ratio_missing_minutes=60-r_n,
        ratio_binance_minutes=count(np.isfinite(b)),ratio_kraken_fill_minutes=count(~np.isfinite(b)&np.isfinite(implied)),
        btc_usd_hourly_close=btc_hour,btc_usd_at_selected_usd_close=np.where(np.isfinite(c),btc[c_idx],np.nan),
        xmr_btc_at_selected_usd_close=np.where(np.isfinite(c),c/btc[c_idx],np.nan),
        kraken_close_usd=k_hour,binance_synthetic_close_usd=p,binance_synthetic_close_minute_utc=utc_column(p_at),
        binance_convertible_traded_minutes=p_n,
        binance_traded_minutes_without_btc_rate=count(np.isfinite(b)&~np.isfinite(btc)),
        binance_valid_candle_minutes=count(closes['binance_candles']),
        binance_zero_trade_candle_minutes=count(closes['binance_candles']&~closes['binance_traded']),
        binance_source_absent_minutes=count(closes['binance_archive_window']&~closes['binance_source_present']),
        binance_source_only_irregular_minutes=count(closes['binance_source_present']&~closes['binance_candles']),
        binance_outside_archive_minutes=count(~closes['binance_archive_window']),
        binance_quarantined_timing_rows=closes['binance_quarantined_hour_counts'],
        shared_traded_minutes=count(common),latest_shared_minute_difference_pct=shared_latest,
        max_shared_minute_absolute_difference_pct=max_basis,
        shared_minutes_difference_over_5pct=large,needs_price_review=(large>0).astype(int),
        selected_usd_close_shared_difference_pct=np.where(np.isfinite(c),basis[c_idx],np.nan),
    ),index=hours)
    frame=frame.join(native.reindex(hours))
    return frame


def analyze(closes, members):
    k, btc, b = (closes[key] for key in ('xmr','btc','binance'))
    proxy, combined, implied, ratio = conversions(k, btc, b)
    basis = 100 * (proxy / k - 1)
    ticks = np.arange(START, END, 60, dtype=np.int64)
    hourly = lambda values: np.isfinite(values).reshape(-1,60).sum(axis=1)
    k_n, c_n, r_n = (hourly(v) for v in (k,combined,ratio))
    yearly = {}
    for year in range(2017,2027):
        lo = int(pd.Timestamp(f'{year}-01-01',tz='UTC').timestamp())
        hi = int(pd.Timestamp(f'{year+1}-01-01',tz='UTC').timestamp())
        mask = (ticks >= lo) & (ticks < hi)
        hmask = mask[::60]
        yearly[str(year)] = dict(calendar_hours=int(hmask.sum()),
            kraken_empty_hours=int((k_n[hmask]==0).sum()), combined_empty_hours=int((c_n[hmask]==0).sum()),
            kraken_fresh_minutes=int(np.isfinite(k[mask]).sum()), combined_fresh_minutes=int(np.isfinite(combined[mask]).sum()),
            basis=stats(basis[mask]))
    finite = np.flatnonzero(np.isfinite(basis))
    top = finite[np.argsort(np.abs(basis[finite]))[-10:][::-1]]
    monthly = {}
    for period in pd.period_range('2017-11','2024-02',freq='M'):
        lo = int(period.start_time.timestamp()); hi = int((period+1).start_time.timestamp())
        values = basis[max(0,(lo-START)//60):min(len(basis),(hi-START)//60)]
        monthly[str(period)] = stats(values)
    return dict(calendar_hours=len(k_n), kraken_observed_hours=int((k_n>0).sum()),
        kraken_empty_hours=int((k_n==0).sum()), combined_observed_hours=int((c_n>0).sum()),
        combined_empty_hours=int((c_n==0).sum()), newly_observed_hours=int(((k_n==0)&(c_n>0)).sum()),
        kraken_fresh_minutes=int(np.isfinite(k).sum()), combined_fresh_minutes=int(np.isfinite(combined).sum()),
        binance_fill_minutes=int((~np.isfinite(k)&np.isfinite(proxy)).sum()),
        binance_candle_rows=sum(int(m['rows']) for m in members),
        binance_validly_timed_candle_rows=int(closes['binance_candles'].sum()),
        binance_zero_trade_minutes=sum(int(m['zero_trade_minutes']) for m in members),
        binance_quarantined_timing_rows=sum(m['quarantined_timing_rows'] for m in members),
        binance_missing_source_timestamps_within_archive_window=int((closes['binance_archive_window']&~closes['binance_source_present']).sum()),
        binance_validly_timed_zero_trade_minutes=int((closes['binance_candles']&~closes['binance_traded']).sum()),
        binance_fresh_minutes=int(np.isfinite(b).sum()),
        binance_fresh_minutes_without_same_minute_btc_usd=int((np.isfinite(b)&~np.isfinite(btc)).sum()),
        ratio_observed_hours=int((r_n>0).sum()), ratio_empty_hours=int((r_n==0).sum()),
        ratio_fresh_minutes=int(np.isfinite(ratio).sum()),
        binance_first_candle_utc=members[0]['first_minute_utc'], binance_last_candle_utc=members[-1]['last_minute_utc'],
        combined_hours_with_60_fresh_minutes=int((c_n==60).sum()),
        kraken_hours_with_60_fresh_minutes=int((k_n==60).sum()),
        basis=stats(basis), yearly=yearly, monthly_basis=monthly,
        largest_aligned_discrepancies=[dict(timestamp_utc=iso(int(ticks[i])), kraken_xmr_usd=float(k[i]),
            binance_xmr_btc=float(b[i]), kraken_btc_usd=float(btc[i]), binance_usd_proxy=float(proxy[i]),
            relative_difference_pct=float(basis[i])) for i in top])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,default=DEFAULT_ARCHIVE)
    parser.add_argument('--analyze-only',action='store_true')
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args()
    closes,native,members,inputs=read_inputs(args.archive)
    summary=analyze(closes,members)
    if args.analyze_only:
        print(json.dumps({k:v for k,v in summary.items() if k not in ('yearly','monthly_basis','largest_aligned_discrepancies')},indent=2))
        print(json.dumps({'yearly':summary['yearly'],'feb_2024':summary['monthly_basis']['2024-02'],'largest_differences':summary['largest_aligned_discrepancies'][:3]},indent=2))
    else:
        verification_path=ROOT/'data/raw/binance/official_verification.json'
        verification=json.loads(verification_path.read_text())
        verified={r['csv']:r for r in verification['monthly']}
        if verification['supplied_archive_sha256']!=inputs['binance_archive'] or verification['verified_files']!=76:
            raise ValueError('Official verification must match the supplied archive')
        for member in members:
            proof=verified[member['csv']]
            if not proof['exact_csv_match'] or proof['official_csv_sha256']!=member['csv_sha256']:
                raise ValueError('Official member verification mismatch')
        inputs['official_verification']=sha256(verification_path)
        frame=hourly_dataset(closes,native)
        if len(frame)!=summary['calendar_hours'] or int(frame.observed_minutes.sum())!=summary['combined_fresh_minutes']:
            raise ValueError('Hourly aggregation does not reconcile')
        for path,key in ((args.archive,'binance_archive'),(ROOT/'data/prices/xmr_usd_1m.csv.gz','xmr_minute'),
                         (ROOT/'data/prices/btc_usd_1m.csv.gz','btc_minute')):
            if sha256(path)!=inputs[key]:
                raise ValueError('Input changed during reconstruction')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        forbidden=[args.archive,ROOT/'data/analysis/xmr_usd_1h.csv',ROOT/'data/analysis/btc_usd_1h.csv',
                   ROOT/'data/prices/xmr_usd_1m.csv.gz',ROOT/'data/prices/btc_usd_1m.csv.gz']
        if args.output.resolve() in [p.resolve() for p in forbidden]:
            raise ValueError('Combined output cannot overwrite original inputs or hourly series')
        temporary=args.output.with_name(args.output.name+'.tmp')
        frame.to_csv(temporary,index=False,float_format='%.17g',lineterminator='\r\n',na_rep='')
        temporary.replace(args.output)
        summary.update(version='xmr_combined_hourly_v1',requested_start_utc=iso(START),
            requested_end_exclusive_utc=iso(END),input_sha256=inputs,builder_sha256=sha256(Path(__file__)),
            sha256_csv=sha256(args.output),forward_filled=False,
            price_type='hourly last fresh minute close; USD includes an explicitly labelled cross-venue proxy',
            source_policy_usd='Kraken at each traded minute; Binance XMR/BTC times same-minute Kraken BTC/USD for missing Kraken XMR minutes',
            source_policy_xmr_btc='Binance at each valid traded minute; same-minute Kraken XMR/USD divided by BTC/USD otherwise',
            close_age_seconds='Hour end minus the selected minute start; an upper bound on within-minute last trade age',
            high_low_policy='No synthetic USD OHLC; native Binance XMR/BTC OHLC is retained in its own columns',
            numeric_policy='IEEE-754 float64, exported with 17 significant digits; original sources preserved',
            needs_price_review_threshold_pct=5,hours_with_large_cross_venue_difference=int(frame.needs_price_review.sum()),
            usd_close_source_switches=int(frame.close_source_changed_from_prior_hour.sum()),
            usd_hours_close_uses_proxy=int(frame.close_uses_usd_proxy.sum()),
            binance_monthly_members=members)
        args.output.with_suffix('.coverage.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps({k:v for k,v in summary.items() if k not in ('yearly','monthly_basis','largest_aligned_discrepancies','binance_monthly_members')},indent=2))


if __name__=='__main__':
    main()
