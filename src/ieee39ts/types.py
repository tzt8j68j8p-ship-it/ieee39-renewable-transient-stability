"""Small data contracts shared by simulation, assessment and CCT search."""
from dataclasses import dataclass, field
from enum import StrEnum
import math

import numpy as np


class StabilityStatus(StrEnum):
    STABLE = "STABLE"
    UNSTABLE = "UNSTABLE"
    NON_CONVERGENT = "NON_CONVERGENT"


class SimulationStatus(StrEnum):
    COMPLETED = "COMPLETED"
    ANGLE_CRITERION_STOP = "ANGLE_CRITERION_STOP"
    PFLOW_FAILED = "PFLOW_FAILED"
    INITIALIZATION_FAILED = "INITIALIZATION_FAILED"
    NUMERICAL_FAILURE = "NUMERICAL_FAILURE"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EARLY_TERMINATION = "EARLY_TERMINATION"
    INVALID_TRAJECTORY = "INVALID_TRAJECTORY"


@dataclass(frozen=True)
class SimulationSettings:
    bus: int = 16
    fault_start_s: float = 1.0
    observation_end_s: float = 8.0
    time_step_s: float = 1 / 128
    angle_limit_deg: float = 180.0
    fault_reactance_pu: float = 1e-4

    def __post_init__(self):
        values = (self.fault_start_s, self.observation_end_s, self.time_step_s,
                  self.angle_limit_deg, self.fault_reactance_pu)
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValueError("Simulation settings must be finite and positive")
        if isinstance(self.bus, bool) or not isinstance(self.bus, int) or not 1 <= self.bus <= 39:
            raise ValueError("Official IEEE39 requires an integer bus from 1 to 39")
        if (self.fault_start_s, self.observation_end_s, self.angle_limit_deg) != (1.0, 8.0, 180.0):
            raise ValueError("Day 1 fixes fault start=1 s, observation end=8 s, angle limit=180 deg")

    def validate_duration(self, duration_s: float):
        if not math.isfinite(duration_s) or not 0 < duration_s < self.observation_end_s - self.fault_start_s:
            raise ValueError("Fault duration must be finite, positive and end before 8 s")


@dataclass
class Trajectory:
    time_s: np.ndarray
    delta_rad: np.ndarray
    omega_pu: np.ndarray
    bus_voltage_pu: np.ndarray
    generator_ids: np.ndarray
    generator_bus_ids: np.ndarray
    inertia_weights: np.ndarray
    bus_ids: np.ndarray

    def validate_shapes(self):
        n = len(self.time_s)
        g = len(self.generator_ids)
        if self.time_s.shape != (n,) or self.delta_rad.shape != (n, g) or self.omega_pu.shape != (n, g):
            raise ValueError("Rotor/time dimensions do not match generator IDs")
        if self.bus_voltage_pu.shape != (n, len(self.bus_ids)):
            raise ValueError("Voltage dimensions do not match bus IDs")
        if self.generator_bus_ids.shape != (g,) or self.inertia_weights.shape != (g,):
            raise ValueError("Generator bus/inertia dimensions do not match IDs")
        if g < 2 or len(set(map(str, self.generator_ids))) != g:
            raise ValueError("Need at least two uniquely identified synchronous generators")
        if not np.isfinite(self.inertia_weights).all() or np.any(self.inertia_weights <= 0):
            raise ValueError("Setup-time inertia weights must be finite and positive")


@dataclass
class RunDiagnostics:
    simulation_status: SimulationStatus = SimulationStatus.EXECUTION_FAILED
    termination_reason: str = "NOT_STARTED"
    pflow_converged: bool = False
    tds_initialized: bool = False
    tds_return: bool = False
    busted: bool = False
    exit_code: int | None = None
    err_msg: str = ""
    numerical_failure: bool = False
    failure_time_s: float | None = None
    fault_cleared: bool = False
    no_fault: bool = False
    execution_error: str | None = None


@dataclass
class FaultResult:
    summary: dict
    trajectory: Trajectory | None = None
    derived_arrays: dict[str, np.ndarray] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchSettings:
    time_step_s: float = 1 / 128
    tc_min_s: float = 4 / 128
    tc_max_s: float = 32 / 128
    tolerance_s: float = 1 / 128
    max_iterations: int = 12

    def grid_ticks(self):
        if not math.isfinite(self.time_step_s) or self.time_step_s <= 0:
            raise ValueError("Grid step must be finite and positive")
        ticks = []
        for value in (self.tc_min_s, self.tc_max_s, self.tolerance_s):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Search bounds and tolerance must be finite and positive")
            ratio = value / self.time_step_s
            if not math.isclose(ratio, round(ratio), rel_tol=0, abs_tol=1e-9):
                raise ValueError("Bounds and tolerance must be integer multiples of the clearing grid")
            ticks.append(round(ratio))
        low, high, tolerance = ticks
        if not 0 < low < high or tolerance < 1:
            raise ValueError("Require 0 < tc_min < tc_max and tolerance >= one grid")
        if isinstance(self.max_iterations, bool) or not isinstance(self.max_iterations, int) or self.max_iterations < 0:
            raise ValueError("max_iterations must be a nonnegative integer")
        return low, high, tolerance
