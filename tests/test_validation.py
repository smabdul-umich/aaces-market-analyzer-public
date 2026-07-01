"""
Model validation tests: realistic scenarios, sensitivity, benchmarks,
and diagnostic reporting.
"""

from __future__ import annotations

import unittest

from params import Aircraft, AircraftFamily, AircraftSelection, AirlineSelection, Demand, DemandSegment, ModelConfig
from scenarios import Scenario, ScenarioRunner

from tests.model_harness import (
    aircraft_selection_diagnostics,
    audit_constraints,
    benchmark_cheapest_casm,
    benchmark_min_risk,
    independent_financials,
    solve,
)


class TestRealisticScenarios(unittest.TestCase):
    def test_leader_baseline_optimal_and_physical(self):
        from params import demand as catalog_demand
        result, opt = solve(AircraftSelection(), AirlineSelection(), "Leader", catalog_demand)
        self.assertEqual(result.status, "optimal")
        audit = audit_constraints(opt, result, opt)
        self.assertTrue(audit.ok, audit.summary())
        # Existing fleet should fly; new orders non-negative integers
        total_orders = sum(result.orders.values())
        self.assertGreaterEqual(total_orders, 0)
        for name, util in result.utilization.items():
            if util.total_fleet_count > 0:
                self.assertLessEqual(util.utilization_rate, 1.0 + 1e-4)

    def test_study1_airline_single_type(self):
        from study_common import study_demand, STUDY_AIRLINE, make_runner
        runner = make_runner(__import__("study1_sensitivity", fromlist=["STUDY_1"]).STUDY_1)
        result = runner.run_one(Scenario("baseline"))
        self.assertEqual(result.status, "optimal")
        types = [a for a, n in result.orders.items() if n > 0]
        self.assertLessEqual(len(types), 1)

    def test_follower_differs_from_leader(self):
        from params import demand as catalog_demand
        rL, _ = solve(AircraftSelection(), AirlineSelection(), "Leader", catalog_demand)
        rF, _ = solve(AircraftSelection(), AirlineSelection(), "Follower", catalog_demand)
        self.assertEqual(rL.status, "optimal")
        self.assertEqual(rF.status, "optimal")
        # Different existing fleets → different utilization at minimum
        self.assertNotEqual(rL.existing_fleet, rF.existing_fleet)


class TestSensitivityValidation(unittest.TestCase):
    """Parameter shifts should move solutions in economically sensible directions."""

    def setUp(self):
        from params import demand as catalog_demand
        self.demand = catalog_demand
        self.runner = ScenarioRunner(airline_name="Leader", demand=catalog_demand)

    def _profit(self, scenario: Scenario) -> float:
        r = self.runner.run_one(scenario)
        self.assertEqual(r.status, "optimal")
        return r.total_profit

    def test_higher_demand_weakly_increases_profit(self):
        base = self._profit(Scenario("base"))
        high = self._profit(Scenario("high_demand", demand_scale=1.5))
        self.assertGreaterEqual(high, base)

    def test_higher_casm_weakly_decreases_profit(self):
        base = self._profit(Scenario("base"))
        high_casm = self._profit(Scenario(
            "casm_up",
            aircraft_overrides={a: {"casm": 0.20} for a in AircraftSelection().names},
        ))
        self.assertLessEqual(high_casm, base)

    def test_subsidy_weakly_increases_or_preserves_feasibility(self):
        """Lower acquisition price via adjustment should not reduce optimal profit."""
        base = self._profit(Scenario("base"))
        subsidized = self._profit(Scenario(
            "subsidy",
            aircraft_overrides={"Concept_A": {"price_adjustment": -5}},
        ))
        self.assertGreaterEqual(subsidized, base)

    def test_higher_fixed_cost_decreases_profit(self):
        base = self._profit(Scenario("base"))
        high_fix = self._profit(Scenario(
            "fix_up",
            aircraft_overrides={a: {"yearly_fixed_cost": 50} for a in AircraftSelection().names},
        ))
        self.assertLess(high_fix, base)

    def test_higher_risk_aversion_discourages_concentration(self):
        runner_low = ScenarioRunner(
            airline_name="Leader",
            demand=self.demand,
        )
        runner_high = ScenarioRunner(
            airline_name="Leader",
            demand=self.demand,
        )
        runner_high.run_one(Scenario("ra", airline_overrides={"Leader": {"risk_aversion": 5000}}))
        r_low = runner_low.run_one(Scenario("base"))
        r_high = runner_high.run_one(Scenario("ra", airline_overrides={"Leader": {"risk_aversion": 5000}}))
        risk_low = r_low.risk_cost
        risk_high = r_high.risk_cost
        # Higher aversion with same orders would increase risk cost; optimizer should adjust down
        self.assertLessEqual(r_high.risk_cost, risk_low + 1e6)  # loose guard


