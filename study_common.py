# study_common.py
"""
Shared machinery for the novel-aircraft-concept fleet-acquisition sensitivity studies.

Each individual study (``study1_sensitivity.py``, ``study2_sensitivity.py``,
…) only needs to declare:

    * which aircraft are eligible (an ``aircraft_filter``)
    * which of those are "conventional" (used for tidy result columns)
    * a label and slug for headers / output files

Everything else — airline, demand, sweep grid, scenario factories,
inspection logic, CLI, CSV output — lives here so the studies stay
trivial to read and stay in lock-step with each other.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from miqp_portfolio import SolverResult
from params import Aircraft, AircraftSelection, AirlineSelection, Demand, DemandSegment
from scenarios import Scenario, ScenarioRunner


# ── Shared identifiers ────────────────────────────────────────────
# These are names of entities defined in params.py, not parameter values.

CONCEPT_AIRCRAFT = "Concept_A"        # the concept type under study; defined in params.Aircrafts
STUDY_AIRLINE    = "Study1_Airline"   # reused by every study; defined in params.Airlines


# ── Single source of truth for base values ────────────────────────
# Base attribute values are read straight from the Concept_A definition in
# params.py — never hard-coded here.  To change a base value for a study,
# edit params.py (overriding params.py for a specific study is expected and
# valid).  This guarantees a sweep at fraction 1.0 (or seat delta 0) exactly
# reproduces the catalogue baseline.
_CATALOG   = AircraftSelection()
BASE_CASM  = _CATALOG.casm(CONCEPT_AIRCRAFT)
BASE_PRICE = _CATALOG.price(CONCEPT_AIRCRAFT)
BASE_SEATS = _CATALOG.seats(CONCEPT_AIRCRAFT)

# Sweep grids.  CASM and price sweeps are multiplicative (fraction × base);
# the seat sweep is additive (base + delta) since seats are an integer count.
SWEEP_FRACTIONS: List[float] = [0.88, 0.89, 0.90, 0.91, 0.92, 0.93, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99,
                                1.00,
                                1.10, 1.20, 1.30, 1.40, 1.50]
SEATS_DELTAS: List[int] = [-20, -15, -10, -5, 0, 5, 10, 15, 20]


# ── Shared demand: single bucket, ~6.5M pax, ~1500 mi midpoint, 3-hr block ─

study_demand = Demand([
    DemandSegment(
        name="single_bucket",
        distance_min=1200,
        distance_max=1800,
        demand=6_500_000,
        block_time=3.0,
    ),
])


# ── Per-study configuration ───────────────────────────────────────

@dataclass(frozen=True)
class StudyConfig:
    """Bundle of everything a study needs to specify.

    Attributes
    ----------
    label : str
        Used in printed headers (e.g. ``"STUDY 1"``).
    description : str
        One-line description for CLI ``--help``.
    aircraft_filter : Callable
        Restricts the solver's aircraft choice set.  Returns ``True`` for
        every aircraft that may appear in this study.
    conventional_aircrafts : tuple of str
        Names of the conventional (non-concept) aircraft in the study.
        Used to add one ``<name>_orders`` column per type to sweep summaries.
    output_dir : Path
        Where CSVs are written when sweeps run.
    slug : str
        Short, filesystem-safe identifier used as the CSV filename prefix
        (e.g. ``"study1"`` → ``study1_casm_sweep.csv``).
    """
    label: str
    description: str
    aircraft_filter: Callable[[Aircraft], bool]
    conventional_aircrafts: Tuple[str, ...]
    output_dir: Path
    slug: str


# ── Single-case scenario factories ────────────────────────────────
#
# These build the ``Scenario`` objects used by both single-case
# inspection (``inspect_case``) and the sweeps (``build_*_sweep``).
# Keeping them as the single source of truth means inspection and sweep
# share byte-identical override values for the same fraction.

def _concept_override(attribute: str, fraction: float, base: float) -> float:
    """Return the absolute parameter value for a sweep point given a multiplier."""
    decimals = 4 if attribute == "casm" else 2
    return round(fraction * base, decimals)


def make_baseline_scenario() -> Scenario:
    """Concept_A at its catalogue defaults (the 100%/100% point)."""
    return Scenario(label="baseline (Concept_A @ 100% CASM, 100% price)")


def make_casm_scenario(fraction: float) -> Scenario:
    """Concept_A's CASM set to ``fraction × BASE_CASM`` (price untouched)."""
    return Scenario(
        label=f"casm={fraction:.0%}_of_base",
        aircraft_overrides={
            CONCEPT_AIRCRAFT: {"casm": _concept_override("casm", fraction, BASE_CASM)},
        },
    )


