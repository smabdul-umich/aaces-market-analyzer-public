# test_solver.py
"""
Test script for the fleet-optimization solver and scenario runner.

Run from the terminal:
    python test_solver.py

Usage notes
-----------
The standard way to interact with the solver is through ``Scenario`` and
``ScenarioRunner``.  A ``Scenario("baseline")`` with no overrides runs
the model with raw defaults from ``params.py``.

For advanced or debugging use, the solver can also be invoked directly::

    from params import AircraftSelection, AirlineSelection, demand
    from miqp_portfolio import FleetOptimizer

    optimizer = FleetOptimizer(
        aircrafts=AircraftSelection(),
        airlines=AirlineSelection(),
        airline_name="Leader",
        demand=demand,
    )
    result = optimizer.solve(verbose=True)
    print(result.summary())
"""

from params import demand
from scenarios import Scenario, ScenarioRunner, PRESETS


AIRLINE = "Leader"
runner = ScenarioRunner(airline_name=AIRLINE, demand=demand)


# ── 1. Base model run (no overrides, raw defaults) ──────────────

def test_base_model():
    print("=" * 70)
    print("1. BASE MODEL RUN")
    print("=" * 70)

    result = runner.run_one(Scenario("baseline"), verbose=True)
    print(result.summary())
    print()
    return result


# ── 2. Single custom scenario ───────────────────────────────────

def test_single_scenario():
    print("=" * 70)
    print("2. SINGLE CUSTOM SCENARIO (concept subsidized)")
    print("=" * 70)

    result = runner.run_one(Scenario(
        label="concept subsidized",
        aircraft_overrides={
            "Concept_A": {"price_adjustment": -3.0, "casm_adjustment": -0.01},
            "Concept_B": {"price_adjustment": -3.0},
        },
    ))
    print(result.summary())
    print()
    return result


# ── 3. Preset: concept subsidy sweep ───────────────────────────

def test_subsidy_sweep():
    print("=" * 70)
    print("3. PRESET: CONCEPT SUBSIDY SWEEP")
    print("=" * 70)

    results = runner.run(PRESETS["concept_subsidy_sweep"])
    print(ScenarioRunner.compare(results))
    print()
    return results


# ── 4. Preset: concept CASM sweep ──────────────────────────────

def test_casm_sweep():
    print("=" * 70)
    print("4. PRESET: CONCEPT CASM SWEEP")
    print("=" * 70)

    results = runner.run(PRESETS["concept_casm_sweep"])
    print(ScenarioRunner.compare(results))
    print()
    return results


# ── 5. Preset: demand sensitivity ──────────────────────────────

def test_demand_sensitivity():
    print("=" * 70)
    print("5. PRESET: DEMAND SENSITIVITY")
    print("=" * 70)

    results = runner.run(PRESETS["demand_sensitivity"])
    print(ScenarioRunner.compare(results))
    print()
    return results


# ── 6. Preset: budget sweep ────────────────────────────────────

def test_budget_sweep():
    print("=" * 70)
    print("6. PRESET: BUDGET SWEEP")
    print("=" * 70)

    results = runner.run(PRESETS["budget_sweep"])
    print(ScenarioRunner.compare(results))
    print()
    return results


# ── 7. Custom sweep with baseline comparison ───────────────────

def test_custom_sweep():
    print("=" * 70)
    print("7. CUSTOM SWEEP: CONCEPT CASM VALUES WITH BASELINE")
    print("=" * 70)

    scenarios = [Scenario("baseline")] + Scenario.sweep(
        attribute="casm",
        aircrafts=["Concept_A", "Concept_B", "Concept_C"],
        values=[0.05, 0.06, 0.07, 0.09, 0.10],
        label_prefix="concept_casm",
    )
    results = runner.run(scenarios)
    print(ScenarioRunner.compare(results))
    print()
    return results


# ── Run all tests ───────────────────────────────────────────────

if __name__ == "__main__":
    test_base_model()
    test_single_scenario()
    test_subsidy_sweep()
    test_casm_sweep()
    test_demand_sensitivity()
    test_budget_sweep()
    test_custom_sweep()

    print("All tests completed.")
