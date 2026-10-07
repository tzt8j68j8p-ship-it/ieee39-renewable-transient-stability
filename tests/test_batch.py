"""Pure callback/array tests; no ANDES or real TDS runs."""
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ieee39ts.batch import (BatchSettings, DEFAULT_BUSES, SUMMARY_FIELDS, cct_ranking,
    read_batch_settings, reference_metrics, run_batch, severity_ranking,
    sort_results, write_batch_summary)
from ieee39ts.types import FaultResult, SearchSettings, Trajectory


def result(bus=16, duration=.125, status="STABLE", peak=100):
    trajectory = Trajectory(np.array([0., 1., 1.1]), np.zeros((3, 2)), np.ones((3, 2)),
                            np.array([[1., 1.], [.02, .8], [-.5, .6]]),
                            np.array(["g1", "g2"]), np.array([30, 31]),
                            np.array([2., 1.]), np.array([bus, 39]))
    return FaultResult({"fault_bus": bus, "clearing_duration_s": duration,
                        "stability_status": status, "simulation_status": "COMPLETED",
                        "max_angle_separation_deg": peak, "max_speed_deviation_pu": .02,
                        "runtime_s": .1, "last_valid_time_s": 1., "tail_invalid": True},
                       trajectory, {"valid_mask": np.array([True, True, False])})


def row(bus, status, estimate, peak=100, reference_status="STABLE"):
    return {**dict.fromkeys(SUMMARY_FIELDS), "fault_id": f"bus{bus:02d}", "fault_bus": bus,
            "model_id": "ieee39_official", "search_status": status, "cct_estimate_s": estimate,
            "max_angle_separation_deg": peak, "reference_stability_status": reference_status,
            "metrics_clear_duration_s": .125}