def make_price_scenario(fraction: float) -> Scenario:
    """Concept_A's price set to ``fraction × BASE_PRICE`` (CASM untouched)."""
    return Scenario(
        label=f"price={fraction:.0%}_of_base",
        aircraft_overrides={
            CONCEPT_AIRCRAFT: {"price": _concept_override("price", fraction, BASE_PRICE)},
        },
    )


def make_seats_scenario(delta: int) -> Scenario:
    """Concept_A's seat count set to ``BASE_SEATS + delta`` (everything else untouched)."""
    return Scenario(
        label=f"seats=base{delta:+d}",
        aircraft_overrides={
            CONCEPT_AIRCRAFT: {"seats": BASE_SEATS + delta},
        },
    )


def build_casm_sweep() -> List[Scenario]:
    """Sweep Concept_A's CASM over ``SWEEP_FRACTIONS × base``, holding price and seats constant."""
    return [make_casm_scenario(f) for f in SWEEP_FRACTIONS]


def build_price_sweep() -> List[Scenario]:
    """Sweep Concept_A's acquisition cost over ``SWEEP_FRACTIONS × base``, holding CASM and seats constant."""
    return [make_price_scenario(f) for f in SWEEP_FRACTIONS]


def build_seats_sweep() -> List[Scenario]:
    """Sweep Concept_A's seat count over ``base + SEATS_DELTAS``, holding everything else constant."""
    return [make_seats_scenario(d) for d in SEATS_DELTAS]


# ── Result aggregation ────────────────────────────────────────────

def _chosen_aircraft(orders: Dict[str, int]) -> str:
    """Return the (single) aircraft name that was ordered, or ``'none'``.

    With ``max_aircraft_types=1`` exactly one aircraft should be ordered.
    Returns ``'multiple (unexpected: ...)'`` if more than one shows up so
    a misconfigured study is loud rather than silently confusing.
    """
    chosen = [name for name, count in orders.items() if count > 0]
    if not chosen:
        return "none"
    if len(chosen) == 1:
        return chosen[0]
    return f"multiple (unexpected: {','.join(sorted(chosen))})"


def summarise_sweep(
    results: Dict[str, SolverResult],
    sweep_inputs: Sequence,
    sweep_values: Sequence,
    conventional_aircrafts: Sequence[str],
    *,
    input_column_name: str = "fraction_of_base",
) -> pd.DataFrame:
    """Build a tidy DataFrame from a sweep's results.

    Parameters
    ----------
    results
        Mapping of scenario label → ``SolverResult`` (one per sweep point).
    sweep_inputs
        Ordered sweep-axis inputs (e.g. fractions ``[0.5, 0.6, …]`` for CASM/price,
        deltas ``[-20, -15, …]`` for seats).  Stored in column ``input_column_name``.
    sweep_values
        The corresponding *absolute* parameter values applied at each point
        (e.g. ``[0.06, 0.072, …]`` for CASM, ``[169, 174, …]`` for seats).
        Stored in column ``swept_value``.
    conventional_aircrafts
        Names of the conventional (non-concept) aircraft in this study; one
        ``<name>_orders`` column is produced per name.
    input_column_name
        Name of the sweep-axis column.  Defaults to ``"fraction_of_base"``
        for CASM/price sweeps; pass e.g. ``"delta_from_base"`` for seats.
    """
    if not (len(sweep_inputs) == len(sweep_values) == len(results)):
        raise ValueError(
            f"sweep length mismatch: {len(sweep_inputs)} inputs, "
            f"{len(sweep_values)} values, {len(results)} results "
            "(duplicate scenario labels collapse the results dict)."
        )

    rows: List[Dict[str, object]] = []
    for sw_in, sw_val, (_label, result) in zip(sweep_inputs, sweep_values, results.items()):
        row: Dict[str, object] = {
            input_column_name: sw_in,
            "swept_value":     sw_val,
            "concept_orders":  result.orders.get(CONCEPT_AIRCRAFT, 0),
        }
        for name in conventional_aircrafts:
            row[f"{name}_orders"] = result.orders.get(name, 0)
        row.update({
            "chosen_aircraft":     _chosen_aircraft(result.orders),
            "total_profit":        result.total_profit if result.objective is not None else float("nan"),
            "concept_penetration": result.concept_penetration,
            "weighted_casm":       result.weighted_casm,
            "status":              result.status,
        })
        rows.append(row)
    return pd.DataFrame(rows)


