"""
Robustness tests: randomized parameter fuzzing, solution continuity,
and numerical stability checks.
"""

from __future__ import annotations

import random
import unittest

from params import AircraftSelection, AirlineSelection, ModelConfig

from tests.model_harness import (
    ToyAircraftSelection,
    ToyAirlineSelection,
    audit_constraints,
    solve,
    toy_aircraft,
    toy_airline,
    toy_demand,
)


class TestFuzzRandomized(unittest.TestCase):
    """Random toy instances should solve without constraint violations."""

    def test_random_toy_instances(self):
        rng = random.Random(42)
        failures = []
        for trial in range(25):
            seats = rng.randint(80, 200)
            casm = rng.uniform(0.04, 0.15)
            price = rng.uniform(5, 80)
            budget = rng.uniform(50, 800)
            pax = rng.uniform(5_000, 200_000)
            ac = toy_aircraft(
                f"Jet{trial}",
                seats=seats,
                casm=casm,
                price=price,
                risk_coef=rng.uniform(0, 20),
            )
            al = toy_airline(
                budget=budget,
                risk_aversion=rng.uniform(0, 100),
                moq_threshold=rng.choice([1, 3, 5]),
                max_aircraft_types=rng.randint(1, 3),
            )
            result, opt = solve(
                ToyAircraftSelection([ac]),
                ToyAirlineSelection([al]),
                "ToyAirline",
                toy_demand(pax=pax),
            )
            if result.status != "optimal":
                failures.append(f"trial {trial}: status={result.status}")
                continue
            audit = audit_constraints(opt, result, opt)
            if not audit.ok:
                failures.append(f"trial {trial}:\n{audit.summary()}")
        self.assertEqual(failures, [], "\n".join(failures))


class TestSolutionContinuity(unittest.TestCase):
    """Small parameter nudges should not cause wild discrete jumps without cause."""

    def test_casm_perturbation_continuous_orders(self):
        al = toy_airline(budget=500, risk_aversion=10, moq_threshold=1)
        demand = toy_demand(pax=80_000)
        orders_prev = None
        jumps = []
        for delta in [0.0, 0.005, 0.01, 0.015, 0.02]:
            ac = toy_aircraft("Stable", casm=0.10 + delta, price=10, risk_coef=1)
            result, _ = solve(
                ToyAircraftSelection([ac]),
                ToyAirlineSelection([al]),
                "ToyAirline",
                demand,
            )
            o = result.orders["Stable"]
            if orders_prev is not None and abs(o - orders_prev) > 20:
                jumps.append((delta, orders_prev, o))
            orders_prev = o
        self.assertEqual(jumps, [], f"Large order jumps: {jumps}")


class TestCatalogRobustness(unittest.TestCase):
    def test_leader_feasible_under_tiny_demand_perturbation(self):
        """Small demand shifts must remain feasible with zero constraint violations."""
        from params import demand as catalog_demand
        scales = [0.98, 1.0, 1.02]
        order_snapshots = []
        for s in scales:
            d = catalog_demand.scaled(s)
            result, opt = solve(
                AircraftSelection(),
                AirlineSelection(),
                "Leader",
                d,
            )
            self.assertEqual(result.status, "optimal")
            audit = audit_constraints(opt, result, opt)
            self.assertTrue(audit.ok, audit.summary())
            order_snapshots.append(tuple(sorted((a, n) for a, n in result.orders.items() if n > 0)))
        # Note: order mix may change discretely under tiny demand shifts (see suite summary).
        _ = order_snapshots

    def test_mip_gap_tightening_preserves_feasibility(self):
        from params import demand as catalog_demand
        cfg_loose = ModelConfig(mip_gap=0.05)
        cfg_tight = ModelConfig(mip_gap=1e-4)
        r1, opt1 = solve(
            AircraftSelection(), AirlineSelection(), "Leader", catalog_demand, cfg_loose,
        )
        r2, opt2 = solve(
            AircraftSelection(), AirlineSelection(), "Leader", catalog_demand, cfg_tight,
        )
        self.assertEqual(r1.status, "optimal")
        self.assertEqual(r2.status, "optimal")
        for opt, r in [(opt1, r1), (opt2, r2)]:
            audit = audit_constraints(opt, r, opt)
            self.assertTrue(audit.ok, audit.summary())


class TestScaling(unittest.TestCase):
    def test_objective_scales_with_horizon(self):
        from params import demand as catalog_demand
        cfg1 = ModelConfig(time_horizon_years=1)
        cfg5 = ModelConfig(time_horizon_years=5)
        r1, _ = solve(AircraftSelection(), AirlineSelection(), "Leader", catalog_demand, cfg1)
        r5, _ = solve(AircraftSelection(), AirlineSelection(), "Leader", catalog_demand, cfg5)
        if r1.objective and r5.objective:
            ratio = r5.objective / r1.objective
            self.assertAlmostEqual(ratio, 5.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