class BatchTests(unittest.TestCase):
    def test_default_config_retains_exact_fifteen_buses_and_window(self):
        settings = read_batch_settings(ROOT / "configs/fault_scan.json")
        self.assertEqual(settings.fault_buses, DEFAULT_BUSES)
        self.assertEqual(len(settings.fault_buses), 15)
        self.assertEqual(settings.search.grid_ticks(), (4, 25, 1))

    def test_duplicate_fault_bus_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            BatchSettings((16, 16))

    def test_invalid_bus_config_explicit_error(self):
        for bus in (0, 40, True, 16.5, "16"):
            with self.subTest(bus=bus), self.assertRaisesRegex(ValueError, "Invalid fault bus"):
                BatchSettings((bus,))

    def test_empty_bus_config_rejected(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            BatchSettings(())

    def test_nonuniform_reference_duration_rejected(self):
        with self.assertRaisesRegex(ValueError, "0.125"):
            BatchSettings((16,), metrics_clear_duration_s=.1875)

    def test_window_not_automatically_expanded(self):
        with self.assertRaisesRegex(ValueError, "CCT window"):
            BatchSettings((16,), search=SearchSettings(tc_max_s=.25))

    def test_resolved_sort_ascending_unresolved_after(self):
        rows = [row(1, "UNRESOLVED", None), row(16, "RESOLVED", .191), row(3, "RESOLVED", .14)]
        self.assertEqual([r["fault_bus"] for r in sort_results(rows)], [3, 16, 1])

    def test_unresolved_never_zero_or_in_cct_ranking(self):
        rows = [row(1, "UNRESOLVED", 0), row(16, "RESOLVED", .191)]
        self.assertIsNone(sort_results(rows)[1]["cct_estimate_s"])
        self.assertEqual([r["fault_bus"] for r in cct_ranking(rows)], [16])
        self.assertEqual(rows[0]["cct_estimate_s"], 0)  # caller data not mutated

    def test_resolved_missing_estimate_rejected(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            sort_results([row(16, "RESOLVED", None)])

    def test_reference_voltage_min_ignores_invalid_tail(self):
        metrics = reference_metrics(result(), 16, .125)
        self.assertEqual(metrics["min_bus_voltage_pu"], .02)
        self.assertEqual(metrics["fault_bus_voltage_min_pu"], .02)
        self.assertEqual(metrics["max_angle_separation_deg"], 100)

    def test_reference_cannot_take_metrics_from_cct_trial_or_other_bus(self):
        with self.assertRaisesRegex(ValueError, "0.125"):
            reference_metrics(result(duration=.1875), 16, .125)
        with self.assertRaisesRegex(ValueError, "fault_bus"):
            reference_metrics(result(bus=3), 16, .125)

    def test_severity_is_separate_from_cct_and_excludes_invalid_references(self):
        rows = [row(1, "UNRESOLVED", None, 170), row(16, "RESOLVED", .19, 110),
                row(3, "UNRESOLVED", None, 300, "NON_CONVERGENT")]
        self.assertEqual([r["fault_bus"] for r in severity_ranking(rows)], [1, 16])
        self.assertEqual([r["fault_bus"] for r in cct_ranking(rows)], [16])

    def test_all_references_use_common_duration_and_own_metrics(self):
        calls = []
        def run_case(bus, duration):
            calls.append((bus, duration))
            status = "STABLE" if duration < .18 else "UNSTABLE"
            return result(bus, duration, status, 123 if duration == .125 else 999)
        report = run_batch(BatchSettings((3, 16)), run_case)
        self.assertEqual(calls[:2], [(3, .125), (16, .125)])
        for output in report["results"]:
            self.assertEqual(output["metrics_clear_duration_s"], .125)
            self.assertEqual(output["max_angle_separation_deg"], 123)
            self.assertEqual(output["search_status"], "RESOLVED")

    def test_missing_upper_endpoint_renamed_and_kept_null(self):
        calls = []
        def run_case(bus, duration):
            calls.append(duration)
            return result(bus, duration)
        output = run_batch(BatchSettings((16,)), run_case)["results"][0]
        self.assertEqual(output["cct_reason"], "NO_UNSTABLE_ENDPOINT_IN_RANGE")
        self.assertIsNone(output["cct_estimate_s"])
        self.assertEqual(output["stable_lower_s"], .1953125)
        self.assertIsNone(output["unstable_upper_s"])
        self.assertEqual(calls, [.125, .03125, .1953125])

    def test_nonconvergent_midpoint_preserves_verified_boundaries(self):
        def run_case(bus, duration):
            status = "NON_CONVERGENT" if duration == .109375 else ("UNSTABLE" if duration == .1953125 else "STABLE")
            return result(bus, duration, status)
        output = run_batch(BatchSettings((16,)), run_case)["results"][0]
        self.assertEqual(output["cct_reason"], "NON_CONVERGENT_MIDPOINT")
        self.assertEqual(output["stable_lower_s"], .03125)
        self.assertEqual(output["unstable_upper_s"], .1953125)
        self.assertEqual(output["failed_clearing_time_s"], .109375)
        self.assertIsNone(output["cct_estimate_s"])

    def test_one_case_exception_does_not_lose_batch_and_checkpoints(self):
        checkpoints = []
        def run_case(bus, duration):
            if bus == 3:
                raise RuntimeError("test single-case failure")
            return result(bus, duration)
        report = run_batch(BatchSettings((3, 16)), run_case,
                           on_checkpoint=lambda rows: checkpoints.append(rows))
        self.assertEqual(len(report["results"]), 2)
        failed = next(r for r in report["results"] if r["fault_bus"] == 3)
        self.assertEqual(failed["reference_stability_status"], "NON_CONVERGENT")
        self.assertEqual(failed["reference_simulation_status"], "EXECUTION_FAILED")
        self.assertIn("test single-case failure", failed["reference_execution_error"])
        self.assertEqual(failed["cct_reason"], "NON_CONVERGENT_STABLE_ENDPOINT")
        self.assertEqual(len(checkpoints), 5)
        self.assertTrue(all(len(rows) == 2 for rows in checkpoints))

    def test_csv_json_fields_complete_null_csv_blank(self):
        scratch = ROOT / ".cache/test_batch"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temporary:
            output = Path(temporary)
            rows = [row(1, "UNRESOLVED", None), row(16, "RESOLVED", .19)]
            write_batch_summary(output, rows, metadata={"complete": True})
            data = json.loads((output / "batch_summary.json").read_text(encoding="utf-8"))
            with (output / "batch_summary.csv").open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(set(reader.fieldnames), set(SUMMARY_FIELDS))
                csv_rows = list(reader)
            self.assertEqual(len(data["results"]), 2)
            for item in data["results"]:
                self.assertTrue(set(SUMMARY_FIELDS).issubset(item))
            self.assertIsNone(data["results"][1]["cct_estimate_s"])
            self.assertEqual(csv_rows[1]["cct_estimate_s"], "")
            self.assertEqual(data["rankings"]["cct"], ["bus16"])


if __name__ == "__main__":
    unittest.main()
