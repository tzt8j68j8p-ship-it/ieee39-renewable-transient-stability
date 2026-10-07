"""Synthetic accepted trajectories; no ANDES imports or TDS calls."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ieee39ts.stability import angle_metrics, assess_trajectory, mapped_inertias
from ieee39ts.types import RunDiagnostics, SimulationStatus, Trajectory


def trace(separations=(10, 20, 30, 40)):
    values = np.deg2rad(np.asarray(separations, dtype=float))
    return Trajectory(np.array([0.0, 1.0, 2.0, 8.0]),
                      np.column_stack([np.zeros(4), values]), np.ones((4, 2)),
                      np.ones((4, 3)), np.array(["G1", "G2"]), np.array([30, 31]),
                      np.array([1.0, 3.0]), np.array([1, 2, 3]))


def completed():
    return RunDiagnostics(simulation_status=SimulationStatus.COMPLETED,
                          termination_reason="OBSERVATION_END_REACHED",
                          pflow_converged=True, tds_initialized=True, tds_return=True,
                          exit_code=0, fault_cleared=True)


class AngleMetricsTests(unittest.TestCase):
    def test_weighted_coi_and_relative_angles(self):
        delta = np.array([[0.0, 2.0], [2.0, 6.0]])
        result = angle_metrics(delta, np.array([1.0, 3.0]))
        np.testing.assert_allclose(result["delta_coi_rad"], [1.5, 5.0])
        np.testing.assert_allclose(result["delta_relative_rad"], [[-1.5, .5], [-3, 1]])

    def test_common_angle_shift_preserves_separation(self):
        delta = np.array([[1.0, 2.0, 4.0], [10.0, 14.0, 9.0]])
        weights = np.array([2.0, 5.0, 7.0])
        first = angle_metrics(delta, weights)
        second = angle_metrics(delta + 100, weights)
        np.testing.assert_allclose(first["angle_separation_deg"], second["angle_separation_deg"])
        np.testing.assert_allclose(first["delta_relative_rad"], second["delta_relative_rad"])

    def test_ten_and_nine_generator_mapping(self):
        mapping = {f"G{i}": float(i) for i in range(1, 11)}
        for count in (10, 9):
            with self.subTest(count=count):
                ids = [f"G{i}" for i in range(count, 0, -1)]
                weights = mapped_inertias(ids, mapping)
                np.testing.assert_equal(weights, list(range(count, 0, -1)))
                delta = np.tile(np.arange(count), (2, 1))
                result = angle_metrics(delta, weights)
                np.testing.assert_allclose(result["delta_coi_rad"], np.average(delta, axis=1, weights=weights))

    def test_missing_and_misaligned_inertia_rejected(self):
        with self.assertRaises(ValueError):
            mapped_inertias(["G1", "G2"], {"G1": 1})
        with self.assertRaises(ValueError):
            angle_metrics(np.ones((3, 2)), np.ones(3))
        with self.assertRaises(ValueError):
            angle_metrics(np.ones((3, 2)), np.array([1, -1]))

    def test_continuous_angles_not_unwrapped(self):
        result = angle_metrics(np.array([[0, 0], [0, 4 * np.pi]]), np.ones(2))
        self.assertAlmostEqual(result["angle_separation_deg"][-1], 720)


class ClassificationTests(unittest.TestCase):
    def test_complete_valid_run_is_stable(self):
        report, _ = assess_trajectory(trace(), completed())
        self.assertEqual(report["stability_status"], "STABLE")
        self.assertEqual(report["valid_sample_count"], 4)

    def test_valid_separation_above_180_is_unstable(self):
        report, _ = assess_trajectory(trace([10, 181, 190, 200]), completed())
        self.assertEqual(report["stability_status"], "UNSTABLE")
        self.assertEqual(report["first_angle_crossing_s"], 1)

    def test_exact_180_matches_andes_threshold(self):
        report, _ = assess_trajectory(trace([10, 180, 181, 200]), completed())
        self.assertEqual(report["first_angle_crossing_s"], 1)

    def test_numeric_failure_before_crossing_is_non_convergent(self):
        diag = replace(completed(), simulation_status=SimulationStatus.NUMERICAL_FAILURE,
                       termination_reason="NEWTON_INTEGRATION_FAILURE", numerical_failure=True,
                       failure_time_s=1.5, tds_return=False, busted=True, exit_code=1,
                       err_msg="Time step reduced to zero")
        report, _ = assess_trajectory(trace([10, 20, 200, 300]), diag)
        self.assertEqual(report["stability_status"], "NON_CONVERGENT")
        self.assertIsNone(report["first_angle_crossing_s"])
        self.assertEqual(report["valid_sample_count"], 2)
        self.assertEqual(report["first_quality_failure_s"], 1.5)

    def test_crossing_then_failure_retains_unstable_and_failure_metadata(self):
        diag = replace(completed(), simulation_status=SimulationStatus.NUMERICAL_FAILURE,
                       termination_reason="NEWTON_INTEGRATION_FAILURE", numerical_failure=True,
                       failure_time_s=2.0, tds_return=False, busted=True, exit_code=1,
                       err_msg="Time step reduced to zero")
        report, _ = assess_trajectory(trace([10, 200, 300, 400]), diag)
        self.assertEqual(report["stability_status"], "UNSTABLE")
        self.assertTrue(report["tail_invalid"])
        self.assertEqual(diag.simulation_status, "NUMERICAL_FAILURE")
        self.assertEqual(diag.exit_code, 1)
        self.assertEqual(report["first_angle_crossing_s"], 1)

    def test_criterion_stop_can_be_unstable_despite_false_return(self):
        diag = replace(completed(), simulation_status=SimulationStatus.ANGLE_CRITERION_STOP,
                       termination_reason="ANGLE_SEPARATION_CRITERION", tds_return=False,
                       busted=True, exit_code=1, err_msg="Violated stability criteria")
        report, _ = assess_trajectory(trace([10, 200, 210, 220]), diag)
        self.assertEqual(report["stability_status"], "UNSTABLE")

    def test_criterion_error_without_angle_evidence_not_unstable(self):
        diag = replace(completed(), simulation_status=SimulationStatus.ANGLE_CRITERION_STOP,
                       tds_return=False, busted=True, exit_code=1,
                       err_msg="Violated stability criteria")
        report, _ = assess_trajectory(trace(), diag)
        self.assertEqual(report["stability_status"], "NON_CONVERGENT")

    def test_bad_tail_cannot_erase_earlier_valid_crossing(self):
        data = trace([10, 200, 210, 220])
        data.delta_rad[-1, 0] = np.nan
        report, arrays = assess_trajectory(data, completed())
        self.assertEqual(report["stability_status"], "UNSTABLE")
        self.assertTrue(report["tail_invalid"])
        np.testing.assert_equal(arrays["valid_mask"], [True, True, True, False])

    def test_invalid_voltage_before_crossing_censors_later_evidence(self):
        data = trace([10, 20, 200, 300])
        data.bus_voltage_pu[1, 0] = -0.01
        report, _ = assess_trajectory(data, completed())
        self.assertEqual(report["stability_status"], "NON_CONVERGENT")
        self.assertIsNone(report["first_angle_crossing_s"])

    def test_unknown_failure_time_cannot_support_crossing(self):
        diag = replace(completed(), simulation_status=SimulationStatus.NUMERICAL_FAILURE,
                       numerical_failure=True, failure_time_s=None, tds_return=False, exit_code=1)
        report, _ = assess_trajectory(trace([10, 200, 300, 400]), diag)
        self.assertEqual(report["stability_status"], "NON_CONVERGENT")

    def test_nonfinite_failure_time_cannot_support_crossing(self):
        diag = replace(completed(), simulation_status=SimulationStatus.NUMERICAL_FAILURE,
                       numerical_failure=True, failure_time_s=float("nan"),
                       tds_return=False, exit_code=1)
        report, _ = assess_trajectory(trace([10, 200, 300, 400]), diag)
        self.assertEqual(report["stability_status"], "NON_CONVERGENT")

    def test_flags_alone_do_not_establish_instability(self):
        diag = replace(completed(), simulation_status=SimulationStatus.NUMERICAL_FAILURE,
                       numerical_failure=True, failure_time_s=2.0,
                       tds_return=False, busted=True, exit_code=1)
        report, _ = assess_trajectory(trace(), diag)
        self.assertEqual(report["stability_status"], "NON_CONVERGENT")

    def test_early_termination_not_stable(self):
        report, _ = assess_trajectory(trace(), replace(completed(), simulation_status=SimulationStatus.EARLY_TERMINATION))
        self.assertEqual(report["stability_status"], "NON_CONVERGENT")

    def test_empty_trajectory_not_stable(self):
        report, _ = assess_trajectory(None, completed())
        self.assertEqual(report["stability_status"], "NON_CONVERGENT")


if __name__ == "__main__":
    unittest.main()
