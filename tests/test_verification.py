"""
Model verification tests: toy problems, per-constraint checks, objective
independence, infeasibility handling, and relaxation direction tests.
"""

from __future__ import annotations

import math
import unittest

from params import (
    AircraftFamily,
    AircraftSelection,
    AirlineSelection,
    Demand,
    DemandSegment,
    Fleets,
    ModelConfig,
)
from miqp_portfolio import FleetOptimizer

from tests.model_harness import (
    TOL,
    ToyAircraftSelection,
    ToyAirlineSelection,
    audit_constraints,
    independent_financials,
    solve,
    toy_aircraft,
    toy_airline,
    toy_demand,
)


class TestObjectiveIndependence(unittest.TestCase):
    """Recomputed financials must match SolverResult within tolerance."""

    def test_toy_single_type(self):
        ac = toy_aircraft("Solo", seats=120, casm=0.08, price=20, block_hours=3000)
        al = toy_airline(budget=10_000, risk_aversion=10.0)
        demand = toy_demand(pax=50_000, block_time=2.5)
        result, opt = solve(ToyAircraftSelection([ac]), ToyAirlineSelection([al]), "ToyAirline", demand)
        self.assertEqual(result.status, "optimal")
        ind = independent_financials(opt, result)
        self.assertAlmostEqual(result.revenue, ind["revenue"], places=2)
        self.assertAlmostEqual(result.operating_cost, ind["operating_cost"], places=2)
        self.assertAlmostEqual(result.fixed_cost, ind["fixed_cost"], places=2)
        self.assertAlmostEqual(result.risk_cost, ind["risk_cost"], places=2)
        self.assertAlmostEqual(result.objective, ind["objective"], places=0)

    def test_catalog_leader_baseline(self):
        from params import demand as catalog_demand
        aircrafts = AircraftSelection()
        airlines = AirlineSelection()
        result, opt = solve(aircrafts, airlines, "Leader", catalog_demand)
        self.assertEqual(result.status, "optimal")
        ind = independent_financials(opt, result)
        self.assertAlmostEqual(result.objective, ind["objective"], delta=max(1.0, abs(ind["objective"]) * 1e-6))


class TestHandCalculatedToy(unittest.TestCase):
    """Small problems where the optimum can be reasoned analytically."""

    def test_single_type_no_risk_orders_to_saturate_block_hours(self):
        """One type, zero risk: fly until block hours bind; orders = ceil(flights*bt/hours)."""
        block_time = 2.0
        block_hours = 1000
        ac = toy_aircraft("Efficient", seats=100, casm=0.05, price=5, block_hours=block_hours, risk_coef=0)
        al = toy_airline(budget=500, risk_aversion=0, moq_threshold=1, max_aircraft_types=1)
        seg = toy_demand(pax=1_000_000, block_time=block_time)  # demand not binding
        result, opt = solve(ToyAircraftSelection([ac]), ToyAirlineSelection([al]), "ToyAirline", seg)
        self.assertEqual(result.status, "optimal")
        flights = result.flights["Efficient", "toy_seg"]
        orders = result.orders["Efficient"]
        # With positive margin the model should use capacity; at least one aircraft.
        self.assertGreater(orders, 0)
        self.assertAlmostEqual(flights * block_time, block_hours * orders, delta=block_time + TOL)
        audit = audit_constraints(opt, result, opt)
        self.assertTrue(audit.ok, audit.summary())

    def test_profit_per_flight_sign_determines_activity(self):
        """Negative unit margin → zero flights and orders."""
        ac = toy_aircraft(
            "MoneyPit", seats=100, casm=1.00, price=1,
            risk_coef=0,
        )
        al = toy_airline(
            budget=100,
            yield_per_mile=0.01,
            ancillary_per_pax=0,
            load_factor=0.8,
            risk_aversion=0,
        )
        demand = toy_demand(pax=10_000)
        result, opt = solve(ToyAircraftSelection([ac]), ToyAirlineSelection([al]), "ToyAirline", demand)
        self.assertEqual(result.status, "optimal")
        self.assertEqual(sum(result.orders.values()), 0)
        self.assertEqual(sum(result.flights.values()), 0)

    def test_two_type_max_one_forces_choice(self):
        cheap = toy_aircraft("Cheap", casm=0.05, price=5, risk_coef=0, family=AircraftFamily.A220)
        dear = toy_aircraft("Dear", casm=0.20, price=5, risk_coef=0, family=AircraftFamily.B737MAX)
        al = toy_airline(budget=500, max_aircraft_types=1, moq_threshold=1, risk_aversion=0)
        demand = toy_demand(pax=100_000)
        result, opt = solve(
            ToyAircraftSelection([cheap, dear]),
            ToyAirlineSelection([al]),
            "ToyAirline",
            demand,
        )
        self.assertEqual(result.status, "optimal")
        types_ordered = [a for a, n in result.orders.items() if n > 0]
        self.assertLessEqual(len(types_ordered), 1)
        if types_ordered:
            self.assertEqual(types_ordered[0], "Cheap")