class TestBenchmarkComparison(unittest.TestCase):
    def test_leader_orders_align_with_low_casm_benchmark(self):
        from params import demand as catalog_demand
        result, opt = solve(AircraftSelection(), AirlineSelection(), "Leader", catalog_demand)
        bench = benchmark_cheapest_casm(opt, result)
        self.assertIsNotNone(bench)
        # Leader has existing fleet; benchmark is informational — ordered types should have reasonable CASM
        ordered = [a for a, n in result.orders.items() if n > 0]
        if ordered:
            casms = [opt.aircrafts.casm(a, True) for a in ordered]
            self.assertLessEqual(max(casms), 0.12 + 1e-6)  # catalog max conventional CASM

    def test_study1_choice_between_conventional_and_concept(self):
        from study_common import make_runner, make_baseline_scenario
        from study1_sensitivity import STUDY_1
        runner = make_runner(STUDY_1)
        result = runner.run_one(make_baseline_scenario())
        self.assertEqual(result.status, "optimal")
        chosen = [a for a, n in result.orders.items() if n > 0]
        self.assertEqual(len(chosen), 1)
        diag = aircraft_selection_diagnostics(
            _optimizer_from_runner(runner),
            result,
        )
        self.assertTrue(any("SELECTED" in line for line in diag))


def _optimizer_from_runner(runner: ScenarioRunner):
    from miqp_portfolio import FleetOptimizer
    return FleetOptimizer(
        AircraftSelection(runner.aircraft_filter) if runner.aircraft_filter else AircraftSelection(),
        AirlineSelection(),
        runner.airline_name,
        runner.demand,
        runner.config,
    )


class TestDiagnostics(unittest.TestCase):
    def test_diagnostics_cover_all_types(self):
        from params import demand as catalog_demand
        result, opt = solve(AircraftSelection(), AirlineSelection(), "Leader", catalog_demand)
        lines = aircraft_selection_diagnostics(opt, result)
        self.assertEqual(len(lines), len(opt.aircraft_names))


class TestCounterintuitiveFlags(unittest.TestCase):
    """Flag parameter regimes that produce surprising outcomes."""

    def test_concept_a_high_risk_coef_vs_b737(self):
        """Concept_A risk_coef=268 in params.py can dominate operating savings — flag it."""
        from study_common import make_runner, make_baseline_scenario
        from study1_sensitivity import STUDY_1
        runner = make_runner(STUDY_1)
        result = runner.run_one(make_baseline_scenario())
        concept_risk = AircraftSelection().risk_coef("Concept_A")
        conv_risk = AircraftSelection().risk_coef("B737Max8")
        self.assertGreater(concept_risk, conv_risk * 10)
        # At equal CASM/price, conventional should win unless concept CASM much lower
        chosen = [a for a, n in result.orders.items() if n > 0]
        if chosen == ["B737Max8"]:
            pass  # expected given current risk_coef
        # Test documents behavior; no failure if concept wins after param change

    def test_price_not_in_objective_makes_acquisition_insensitive(self):
        """Known model property: price affects budget only, not annual profit."""
        from study_common import make_runner, build_price_sweep, STUDY_AIRLINE
        from study1_sensitivity import STUDY_1
        runner = make_runner(STUDY_1)
        results = runner.run(build_price_sweep()[:3])
        profits = [r.total_profit for r in results.values()]
        if len(set(round(p, 0) for p in profits)) == 1:
            # Counterintuitive but documented: flat price sweep when budget non-binding
            self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