def find_concept_choice_range(df: pd.DataFrame) -> Optional[Tuple[float, float]]:
    """Return ``(min, max)`` of ``swept_value`` over rows where Concept_A was chosen.

    Sweep-direction-agnostic so it works for any axis:

    * For monotonic sweeps where the concept wins **below** a threshold (CASM,
      price), the upper bound *is* the critical threshold.
    * For monotonic sweeps where the concept wins **above** a threshold (seats,
      when the concept carries higher risk), the lower bound *is* the critical
      threshold.

    Returns ``None`` if the concept was never chosen across the swept range.
    """
    concept_rows = df[df["chosen_aircraft"] == CONCEPT_AIRCRAFT]
    if concept_rows.empty:
        return None
    return (float(concept_rows["swept_value"].min()),
            float(concept_rows["swept_value"].max()))


# ── Runner factory ────────────────────────────────────────────────

def make_runner(config: StudyConfig) -> ScenarioRunner:
    """Build the ``ScenarioRunner`` used by both sweeps and inspection.

    Centralising this guarantees that ``inspect_case`` and ``run_sweeps``
    solve the *same* model — anything else is a bug.
    """
    return ScenarioRunner(
        airline_name    = STUDY_AIRLINE,
        demand          = study_demand,
        aircraft_filter = config.aircraft_filter,
    )


# ── Single-case inspection ────────────────────────────────────────

def inspect_case(
    config: StudyConfig,
    scenario: Scenario,
    *,
    verbose: bool = False,
) -> SolverResult:
    """Run ONE scenario through ``config`` and print its full summary.

    Use this to zoom into a single test point — e.g. the baseline, or a
    specific point on the CASM/price sweep — and see per-aircraft
    utilization, segment fulfillment, financials, and concept share at
    the level of detail ``SolverResult.summary()`` produces.
    """
    runner = make_runner(config)

    header = f" {config.label} CASE INSPECTION: {scenario.label} "
    print("=" * 88)
    print(header.center(88, "─"))
    print("=" * 88)

    if scenario.aircraft_overrides:
        print("Aircraft overrides:")
        for aircraft, attrs in scenario.aircraft_overrides.items():
            for attr, value in attrs.items():
                print(f"  {aircraft}.{attr} = {value}")
    else:
        print("Aircraft overrides: (none — catalogue defaults)")
    print()

    result = runner.run_one(scenario, verbose=verbose)
    print(result.summary())
    print()
    return result


# ── Top-level sweep runner ────────────────────────────────────────

def _run_one_sweep(
    runner: ScenarioRunner,
    *,
    section_label: str,        # e.g. "STUDY 1.A"
    section_title: str,        # e.g. "Concept_A CASM sweep   (acquisition cost & risk held constant)"
    sweep_name: str,           # e.g. "CASM"  — used in summary line and headers
    scenarios: List[Scenario],
    sweep_inputs: Sequence,
    sweep_values: Sequence,
    input_column_name: str,
    value_format: str,         # format spec for printing min/max swept_value
    conventional_aircrafts: Sequence[str],
) -> pd.DataFrame:
    """Solve one sweep, print its comparison table + tidy summary, return the DataFrame."""
    print("=" * 88)
    print(f"{section_label} — {section_title}")
    print("=" * 88)

    results = runner.run(scenarios)
    print(ScenarioRunner.compare(results))

    df = summarise_sweep(
        results, sweep_inputs, sweep_values,
        conventional_aircrafts,
        input_column_name=input_column_name,
    )

    print()
    print(f"Sweep summary ({sweep_name}):")
    print(df.to_string(index=False))

    rng = find_concept_choice_range(df)
    if rng is None:
        print(f"\n  → Concept_A was never chosen across the swept {sweep_name} range.")
    else:
        lo, hi = rng
        if lo == hi:
            print(f"\n  → Concept_A chosen at exactly one {sweep_name} value: {lo:{value_format}}.")
        else:
            print(f"\n  → Concept_A chosen at {sweep_name} values in "
                  f"[{lo:{value_format}}, {hi:{value_format}}].")
    print()
    return df


