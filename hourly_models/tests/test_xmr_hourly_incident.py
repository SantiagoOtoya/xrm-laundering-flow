"""Regressions for the explicit combined-price addition to NEWMODELS.MD."""
import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
try:
    import numpy as np
    import train_xmr_hourly_incident as model
except ImportError:
    np = None


@unittest.skipIf(np is None, "NumPy required")
class IncidentModelAdditionTests(unittest.TestCase):
    def setUp(self):
        self.spec = model.DEFAULT_SPEC
        self.start = model.timestamp("2020-01-01T00:00:00Z")

    def frame(self):
        n = 400
        audit = [dict(selected_incident_id="", active_incident_ids=[]) for _ in range(n)]
        return model.Frame(self.start, self.start + n * model.HOUR,
            np.full(n+1, 100.), np.full(n+1, 100.), np.zeros((n, 8)), np.ones(n, dtype=bool),
            np.full(n, np.nan), audit, [])

    def paper(self, frame, signals=(0,), cost=None):
        return model.paper(frame, np.array(signals), np.full(len(signals), .9),
                           self.start, frame.cutoff, self.spec, cost=cost)

    def test_exact_amended_defaults_and_calendar_boundaries(self):
        model.validate_spec(self.spec)
        self.assertEqual(self.spec["xmr_path"], "data/analysis/xmr_usd_btc_combined_1h.csv")
        self.assertEqual(self.spec["fixed_hurdle"], .03)
        self.assertFalse(self.spec["hurdle_selection_repeated"])
        self.assertEqual(model.FEATURES[6], "incident_catalog_loss_log")
        self.assertEqual(self.spec["paper_fill_delay_hours"], 1)
        self.assertEqual(model.inner_bounds(model.timestamp(self.spec["history_start"]),
            model.timestamp(self.spec["initial_development_end"]))[0],
            (model.timestamp("2018-12-15T00:00:00Z"), model.timestamp("2019-08-09T08:00:00Z")))
        for change in ({"xmr_path": "data/analysis/xmr_usd_1h.csv"}, {"paper_fill_delay_hours": 0}, {"fixed_hurdle": .04}):
            with self.assertRaisesRegex(ValueError, "fixed rule"):
                model.validate_spec(dict(self.spec, **change))

    def test_price_review_exclusion_and_reserved_numeric_poison(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"prices.csv"
            with path.open("w", newline="") as handle:
                fields = ["timestamp_unix", "timestamp_utc", "close_usd", "close_age_seconds", "needs_price_review", "close_uses_usd_proxy"]
                writer=csv.DictWriter(handle,fields); writer.writeheader()
                for i, (price, age, flag) in enumerate([(100,300,"0"),(101,60,"1"),(102,301,"0"),("OOS_POISON","OOS_POISON","1")]):
                    writer.writerow(dict(timestamp_unix=self.start+i*model.HOUR, timestamp_utc=model.iso(self.start+i*model.HOUR),
                        close_usd=price, close_age_seconds=age, needs_price_review=flag, close_uses_usd_proxy="1"))
            audit=[]
            values, quality=model.read_closes(path,self.start,self.start+3*model.HOUR,300,audit)
            np.testing.assert_equal(values,[np.nan,100,np.nan,np.nan])
            self.assertEqual(quality[2],"unresolved_price_review")
            self.assertEqual(quality[3],"stale_boundary_price")
            self.assertEqual(len(audit),3)
            self.assertEqual(audit[1]["price_review_disposition"],"unresolved")

    def test_next_close_fill_holds_120_hours_cost_once_and_ignores_future_labels(self):
        frame=self.frame(); frame.xmr[1]=110; frame.xmr[121]=132
        result,trades,unresolved,_=self.paper(frame)
        self.assertEqual(trades[0]["signal_time"], model.iso(self.start))
        self.assertEqual(trades[0]["entry_time"], model.iso(self.start+model.HOUR))
        self.assertEqual(trades[0]["exit_time"], model.iso(self.start+121*model.HOUR))
        self.assertAlmostEqual(result["net_return"], .1*(.2-.02))
        self.assertEqual(unresolved,[])
        stressed,_,_,_=self.paper(frame,cost=.04)
        self.assertAlmostEqual(stressed["net_return"],.1*(.2-.04))

    def test_missing_fill_unfilled_missing_exit_unresolved(self):
        frame=self.frame(); frame.xmr[1]=np.nan
        result,trades,unresolved,_=self.paper(frame)
        self.assertEqual(result["unfilled_orders"],1)
        self.assertEqual(trades,[])
        self.assertEqual(unresolved,[])
        self.assertEqual(result["unfilled_order_ledger"][0]["scheduled_fill"], model.iso(self.start+model.HOUR))
        frame=self.frame(); frame.xmr[121]=np.nan
        result,trades,unresolved,_=self.paper(frame)
        self.assertFalse(result["complete"])
        self.assertEqual(result["unresolved_trades"],1)
        self.assertEqual(trades,[])
        self.assertEqual(unresolved[0]["scheduled_exit"],model.iso(self.start+121*model.HOUR))

    def test_unknown_mark_invalidates_drawdown_and_exit_cannot_trigger_reentry(self):
        frame=self.frame(); frame.xmr[50]=np.nan
        result,trades,_,_=self.paper(frame,(0,121,280))
        self.assertEqual(len(trades),1)
        self.assertIsNone(result["maximum_drawdown"])
        self.assertFalse(result["risk_complete"])

    def catalog_row(self, identity="a", date="2020-01-01", amount="10000000"):
        return dict(incident_id=identity,incident_date=date,reported_loss_usd=amount,
            source_dates='["2019-12-01"]',loss_basis="unverified_catalog_amount",
            detection_available_at_utc="",loss_known_at_detection_usd="",date_precision="day")

    def test_assigned_catalog_date_and_frozen_loss_are_explicit_retrospective_proxies(self):
        windows,audit=model.catalog_windows([self.catalog_row()],self.spec)
        activation=self.start+24*model.HOUR
        self.assertEqual(audit[0]["assumed_activation_utc"],model.iso(activation))
        self.assertEqual(audit[0]["detection_available_at_utc"],"")
        self.assertEqual(model.incident_features(activation-model.HOUR,windows,self.spec)[0],[0.,0.,0.])
        values,context=model.incident_features(activation,windows,self.spec)
        self.assertEqual(values,[1.,math.log1p(10),0.])
        self.assertEqual(context["assigned_incident_date"],"2020-01-01")
        self.assertFalse(context["verified_information_available"])
        self.assertEqual(model.incident_features(activation+23*model.HOUR,windows,self.spec)[0][2],23)
        self.assertEqual(model.incident_features(activation+24*model.HOUR,windows,self.spec)[0],[0.,0.,0.])

    def test_largest_individual_catalog_amount_and_same_incident_age(self):
        rows=[self.catalog_row("a",amount="10000000"),self.catalog_row("b",amount="20000000")]
        windows,_=model.catalog_windows(rows,self.spec)
        values,audit=model.incident_features(self.start+25*model.HOUR,windows,self.spec)
        self.assertEqual(audit["selected_incident_id"],"b")
        self.assertEqual(values,[1.,math.log1p(20),1.])
        rows[1]["reported_loss_usd"]="10000000"
        windows,_=model.catalog_windows(list(reversed(rows)),self.spec)
        self.assertEqual(model.incident_features(self.start+25*model.HOUR,windows,self.spec)[1]["selected_incident_id"],"a")

    def test_structural_errors_fail_instead_of_becoming_ordinary_hours(self):
        for row in [self.catalog_row(identity=""),self.catalog_row(date="2020-02-30"),
                    self.catalog_row(amount="NaN"),self.catalog_row(amount="0"),self.catalog_row(amount="-1")]:
            with self.assertRaisesRegex(ValueError,"structural"):
                model.catalog_windows([row],self.spec)
        with self.assertRaisesRegex(ValueError,"duplicate"):
            model.catalog_windows([self.catalog_row(),self.catalog_row()],self.spec)
        windows,_=model.catalog_windows([self.catalog_row(amount="5000000")],self.spec)
        self.assertFalse(windows)

    def test_missing_historical_coverage_is_not_a_catalog_mode_gate(self):
        values,audit=model.incident_features(self.start,{},self.spec)
        self.assertEqual(values,[0.,0.,0.])
        self.assertEqual(audit["coverage_status"],"assumed_frozen_catalog_population")
        frame=self.frame()
        self.assertEqual(len(model.sample_indices(frame,self.start,frame.cutoff)),281)
        self.assertTrue(frame.eligible.all())

    def test_training_scaling_objective_convergence_and_future_invariance(self):
        frame=self.frame()
        i=np.arange(len(frame.x))
        frame.x[:,0]=np.sin(i/10)
        frame.future_return[:]=np.where(np.sin(i/13)>0,.04,-.02)
        end=self.start+300*model.HOUR
        idx=model.sample_indices(frame,self.start,end)
        fitted=model.fit(frame,idx,.03,.1,end,self.spec)
        self.assertLessEqual(fitted["convergence"]["gradient_linf"],self.spec["optimizer_gradient_tolerance"])
        self.assertEqual(fitted["scaler_scale"][5:], [1.,1.,1.])
        self.assertEqual(fitted["scaler_mean"],frame.x[idx].mean(axis=0).tolist())
        frame.x[300:]=999; frame.future_return[300:]=999
        self.assertEqual(fitted,model.fit(frame,idx,.03,.1,end,self.spec))
        with self.assertRaisesRegex(ValueError,"crossing"):
            model.fit(frame,np.r_[idx,299],.03,.1,end,self.spec)

    def test_boundary_purge_is_by_timestamp_with_exact_equality_allowed(self):
        frame=self.frame(); frame.x[100]=np.nan
        indices=model.sample_indices(frame,self.start,self.start+300*model.HOUR)
        self.assertIn(180,indices)
        self.assertNotIn(181,indices)
        self.assertNotIn(100,indices)


if __name__=="__main__":
    unittest.main()
