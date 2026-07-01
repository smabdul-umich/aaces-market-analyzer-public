#!/usr/bin/env python3
"""
Run the full model verification & validation suite and print a summary report.

Usage:
    python tests/run_model_tests.py
    python tests/run_model_tests.py -v
"""

from __future__ import annotations

import argparse
import sys
import time
import unittest
from io import StringIO

# Ensure repo root is on path when invoked as script
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run_suite(verbosity: int = 1) -> unittest.TestResult:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for module in (
        "tests.test_verification",
        "tests.test_validation",
        "tests.test_robustness",
    ):
        suite.addTests(loader.loadTestsFromName(module))
    stream = sys.stdout if verbosity > 1 else StringIO()
    runner = unittest.TextTestRunner(verbosity=verbosity, stream=stream)
    return runner.run(suite)


def _print_diagnostic_sample() -> None:
    from params import AircraftSelection, AirlineSelection, demand
    from tests.model_harness import aircraft_selection_diagnostics, audit_constraints, solve

    print("\n" + "=" * 72)
    print("SAMPLE DIAGNOSTIC — Leader baseline (first 8 lines)")
    print("=" * 72)
    result, opt = solve(AircraftSelection(), AirlineSelection(), "Leader", demand)
    for line in aircraft_selection_diagnostics(opt, result)[:8]:
        print(line)
    audit = audit_constraints(opt, result, opt)
    print(f"\nConstraint audit: {audit.summary()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run fleet model V&V test suite")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--no-diagnostics", action="store_true")
    args = parser.parse_args()

    print("AACES Fleet Model — Verification & Validation Suite")
    print("=" * 72)
    t0 = time.perf_counter()
    result = _run_suite(verbosity=2 if args.verbose else 1)
    elapsed = time.perf_counter() - t0

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  Tests run   : {result.testsRun}")
    print(f"  Failures    : {len(result.failures)}")
    print(f"  Errors      : {len(result.errors)}")
    print(f"  Skipped     : {len(result.skipped)}")
    print(f"  Elapsed     : {elapsed:.1f}s")

    if result.failures:
        print("\n--- FAILURES ---")
        for test, trace in result.failures:
            print(f"\n{test}:")
            print(trace)

    if result.errors:
        print("\n--- ERRORS ---")
        for test, trace in result.errors:
            print(f"\n{test}:")
            print(trace)

    if not args.no_diagnostics and not result.errors:
        _print_diagnostic_sample()

    print("\n--- KNOWN MODEL PROPERTIES (not test failures) ---")
    print("  • Acquisition price enters the budget constraint only, not the objective.")
    print("  • Serving demand is optional — zero orders is feasible when margin is negative.")
    print("  • Concept_A risk_coef=268 in params.py can dominate sensitivity-study outcomes.")
    print("  • Leader new-build orders can jump discretely under ±2% demand (MIQP switching).")

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
