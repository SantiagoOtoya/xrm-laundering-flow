"""Hourly boundaries, sparse OHLC and missing-data semantics using synthetic candles."""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_hourly_prices import hourly_rows, hourly_columns, hourly_path
from build_prices import iso
from price_pairs import START, BOUNDARY


def minute(t, o='10', h='12', l='9', c='11', v='2', n='3'):
    return dict(timestamp_unix=str(t), timestamp_utc=iso(t), open_usd=o,
                high_usd=h, low_usd=l, close_usd=c, volume_xmr=v, trade_count=n,
                source='kraken_official_ohlcvt_2026q2' if t < BOUNDARY else 'kraken_public_trades_api')


class HourlyPriceTests(unittest.TestCase):
    def test_sparse_ohlc_uses_first_open_last_close_and_all_extrema(self):
        rows = [minute(START+60), minute(START+1800, '8', '15', '7', '14', '0.3', '4'),
                minute(START+3540, '13', '14', '12', '13', '1.7', '2')]
        hour = list(hourly_rows(rows, START, START+3600))[0]
        self.assertEqual([hour[k] for k in ('open_usd', 'high_usd', 'low_usd', 'close_usd')], ['10', '15', '7', '13'])
        self.assertEqual(hour['volume_xmr'], '4.0')
        self.assertEqual(hour['volume_usd_estimate'], '48.3')
        self.assertEqual(hour['trade_count'], 9)
        self.assertEqual(hour['observed_minutes'], 3)
        self.assertEqual(hour['missing_minutes'], 57)
        self.assertEqual(hour['open_delay_seconds'], 60)
        self.assertEqual(hour['close_age_seconds'], 60)

    def test_empty_edges_and_internal_hour_have_blank_prices_and_volumes(self):
        rows = [minute(START+3600), minute(START+3*3600)]
        result = list(hourly_rows(rows, START, START+5*3600))
        self.assertEqual(len(result), 5)
        for index in (0, 2, 4):
            row = result[index]
            for key in ('open_usd', 'high_usd', 'low_usd', 'close_usd', 'volume_xmr',
                        'volume_usd_estimate', 'source', 'open_delay_seconds', 'close_age_seconds'):
                self.assertEqual(row[key], '')
            self.assertEqual(row['trade_count'], 0)
            self.assertEqual(row['observed_minutes'], 0)
            self.assertEqual(row['missing_minutes'], 60)

    def test_midnight_and_archive_api_boundary_are_separate_hours(self):
        result = list(hourly_rows([minute(BOUNDARY-60), minute(BOUNDARY)], BOUNDARY-3600, BOUNDARY+3600))
        self.assertEqual([r['timestamp_unix'] for r in result], [BOUNDARY-3600, BOUNDARY])
        self.assertEqual(result[0]['source'], 'kraken_official_ohlcvt_2026q2')
        self.assertEqual(result[1]['source'], 'kraken_public_trades_api')
        self.assertEqual(result[1]['open_delay_seconds'], 0)
        self.assertEqual(result[1]['close_age_seconds'], 3600)

    def test_every_observed_minute_is_counted_once_in_a_full_hour(self):
        result = list(hourly_rows([minute(START+60*n) for n in range(60)], START, START+3600))
        self.assertEqual(result[0]['observed_minutes'], 60)
        self.assertEqual(result[0]['missing_minutes'], 0)
        self.assertEqual(result[0]['volume_xmr'], '120')
        self.assertEqual(result[0]['trade_count'], 180)

    def test_btc_uses_btc_volume_and_preserves_sparse_and_empty_hours(self):
        source = minute(START+60, v='0.00000001234567890123456789')
        source['volume_btc'] = source.pop('volume_xmr')
        rows = list(hourly_rows([source], START, START+7200, coin='BTC/USD'))
        self.assertEqual(Decimal(rows[0]['volume_btc']), Decimal(source['volume_btc']))
        self.assertEqual(Decimal(rows[0]['volume_usd_estimate']),
                         Decimal(source['volume_btc']) * Decimal(source['close_usd']))
        self.assertEqual(rows[0]['observed_minutes'], 1)
        self.assertEqual(rows[1]['volume_btc'], '')
        self.assertEqual(rows[1]['observed_minutes'], 0)
        self.assertNotIn('volume_xmr', rows[0])
        self.assertEqual(list(rows[0]), hourly_columns('BTC'))
        self.assertEqual(hourly_path('XBTUSD').name, 'btc_usd_1h.csv')

    def test_bad_minute_order_bounds_and_timestamps_fail(self):
        invalid = [[minute(START), minute(START)], [minute(START+60), minute(START)],
                   [minute(START+3600)], [minute(START+1)], [minute(START, h='8')],
                   [dict(minute(START), timestamp_utc=iso(START+60))], []]
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                list(hourly_rows(rows, START, START+3600))
        with self.assertRaises(ValueError):
            list(hourly_rows([minute(START)], START+60, START+3600))


if __name__ == '__main__':
    unittest.main()