def run_sweeps(
    config: StudyConfig,
    *,
    write_csvs: bool = True,
) -> Dict[str, pd.DataFrame]:
    """Run all sensitivity sweeps for ``config`` and return summary DataFrames."""
    runner = make_runner(config)

    # Pre-compute absolute values so the summary tables show the actual
    # parameter values applied at each sweep point (not just the inputs).
    casm_values  = [round(f * BASE_CASM, 4) for f in SWEEP_FRACTIONS]
    price_values = [round(f * BASE_PRICE, 2) for f in SWEEP_FRACTIONS]
    seats_values = [BASE_SEATS + d              for d in SEATS_DELTAS]

    # ── Sweep A: CASM ────────────────────────────────────────────
    casm_df = _run_one_sweep(
        runner,
        section_label          = f"{config.label}.A",
        section_title          = "Concept_A CASM sweep   (acquisition cost, seats & risk held constant)",
        sweep_name             = "CASM",
        scenarios              = build_casm_sweep(),
        sweep_inputs           = SWEEP_FRACTIONS,
        sweep_values           = casm_values,
        input_column_name      = "fraction_of_base",
        value_format           = ".4f",
        conventional_aircrafts = config.conventional_aircrafts,
    )

    # ── Sweep B: acquisition cost ────────────────────────────────
    price_df = _run_one_sweep(
        runner,
        section_label          = f"{config.label}.B",
        section_title          = "Concept_A acquisition-cost sweep   (CASM, seats & risk held constant)",
        sweep_name             = "price",
        scenarios              = build_price_sweep(),
        sweep_inputs           = SWEEP_FRACTIONS,
        sweep_values           = price_values,
        input_column_name      = "fraction_of_base",
        value_format           = ".2f",
        conventional_aircrafts = config.conventional_aircrafts,
    )

    # If the price sweep is perfectly flat, the model isn't actually
    # sensitive to acquisition cost in this configuration — flag it so
    # the user knows why before drawing conclusions from the table.
    if price_df["chosen_aircraft"].nunique() == 1 and price_df["total_profit"].nunique() == 1:
        budget = AirlineSelection().budget(STUDY_AIRLINE)
        print("  [DIAGNOSTIC] The price sweep is flat (same aircraft & same profit at every point).")
        print("  In the current MIQP, `price` enters only the budget constraint, not the objective")
        print("  (see `_add_budget_constraint` in miqp_portfolio.py).  When the budget is")
        print(f"  non-binding, the optimum is insensitive to Concept_A's price.  {STUDY_AIRLINE}'s")
        print(f"  budget is currently {budget:g} (units of $M).  To make this sweep informative, either:")
        print(f"    (a) lower `{STUDY_AIRLINE}.budget` in params.py until it binds, or")
        print("    (b) extend miqp_portfolio.py to include `price * orders` in the objective.")
        print()

    # ── Sweep C: seat count ──────────────────────────────────────
    # Note the *direction* flip vs CASM/price: the concept wins (when at all)
    # at HIGH seat counts, because more seats per aircraft → fewer
    # aircraft needed → less risk-cost penalty (which scales with N²).
    seats_df = _run_one_sweep(
        runner,
        section_label          = f"{config.label}.C",
        section_title          = "Concept_A seat-count sweep   (CASM, price & risk held constant)",
        sweep_name             = "seats",
        scenarios              = build_seats_sweep(),
        sweep_inputs           = SEATS_DELTAS,
        sweep_values           = seats_values,
        input_column_name      = "delta_from_base",
        value_format           = ".0f",
        conventional_aircrafts = config.conventional_aircrafts,
    )

    # ── Persist tidy CSVs for downstream plotting ────────────────
    if write_csvs:
        config.output_dir.mkdir(exist_ok=True)
        casm_path  = config.output_dir / f"{config.slug}_casm_sweep.csv"
        price_path = config.output_dir / f"{config.slug}_price_sweep.csv"
        seats_path = config.output_dir / f"{config.slug}_seats_sweep.csv"
        casm_df.to_csv(casm_path,   index=False)
        price_df.to_csv(price_path, index=False)
        seats_df.to_csv(seats_path, index=False)
        cwd = Path.cwd()
        for path in (casm_path, price_path, seats_path):
            shown = path.relative_to(cwd) if path.is_relative_to(cwd) else path
            print(f"[INFO] Wrote {shown}")

    return {"casm": casm_df, "price": price_df, "seats": seats_df}