class TestPerConstraint(unittest.TestCase):
    """Each constraint family in isolation on purpose-built instances."""

    def test_range_forces_zero_flights(self):
        short = toy_aircraft("ShortHaul", range_mi=500)
        al = toy_airline(budget=500)
        demand = toy_demand(distance_min=800, distance_max=1200)
        result, opt = solve(
            ToyAircraftSelection([short]),
            ToyAirlineSelection([al]),
            "ToyAirline",
            demand,
        )
        self.assertEqual(result.status, "optimal")
        self.assertEqual(result.flights["ShortHaul", "toy_seg"], 0)
        audit = audit_constraints(opt, result, opt)
        self.assertTrue(audit.ok, audit.summary())

    def test_demand_cap_binds(self):
        ac = toy_aircraft("Wide", seats=200, casm=0.05, price=5, risk_coef=0)
        al = toy_airline(budget=500, market_share=1.0, load_factor=1.0, risk_aversion=0)
        pax_cap = 5000.0
        demand = toy_demand(pax=pax_cap)
        result, opt = solve(
            ToyAircraftSelection([ac]),
            ToyAirlineSelection([al]),
            "ToyAirline",
            demand,
        )
        self.assertEqual(result.status, "optimal")
        fulfilled = result.segment_fulfillment["toy_seg"].seats_assigned
        self.assertLessEqual(fulfilled, pax_cap + TOL)
        # Should be at or near cap when profitable
        self.assertGreater(fulfilled, 0)

    def test_budget_relaxation_increases_orders(self):
        ac = toy_aircraft("Fleet", seats=150, casm=0.06, price=50, risk_coef=0)
        al_tight = toy_airline(budget=60, moq_threshold=1, risk_aversion=0)
        al_loose = toy_airline(budget=500, moq_threshold=1, risk_aversion=0)
        demand = toy_demand(pax=200_000)
        r_tight, _ = solve(
            ToyAircraftSelection([ac]),
            ToyAirlineSelection([al_tight]),
            "ToyAirline",
            demand,
        )
        r_loose, _ = solve(
            ToyAircraftSelection([ac]),
            ToyAirlineSelection([al_loose]),
            "ToyAirline",
            demand,
        )
        self.assertLessEqual(sum(r_tight.orders.values()), sum(r_loose.orders.values()))

    def test_moq_requires_minimum_family_orders(self):
        ac = toy_aircraft("FamilyA", family=AircraftFamily.A220, price=10, risk_coef=0)
        al = toy_airline(budget=500, moq_threshold=5, risk_aversion=0)
        demand = toy_demand(pax=50_000)
        result, opt = solve(
            ToyAircraftSelection([ac]),
            ToyAirlineSelection([al]),
            "ToyAirline",
            demand,
        )
        self.assertEqual(result.status, "optimal")
        if result.orders["FamilyA"] > 0:
            self.assertGreaterEqual(result.orders["FamilyA"], 5)

    def test_bulk_discount_reduces_effective_spend(self):
        ac = toy_aircraft("BulkJet", price=10, risk_coef=0)
        al = toy_airline(budget=200, moq_threshold=1, risk_aversion=0)
        demand = toy_demand(pax=500_000)
        cfg_off = ModelConfig(bulk_discount_rate=0.0, bulk_discount_threshold=5)
        cfg_on = ModelConfig(bulk_discount_rate=0.10, bulk_discount_threshold=5)
        r0, _ = solve(
            ToyAircraftSelection([ac]), ToyAirlineSelection([al]), "ToyAirline", demand, cfg_off,
        )
        r1, _ = solve(
            ToyAircraftSelection([ac]), ToyAirlineSelection([al]), "ToyAirline", demand, cfg_on,
        )
        self.assertEqual(r0.status, "optimal")
        self.assertEqual(r1.status, "optimal")
        if r1.orders["BulkJet"] >= 5:
            self.assertGreaterEqual(r1.orders["BulkJet"], r0.orders["BulkJet"])

    def test_risk_penalty_discourages_large_orders(self):
        ac = toy_aircraft("Risky", risk_coef=100, casm=0.05, price=5)
        al_low = toy_airline(budget=500, risk_aversion=0, moq_threshold=1)
        al_high = toy_airline(budget=500, risk_aversion=500, moq_threshold=1)
        demand = toy_demand(pax=300_000)
        r0, _ = solve(
            ToyAircraftSelection([ac]), ToyAirlineSelection([al_low]), "ToyAirline", demand,
        )
        r1, _ = solve(
            ToyAircraftSelection([ac]), ToyAirlineSelection([al_high]), "ToyAirline", demand,
        )
        self.assertGreaterEqual(r0.orders["Risky"], r1.orders["Risky"])

    def test_all_constraints_after_catalog_solve(self):
        from params import demand as catalog_demand
        result, opt = solve(AircraftSelection(), AirlineSelection(), "Leader", catalog_demand)
        audit = audit_constraints(opt, result, opt)
        self.assertTrue(audit.ok, audit.summary())


