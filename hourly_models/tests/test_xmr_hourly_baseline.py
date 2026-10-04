"""Leakage, target clocks, missing-data execution and chronological baseline checks."""
import copy
import csv
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
try:
    import numpy as np
    import train_xmr_hourly_baseline as baseline
except ImportError:
    np = None


@unittest.skipIf(np is None, "Install requirements-analysis.txt")
class HourlyBaselineTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((ROOT / baseline.CONFIG).read_text())
        self.start = baseline.timestamp("2020-01-01T00:00:00Z")

    def frame(self, hours=1800):
        i = np.arange(hours + 1)
        xmr = 100 * np.exp(.08 * np.sin(i / 80) + .02 * np.sin(i / 11) + .00003 * i)
        btc = 10000 * np.exp(.05 * np.sin(i / 130) + .00001 * i)
        return baseline.build_frame(xmr, btc, self.start, self.start + hours * baseline.HOUR)

    def write_prices(self, path, hours, prices=None, age="60", poison_from=None, review_at=None):
        fields = ["timestamp_unix", "timestamp_utc", "close_usd", "close_age_seconds"]
        if review_at is not None:
            fields += ["available_after_utc", "close_usd_source", "close_usd_minute_utc",
                       "needs_price_review", "close_source_changed_from_prior_hour",
                       "max_shared_minute_absolute_difference_pct", "selected_usd_close_shared_difference_pct"]
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fields)
            writer.writeheader()
            for i in range(hours):
                t = self.start + i * baseline.HOUR
                close = prices[i + 1] if prices is not None else 100 + i
                if poison_from is not None and i >= poison_from:
                    close = "OOS_POISON"
                row = dict(timestamp_unix=t, timestamp_utc=baseline.iso(t), close_usd=close, close_age_seconds=age)
                if review_at is not None:
                    row.update(available_after_utc=baseline.iso(t + baseline.HOUR), close_usd_source="kraken_xmr_usd",
                        close_usd_minute_utc=baseline.iso(t + 59*60), needs_price_review=int(i == review_at),
                        close_source_changed_from_prior_hour=0,
                        max_shared_minute_absolute_difference_pct="6" if i == review_at else "1",
                        selected_usd_close_shared_difference_pct="6" if i == review_at else "1")
                writer.writerow(row)

    def test_review_unresolved_prices_excluded_without_overwriting_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = copy.deepcopy(self.spec)
            for key in ("xmr_coverage_path", "btc_coverage_path", "xmr_validation_path", "btc_validation_path"):
                spec.pop(key, None)
            for key in ("xmr_path", "btc_path"):
                path = root / spec[key]; path.parent.mkdir(parents=True, exist_ok=True)
                self.write_prices(path, 20, review_at=10 if key == "xmr_path" else None)
            before = (root / spec["xmr_path"]).read_bytes()
            report = baseline.prepare_review(spec, root)
            self.assertEqual(report["disposition_counts"], {"unresolved":1})
            excluded, rows = baseline.excluded_review_prices(spec, root)
            self.assertEqual(excluded, {self.start + 10 * baseline.HOUR})
            closes = baseline.read_closes(root / spec["xmr_path"], self.start,
                self.start + 20 * baseline.HOUR, 300, excluded)
            self.assertTrue(np.isnan(closes[11])); self.assertTrue(np.isfinite(closes[10]))
            self.assertEqual((root / spec["xmr_path"]).read_bytes(), before)
            report["rows"] = []
            (root / spec["price_review_path"]).write_bytes(baseline.json_bytes(report))
            with self.assertRaisesRegex(ValueError, "explicit dispositions"):
                baseline.excluded_review_prices(spec, root)

    def test_source_validation_checksum_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = dict(xmr_path="xmr.csv", btc_path="btc.csv", xmr_coverage_path="coverage.json")
            for source in ("xmr.csv", "btc.csv"):
                self.write_prices(root / source, 3)
            (root / "coverage.json").write_text(json.dumps({"sha256_csv":"wrong"}))
            with self.assertRaisesRegex(ValueError, "validation manifest"):
                baseline.verify_price_sources(spec, root)

    def test_reserved_values_not_parsed_and_prior_boundary_is_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "prices.csv"
            self.write_prices(path, 6, poison_from=3)
            prices = baseline.read_closes(path, self.start, self.start + 3 * baseline.HOUR, 300)
            np.testing.assert_equal(prices, [np.nan, 100, 101, 102])

    def test_bad_order_or_non_hour_timestamp_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "prices.csv"
            self.write_prices(path, 3)
            with path.open() as handle:
                rows = list(csv.DictReader(handle))
            rows[1]["timestamp_unix"] = rows[0]["timestamp_unix"]
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, list(rows[0])); writer.writeheader(); writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "unique chronological"):
                baseline.read_closes(path, self.start, self.start + 3 * baseline.HOUR, 300)

    def test_freshness_limit_does_not_fill_missing_or_stale_prices(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "prices.csv"
            self.write_prices(path, 3, age="301")
            self.assertTrue(np.isnan(baseline.read_closes(path, self.start, self.start + 3 * baseline.HOUR, 300)).all())

    def test_disjoint_return_features_sum_to_seven_day_return(self):
        frame = self.frame()
        for i in (168, 240, 400):
            self.assertAlmostEqual(frame.x[i, 0] + frame.x[i, 1], np.log(frame.xmr[i] / frame.xmr[i-168]))
            self.assertAlmostEqual(frame.x[i, 2] + frame.x[i, 3], np.log(frame.btc[i] / frame.btc[i-168]))
            expected = np.sqrt(np.square(np.diff(np.log(frame.xmr[i-24:i+1]))).sum())
            self.assertAlmostEqual(frame.x[i, 4], expected)

    def test_no_future_price_or_btc_target_used_by_features(self):
        frame = self.frame()
        xmr, btc = frame.xmr.copy(), frame.btc.copy()
        xmr[401:] *= 2; btc[401:] *= 100
        changed = baseline.build_frame(xmr, btc, frame.start, frame.cutoff)
        np.testing.assert_array_equal(changed.x[400], frame.x[400])
        btc_only = baseline.build_frame(frame.xmr, btc, frame.start, frame.cutoff)
        np.testing.assert_array_equal(btc_only.future_return, frame.future_return)

    def test_missing_internal_volatility_boundary_excludes_row(self):
        frame = self.frame()
        xmr = frame.xmr.copy(); xmr[390] = np.nan
        changed = baseline.build_frame(xmr, frame.btc, frame.start, frame.cutoff)
        self.assertFalse(changed.eligible[400])
        self.assertTrue(changed.eligible[415])

    def test_timestamp_purge_allows_exact_end_but_not_crossing(self):
        frame = self.frame()
        end = frame.start + 500 * baseline.HOUR
        indices = baseline.sample_indices(frame, frame.start, end)
        self.assertIn(380, indices); self.assertNotIn(381, indices)
        validation = baseline.sample_indices(frame, end, frame.start + 700 * baseline.HOUR)
        self.assertEqual(validation[0], 500); self.assertEqual(validation[-1], 580)
        frame.x[375] = np.nan
        self.assertNotIn(375, baseline.sample_indices(frame, frame.start, end))
        self.assertIn(380, baseline.sample_indices(frame, frame.start, end))

    def test_fit_scaler_and_regularization_use_training_only(self):
        frame = self.frame()
        end = frame.start + 1000 * baseline.HOUR
        training = baseline.sample_indices(frame, frame.start, end)
        model = baseline.fit(frame, training, .03, .1, end, self.spec)
        np.testing.assert_array_equal(model["scaler_mean"], frame.x[training].mean(axis=0))
        np.testing.assert_array_equal(model["scaler_scale"], frame.x[training].std(axis=0))
        self.assertLessEqual(model["convergence"]["gradient_linf"], self.spec["optimizer_gradient_tolerance"])
        with self.assertRaisesRegex(ValueError, "crossing"):
            baseline.fit(frame, np.r_[training, 950], .03, .1, end, self.spec)

    def test_inner_selection_unaffected_by_future_outer_labels(self):
        frame = self.frame()
        end = frame.start + 1200 * baseline.HOUR
        selected = baseline.select_l2(frame, end, .03, self.spec)
        changed = copy.deepcopy(frame)
        changed.future_return[1200:] = 100
        changed.x[1200:] = 99999
        self.assertEqual(selected, baseline.select_l2(changed, end, .03, self.spec))

    def test_binary_hurdle_and_tied_auc_and_single_class_metrics(self):
        hurdle = .03
        self.assertEqual((np.array([-.1, 0, .01, .03, .030001]) > hurdle).tolist(), [False, False, False, False, True])
        report = baseline.metrics(np.array([0, 1, 0, 1]), np.full(4, .5))
        self.assertEqual(report["auc"], .5); self.assertEqual(report["brier"], .25)
        self.assertAlmostEqual(report["log_loss"], np.log(2))
        self.assertIsNone(baseline.metrics(np.zeros(4), np.full(4, .4))["auc"])

    def policy_frame(self):
        n = 300
        prices = np.full(n + 1, 100.0); prices[121] = 110.0
        return baseline.Frame(self.start, self.start + n * baseline.HOUR, prices, prices.copy(),
                              np.zeros((n,5)), np.full(n, np.nan), [])

    def test_paper_delayed_fill_cost_once_and_missing_label_not_entry_gate(self):
        frame = self.policy_frame()
        policy, trades, _ = baseline.paper(frame, np.array([0]), np.array([.9]), frame.start, frame.cutoff, self.spec)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["entry_time"], baseline.iso(frame.start + baseline.HOUR))
        self.assertEqual(trades[0]["exit_time"], baseline.iso(frame.start + 121 * baseline.HOUR))
        self.assertAlmostEqual(policy["net_return"], .1 * (.1 - .02))
        stressed, _, _ = baseline.paper(frame, np.array([0]), np.array([.9]), frame.start, frame.cutoff, self.spec, cost=.04)
        self.assertAlmostEqual(stressed["net_return"], .1 * (.1 - .04))

    def test_missing_exit_unresolved_and_missing_mark_risk_incomplete(self):
        frame = self.policy_frame(); frame.xmr[121] = np.nan
        result, trades, _ = baseline.paper(frame, np.array([0]), np.array([.9]), frame.start, frame.cutoff, self.spec)
        self.assertEqual(result["unresolved_trades"], 1); self.assertFalse(result["complete"])
        self.assertEqual(trades, []); self.assertIsNone(result["net_return"])
        frame = self.policy_frame(); frame.xmr[50] = np.nan
        result, trades, _ = baseline.paper(frame, np.array([0]), np.array([.9]), frame.start, frame.cutoff, self.spec)
        self.assertEqual(result["completed_trades"], 1); self.assertFalse(result["risk_complete"])

    def test_no_same_timestamp_reentry_and_no_exit_across_block(self):
        frame = self.policy_frame()
        policy, trades, _ = baseline.paper(frame, np.array([0,121,180,299]), np.full(4,.9),
                                            frame.start, frame.cutoff, self.spec)
        self.assertEqual(policy["completed_trades"], 1)

    def test_calendar_split_and_oos_cannot_be_enabled(self):
        baseline.validate_spec(self.spec)
        self.assertEqual(baseline.inner_bounds(baseline.timestamp(self.spec["history_start"]),
            baseline.timestamp(self.spec["initial_development_end"]))[0],
            (baseline.timestamp("2018-12-15T00:00:00Z"), baseline.timestamp("2019-08-09T08:00:00Z")))
        changed = dict(self.spec, reserved_period_evaluation_allowed=True)
        with self.assertRaisesRegex(ValueError, "disabled"):
            baseline.validate_spec(changed)

    def test_empty_fixed_selection_fold_reported_without_reallocating(self):
        frame = self.frame()
        frame.x[1000:1200] = np.nan
        spec = dict(self.spec, initial_development_end=baseline.iso(frame.start + 1200 * baseline.HOUR))
        report = baseline.readiness(frame, spec)
        self.assertFalse(report["initial_selection_ready"])
        self.assertEqual(report["initial_selection_folds"][2]["validation_rows"], 0)
        self.assertEqual(report["initial_selection_folds"][2]["training_end"], baseline.iso(frame.start + 1000 * baseline.HOUR))

    def test_synthetic_end_to_end_freeze_and_exact_reproduction(self):
        # Full declared procedure on synthetic history, never the real model's outcomes.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = copy.deepcopy(self.spec)
            # Synthetic sources have no real archive-validation manifests.
            for key in ("xmr_coverage_path", "btc_coverage_path", "xmr_validation_path", "btc_validation_path"):
                spec.pop(key, None)
            end = self.start + 200 * 24 * baseline.HOUR
            cutoff = self.start + 160 * 24 * baseline.HOUR
            initial = self.start + 80 * 24 * baseline.HOUR
            spec.update(history_start=baseline.iso(self.start), history_end_exclusive=baseline.iso(end),
                        development_end_exclusive=baseline.iso(cutoff), initial_development_end=baseline.iso(initial),
                        outer_ends=[baseline.iso(initial + (cutoff-initial) * i // 3) for i in (1,2,3)],
                        bootstrap_replicates=10)
            for path in baseline.provenance_paths(spec):
                dest = root / path; dest.parent.mkdir(parents=True, exist_ok=True)
                if path not in (spec["xmr_path"], spec["btc_path"], spec["price_review_path"]):
                    dest.write_text("synthetic fixture\n")
            frame = self.frame(200 * 24)
            self.write_prices(root / spec["xmr_path"], 200 * 24, frame.xmr, poison_from=160*24)
            self.write_prices(root / spec["btc_path"], 200 * 24, frame.btc, poison_from=160*24)
            baseline.prepare_review(spec, root)
            baseline.freeze(spec, root)
            result = baseline.run(spec, root)
            reproduced = baseline.run(spec, root, check_reproduction=True)
            self.assertEqual(result, reproduced)
            self.assertFalse(result["heldout_outcomes_evaluated"])
            self.assertFalse(result["incident_hypothesis_tested"])
            self.assertEqual(len(result["outer_folds"]), 3)
            self.assertTrue((root / baseline.OUT / "SELECTED.json").exists())
            with self.assertRaisesRegex(ValueError, "overwrite"):
                baseline.run(spec, root)
            (root / spec["btc_path"]).write_text("changed source")
            with self.assertRaisesRegex(ValueError, "Frozen input"):
                baseline.verify(spec, root)


if __name__ == "__main__":
    unittest.main()
