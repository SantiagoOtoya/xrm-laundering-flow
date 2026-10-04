"""Cross-unit conversion, fresh observations and source-clock boundaries."""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from build_combined_xmr_hourly import binance_timing_mask,conversions,hourly_close,hourly_dataset


class CombinedXmrHourlyTests(unittest.TestCase):
    def test_timestamp_anomalies_are_quarantined_without_relabelling(self):
        frame=pd.DataFrame({'timestamp_ms':[0,60000,120022,180000,240000],
                            'close_time_ms':[59999,119999,180021,179999,299000]})
        self.assertEqual(binance_timing_mask(frame).tolist(),[True,True,False,False,False])
        self.assertEqual(frame.timestamp_ms[2],120022)

    def test_conversion_requires_btc_in_the_same_minute(self):
        k=np.array([np.nan,np.nan,150.])
        btc=np.array([10000.,np.nan,20000.])
        b=np.array([.015,.015,.008])
        proxy,combined,implied,ratio=conversions(k,btc,b)
        self.assertEqual(proxy[0],150)
        self.assertTrue(np.isnan(proxy[1]))
        self.assertTrue(np.isnan(combined[1]))
        self.assertEqual(combined[2],150)
        self.assertEqual(implied[2],.0075)
        self.assertEqual(ratio[1],.015)

    def test_hourly_close_uses_last_fresh_observation_before_the_boundary(self):
        values=np.full(180,np.nan)
        values[0]=100;values[59]=101;values[60]=102
        close,at,count,_=hourly_close(values,start=0)
        np.testing.assert_equal(close,[101,102,np.nan])
        np.testing.assert_equal(at,[3540,3600,np.nan])
        np.testing.assert_equal(count,[2,1,0])
        with self.assertRaises(ValueError):hourly_close(values[:-1],start=0)

    def inputs(self):
        empty=lambda:np.full(120,np.nan)
        k,btc,b=empty(),empty(),empty()
        k[58]=150;btc[58]=10000;btc[59]=11000;b[58]=.015;b[59]=.016
        present=np.zeros(120,dtype=bool);present[57:60]=True
        traded=np.isfinite(b)
        return dict(xmr=k,btc=btc,binance=b,binance_candles=present,
                    binance_traded=traded,binance_source_present=present,
                    binance_archive_window=np.ones(120,dtype=bool),
                    binance_quarantined_hour_counts=np.zeros(2,dtype=int))

    def test_latest_gap_fill_has_explicit_provenance_and_consistent_units(self):
        frame=hourly_dataset(self.inputs(),pd.DataFrame(index=pd.Index([],name='hour')),start=0)
        row=frame.iloc[0]
        self.assertEqual(row.close_usd,176)
        self.assertEqual(row.close_usd_source,'binance_xmr_btc_times_kraken_btc_usd')
        self.assertEqual(row.close_usd_minute_utc,'1970-01-01T00:59:00Z')
        self.assertEqual(row.close_xmr_btc,.016)
        self.assertEqual(row.btc_usd_at_selected_usd_close,11000)
        self.assertEqual(row.observed_minutes,2)
        self.assertEqual(row.kraken_minutes,1)
        self.assertEqual(row.binance_fill_minutes,1)

    def test_zero_trade_candles_and_empty_hours_do_not_create_fresh_prices(self):
        frame=hourly_dataset(self.inputs(),pd.DataFrame(index=pd.Index([],name='hour')),start=0)
        self.assertEqual(frame.iloc[0].binance_zero_trade_candle_minutes,1)
        self.assertEqual(frame.iloc[0].binance_source_absent_minutes,57)
        self.assertTrue(np.isnan(frame.iloc[1].close_usd))
        self.assertEqual(frame.iloc[1].close_usd_source,'')
        self.assertEqual(frame.iloc[1].observed_minutes,0)
        self.assertEqual(frame.iloc[1].missing_minutes,60)

    def test_severe_price_difference_is_flagged_but_not_silently_removed(self):
        inputs=self.inputs();inputs['xmr'][58]=.01
        frame=hourly_dataset(inputs,pd.DataFrame(index=pd.Index([],name='hour')),start=0)
        row=frame.iloc[0]
        self.assertEqual(row.kraken_close_usd,.01)
        self.assertEqual(row.needs_price_review,1)
        self.assertEqual(row.shared_minutes_difference_over_5pct,1)
        self.assertEqual(row.close_usd,176)


if __name__=='__main__':unittest.main()
