# scenarios.py
"""
Scenario definition and batch execution for fleet-optimization analysis.

A ``Scenario`` is a lightweight, declarative container that describes
parameter overrides (aircraft attributes, airline attributes, demand
scaling).  ``ScenarioRunner`` takes base parameter objects, applies each
scenario's overrides to independent copies, solves via ``FleetOptimizer``,
and collects the results for comparison.

This module is designed to serve as the interface between any frontend
(GUI, notebook, CLI script) and the solver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from params import Aircraft, AircraftFamily, AircraftSelection, AirlineSelection, Demand, ModelConfig
from miqp_portfolio import FleetOptimizer, SolverResult


# ── Scenario ────────────────────────────────────────────────────────

@dataclass
class Scenario:
    """A named set of parameter overrides to apply before solving.

    All override fields default to empty / None, so ``Scenario("baseline")``
    is a valid no-change scenario.
    """

    label: str
    aircraft_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    airline_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    demand_scale: Optional[float] = None

    # ── factories for common sweep patterns ──────────────────────

    @classmethod
    def sweep(
        cls,
        attribute: str,
        aircrafts: List[str],
        values: List[Union[int, float]],
        *,
        label_prefix: Optional[str] = None,
    ) -> List[Scenario]:
        """Generate one ``Scenario`` per value, setting *attribute* on every aircraft in the list.

        Example::

            Scenario.sweep(
                attribute="price_adjustment",
                aircrafts=["Concept_A", "Concept_B"],
                values=[0, -2, -5],
                label_prefix="subsidy",
            )
            # -> [Scenario("subsidy_0"), Scenario("subsidy_-2"), Scenario("subsidy_-5")]
        """
        prefix = label_prefix or attribute
        return [
            cls(
                label=f"{prefix}={value}",
                aircraft_overrides={aircraft: {attribute: value} for aircraft in aircrafts},
            )
            for value in values
        ]

    @classmethod
    def sweep_airline(
        cls,
        attribute: str,
        airlines: List[str],
        values: List[Union[int, float]],
        *,
        label_prefix: Optional[str] = None,
    ) -> List[Scenario]:
        """Same as ``sweep`` but for airline attributes (e.g. budget, risk_aversion)."""
        prefix = label_prefix or attribute
        return [
            cls(
                label=f"{prefix}={value}",
                airline_overrides={airline: {attribute: value} for airline in airlines},
            )
            for value in values
        ]

    @classmethod
    def sweep_demand(
        cls,
        fractions: List[float],
        *,
        label_prefix: str = "demand_scale",
    ) -> List[Scenario]:
        """Generate one ``Scenario`` per demand-scaling fraction."""
        return [
            cls(label=f"{label_prefix}={fraction}", demand_scale=fraction)
            for fraction in fractions
        ]


# ── ScenarioRunner ──────────────────────────────────────────────────

class ScenarioRunner:
    """Runs isolated solves for each scenario.

    Every ``run_one`` call constructs fresh ``AircraftSelection`` and
    ``AirlineSelection`` objects from the defaults in ``params.py``,
    applies the scenario's overrides, and solves.  No shared mutable state
    between runs.
    """

    def __init__(
        self,
        airline_name: str,
        demand: Demand,
        config: ModelConfig = ModelConfig(),
        aircraft_filter: Optional[Callable[[Aircraft], bool]] = None,
    ):
        """Construct a runner for a given airline / demand / solver config.

        ``aircraft_filter`` (optional) restricts the aircraft choice set passed to
        the solver.  If provided, only aircraft for which the filter returns
        ``True`` can be ordered.  This is used by sensitivity studies that need
        to constrain the model to a small subset of the catalog (e.g. one
        conventional vs one novel-aircraft-concept type).
        """
        self.airline_name    = airline_name
        self.demand          = demand
        self.config          = config
        self.aircraft_filter = aircraft_filter

    # ── execution ────────────────────────────────────────────────

    def run_one(self, scenario: Scenario, *, verbose: bool = False) -> SolverResult:
        """Apply a single scenario's overrides and solve.  Returns one ``SolverResult``."""
        aircrafts = AircraftSelection(self.aircraft_filter)
        airlines  = AirlineSelection()
        demand    = self.demand

        if scenario.aircraft_overrides:
            aircrafts.apply_mofd(scenario.aircraft_overrides)
        if scenario.airline_overrides:
            airlines.apply_mofd(scenario.airline_overrides)
        if scenario.demand_scale is not None:
            demand = demand.scaled(scenario.demand_scale)

        optimizer = FleetOptimizer(aircrafts, airlines, self.airline_name, demand, self.config)
        return optimizer.solve(verbose=verbose)

    def run(
        self,
        scenarios: Sequence[Scenario],
        *,
        verbose: bool = False,
    ) -> Dict[str, SolverResult]:
        """Run every scenario and return results keyed by label."""
        return {
            scenario.label: self.run_one(scenario, verbose=verbose)
            for scenario in scenarios
        }

    # ── comparison ───────────────────────────────────────────────

    @staticmethod
    def compare(results: Dict[str, SolverResult]) -> str:
        """Build a side-by-side comparison string across scenario results.

        Shows one row per scenario with key metrics: status, profit,
        orders by type, concept penetration, and weighted CASM.
        """
        if not results:
            return "(no results to compare)"

        # Collect all aircraft names that were ordered in any scenario
        all_ordered_aircraft: set[str] = set()
        for result in results.values():
            for aircraft, count in result.orders.items():
                if count > 0:
                    all_ordered_aircraft.add(aircraft)
        ordered_names = sorted(all_ordered_aircraft)

        # Header
        aircraft_headers = "".join(f"  {name:>10s}" for name in ordered_names)
        header = f"{'Scenario':<30s}  {'Status':<12s}  {'Total Profit':>14s}{aircraft_headers}  {'Concept%':>9s}  {'CASM':>8s}"
        separator = "─" * len(header)

        lines = [separator, header, separator]

        for label, result in results.items():
            profit_str = f"{result.total_profit:>14,.0f}" if result.objective is not None else f"{'N/A':>14s}"
            aircraft_cols = "".join(
                f"  {result.orders.get(name, 0):>10d}" for name in ordered_names
            )
            concept_str = f"{result.concept_penetration:>8.1%}" if result.objective is not None else f"{'N/A':>8s}"
            casm_str = f"{result.weighted_casm:>8.4f}" if result.weighted_casm else f"{'N/A':>8s}"

            lines.append(
                f"{label:<30s}  {result.status:<12s}  {profit_str}{aircraft_cols}  {concept_str}  {casm_str}"
            )

        lines.append(separator)
        return "\n".join(lines)


# ── Presets ─────────────────────────────────────────────────────────

_concept_names = AircraftSelection(lambda aircraft: aircraft.family == AircraftFamily.NOVEL_AIRCRAFT_CONCEPT).names

PRESETS: Dict[str, List[Scenario]] = {
    "concept_subsidy_sweep": [
        Scenario("baseline (no subsidy)"),
    ] + Scenario.sweep(
        attribute="price_adjustment",
        aircrafts=_concept_names,
        values=[-2, -5, -10],
        label_prefix="subsidy",
    ),

    "concept_casm_sweep": Scenario.sweep(
        attribute="casm",
        aircrafts=_concept_names,
        values=[0.06, 0.08, 0.10, 0.12],
        label_prefix="concept_casm",
    ),

    "demand_sensitivity": Scenario.sweep_demand(
        fractions=[0.5, 0.75, 1.0, 1.25, 1.5],
    ),

    "budget_sweep": Scenario.sweep_airline(
        attribute="budget",
        airlines=["Leader"],
        values=[200, 400, 600, 800, 1000],
        label_prefix="budget",
    ),
}