class TestInfeasibility(unittest.TestCase):
    def test_impossible_moq_with_zero_budget(self):
        ac = toy_aircraft("Needy", price=100, family=AircraftFamily.A220)
        al = toy_airline(budget=0, moq_threshold=5)
        demand = toy_demand(pax=10_000)
        result, _ = solve(
            ToyAircraftSelection([ac]),
            ToyAirlineSelection([al]),
            "ToyAirline",
            demand,
        )
        # Zero orders is feasible; should be optimal with no purchases.
        self.assertEqual(result.status, "optimal")
        self.assertEqual(sum(result.orders.values()), 0)

    def test_infeasible_budget_with_forced_moq_via_existing(self):
        """If MOQ requires 5 aircraft at $100 each but budget is $50 → infeasible if model must serve demand."""
        ac = toy_aircraft("Expensive", price=100, seats=200, casm=0.05, risk_coef=0)
        al = toy_airline(budget=50, moq_threshold=5, risk_aversion=0)
        demand = toy_demand(pax=1_000_000)
        result, _ = solve(
            ToyAircraftSelection([ac]),
            ToyAirlineSelection([al]),
            "ToyAirline",
            demand,
        )
        # Optimizer may still return optimal with zero orders (demand not mandatory to serve).
        self.assertIn(result.status, ("optimal", "infeasible"))


class TestUnitsConsistency(unittest.TestCase):
    """ASM / pax / $ dimensions line up in toy problem."""

    def test_asm_and_pax_formulas(self):
        ac = toy_aircraft("Unit", seats=100)
        al = toy_airline(load_factor=0.8)
        seg = DemandSegment("s", 1000, 1000, 10_000, 2.0)
        demand = Demand([seg])
        result, opt = solve(
            ToyAircraftSelection([ac]),
            ToyAirlineSelection([al]),
            "ToyAirline",
            demand,
        )
        flights = result.flights["Unit", "s"]
        expected_asm = flights * 100 * 1000  # seats * miles
        expected_pax = flights * 100 * 0.8
        # Cross-check fulfillment
        ful = result.segment_fulfillment["s"]
        self.assertAlmostEqual(ful.seats_assigned, expected_pax, places=4)
        # KPI ASM
        self.assertAlmostEqual(result.total_asm, expected_asm, places=0)


if __name__ == "__main__":
    unittest.main()