# ── CLI ───────────────────────────────────────────────────────────

def _resolve_inspect_scenario(spec: str) -> Scenario:
    """Parse an ``--inspect`` argument into a Scenario.

    Accepted forms:
      ``baseline``            -> catalogue defaults
      ``casm:<fraction>``     -> Concept_A CASM at <fraction> × base       (e.g. ``casm:0.9``)
      ``price:<fraction>``    -> Concept_A price at <fraction> × base      (e.g. ``price:0.5``)
      ``seats:<delta>``       -> Concept_A seats at base + <delta> seats   (e.g. ``seats:-20``, ``seats:+5``)
    """
    spec = spec.strip().lower()
    if spec == "baseline":
        return make_baseline_scenario()
    if ":" in spec:
        kind, raw = spec.split(":", 1)
        if kind == "seats":
            try:
                delta = int(raw)
            except ValueError as exc:
                raise SystemExit(
                    f"--inspect: could not parse seats delta in {spec!r} "
                    f"(expected an integer like -20, 0, +5)"
                ) from exc
            return make_seats_scenario(delta)
        try:
            fraction = float(raw)
        except ValueError as exc:
            raise SystemExit(f"--inspect: could not parse fraction in {spec!r}") from exc
        if kind == "casm":
            return make_casm_scenario(fraction)
        if kind == "price":
            return make_price_scenario(fraction)
    raise SystemExit(
        f"--inspect: unrecognised case {spec!r}. "
        f"Expected one of: baseline | casm:<fraction> | price:<fraction> | seats:<delta>"
    )


def _build_arg_parser(config: StudyConfig, prog_name: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog_name,
        description=f"{config.label} — {config.description}",
        epilog=(
            "Examples:\n"
            f"  python {prog_name}                       # all sweeps + write CSVs\n"
            f"  python {prog_name} --inspect baseline    # only the baseline summary\n"
            f"  python {prog_name} --inspect casm:0.9    # CASM sweep point at 90%% of base\n"
            f"  python {prog_name} --inspect price:0.5   # price sweep point at 50%% of base\n"
            f"  python {prog_name} --inspect seats:-20   # seats sweep point at base - 20 seats\n"
            f"  python {prog_name} --inspect seats:+15   # seats sweep point at base + 15 seats\n"
            f"  python {prog_name} --no-sweeps           # skip sweeps (use with --inspect)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--inspect", metavar="CASE", default=None,
        help="Zoom into a single case and print its full SolverResult.summary(). "
             "CASE = baseline | casm:<fraction> | price:<fraction> | seats:<delta>.",
    )
    parser.add_argument(
        "--no-sweeps", action="store_true",
        help="Skip the CASM, price, and seats sweeps (only meaningful with --inspect).",
    )
    parser.add_argument(
        "--no-csv", action="store_true",
        help=f"Do not write per-sweep CSVs to {config.output_dir.name}/.",
    )
    parser.add_argument(
        "--verbose-solver", action="store_true",
        help="Show Gurobi solver output (otherwise suppressed).",
    )
    return parser


def run_cli(config: StudyConfig, prog_name: str) -> None:
    """Top-level CLI entry point.  Each study's ``__main__`` calls this once."""
    args = _build_arg_parser(config, prog_name).parse_args()

    if not args.no_sweeps:
        run_sweeps(config, write_csvs=not args.no_csv)

    if args.inspect is not None:
        scenario = _resolve_inspect_scenario(args.inspect)
        inspect_case(config, scenario, verbose=args.verbose_solver)
    elif args.no_sweeps:
        # Nothing to do — sweeps off and no inspection requested.
        # Default to baseline so the script always produces output.
        inspect_case(config, make_baseline_scenario(), verbose=args.verbose_solver)
