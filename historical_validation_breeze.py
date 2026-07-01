from __future__ import annotations

"""Breeze A220 partial historical validation.

This script validates the fleet-acquisition MILP against a Breeze-like
historical case using:

1. a user-provided schedule network CSV (see ``data/README.md``), and
2. calibrated economic inputs for quantities not publicly disclosed.

Outputs are written to ``outputs/historical_validation`` as CSV and Markdown.
"""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd

from params import (
    AircraftSelection,
    AirlineSelection,
    Airlines,
    Demand,
    DemandSegment,
    Fleets,
    ModelConfig,
)
from miqp_portfolio import FleetOptimizer, SolverResult


@dataclass(frozen=True)
class ValidationConfig:
    annual_passengers_2024: int = 4_200_000
    annual_revenue_2024: int = 680_000_000
    base_load_factor: float = 0.82
    base_ancillary_per_pax: float = 10.0
    base_max_aircraft_types: int = 1
    base_moq_threshold: int = 5
    budget_buffer: float = 1.10
    budget_sweep_factors: tuple[float, ...] = (0.85, 1.00, 1.15)
    mip_gap: float = 1e-4
    block_speed_mph: float = 400.0
    turnaround_hours: float = 0.5


CONFIG = ValidationConfig()

CANDIDATE_AIRCRAFT = [
    "A220-300",
    "E190",
    "E195",
    "A319Neo",
    "A320Neo",
    "B737Max7",
    "B737Max8",
]

BREEZE_AIRCRAFT_OVERRIDES = {
    "A220-300": {"seats": 137, "casm": 0.1180},
    "E190": {"seats": 108, "casm": 0.1230},
    "E195": {"seats": 122, "casm": 0.1215},
    "A319Neo": {"casm": 0.1210},
    "A320Neo": {"casm": 0.1195},
    "B737Max7": {"casm": 0.1205},
    "B737Max8": {"casm": 0.1195},
}


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def outputs_dir() -> Path:
    path = repo_root() / "outputs" / "historical_validation"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_schedule_network(csv_path: Path) -> pd.DataFrame:
    """Load a route-level schedule CSV and aggregate to directed segments.

    See ``data/README.md`` for the required column schema.
    """
    raw = pd.read_csv(csv_path, low_memory=False)
    raw["NFlts"] = pd.to_numeric(raw["NFlts"], errors="coerce").fillna(0.0)
    raw["seats"] = pd.to_numeric(raw["seats"], errors="coerce").fillna(0.0)
    raw["distance"] = pd.to_numeric(raw["distance"], errors="coerce").fillna(0.0)
    raw = raw[(raw["NFlts"] > 0) & (raw["seats"] > 0) & (raw["distance"] > 0)].copy()

    grouped = (
        raw.groupby(["depapt", "arrapt"], as_index=False)
        .agg(
            distance=("distance", "max"),
            seat_supply_sample=("seats", lambda s: (s * raw.loc[s.index, "NFlts"]).sum()),
        )
    )
    grouped = grouped[grouped["seat_supply_sample"] > 0].copy()
    grouped["share"] = grouped["seat_supply_sample"] / grouped["seat_supply_sample"].sum()
    grouped["annual_passenger_demand"] = grouped["share"] * CONFIG.annual_passengers_2024
    grouped["block_time"] = grouped["distance"] / CONFIG.block_speed_mph + CONFIG.turnaround_hours
    grouped["segment_name"] = grouped["depapt"] + "-" + grouped["arrapt"]
    return grouped


def build_demand(route_df: pd.DataFrame) -> Demand:
    segments: List[DemandSegment] = []
    for row in route_df.itertuples(index=False):
        distance = float(row.distance)
        segments.append(
            DemandSegment(
                name=str(row.segment_name),
                distance_min=distance,
                distance_max=distance,
                demand=float(row.annual_passenger_demand),
                block_time=float(row.block_time),
            )
        )
    return Demand(segments)


def zero_fleet() -> object:
    fleet_type = type(Fleets.Leader.value)
    return fleet_type(**{field: 0 for field in fleet_type.__dataclass_fields__})


def validation_aircraft_selection(candidate_names: Iterable[str] | None = None) -> AircraftSelection:
    names = set(candidate_names or CANDIDATE_AIRCRAFT)
    aircrafts = AircraftSelection(lambda aircraft: aircraft.name in names)
    overrides = {
        name: attrs
        for name, attrs in BREEZE_AIRCRAFT_OVERRIDES.items()
        if name in names
    }
    if overrides:
        aircrafts.apply_mofd(overrides)
    return aircrafts


def weighted_stage_length(route_df: pd.DataFrame) -> float:
    return float((route_df["share"] * route_df["distance"]).sum())


def calibrated_yield_per_mile(route_df: pd.DataFrame) -> float:
    avg_stage_len = weighted_stage_length(route_df)
    revenue_per_pax = CONFIG.annual_revenue_2024 / CONFIG.annual_passengers_2024
    return max((revenue_per_pax - CONFIG.base_ancillary_per_pax) / avg_stage_len, 0.0)


def calibrated_budget(aircrafts: AircraftSelection, route_df: pd.DataFrame) -> tuple[float, pd.DataFrame]:
    max_distance = float(route_df["distance"].max())
    avg_block_time = float((route_df["share"] * route_df["block_time"]).sum())
    rows = []

    for aircraft_name in aircrafts.names:
        max_range = aircrafts.range(aircraft_name)
        feasible = max_range >= max_distance
        if not feasible:
            rows.append(
                {
                    "aircraft": aircraft_name,
                    "feasible_all_routes": False,
                    "required_aircraft_est": math.nan,
                    "estimated_capex_musd": math.nan,
                    "price_musd": aircrafts.price(aircraft_name),
                    "seats": aircrafts.seats(aircraft_name),
                    "yearly_block_hours": aircrafts.yearly_block_hours(aircraft_name),
                    "range_nm": max_range,
                }
            )
            continue

        pax_per_aircraft = (
            aircrafts.yearly_block_hours(aircraft_name)
            / avg_block_time
            * aircrafts.seats(aircraft_name)
            * CONFIG.base_load_factor
        )
        required_aircraft = math.ceil(CONFIG.annual_passengers_2024 / pax_per_aircraft)
        rows.append(
            {
                "aircraft": aircraft_name,
                "feasible_all_routes": True,
                "required_aircraft_est": required_aircraft,
                "estimated_capex_musd": required_aircraft * aircrafts.price(aircraft_name),
                "price_musd": aircrafts.price(aircraft_name),
                "seats": aircrafts.seats(aircraft_name),
                "yearly_block_hours": aircrafts.yearly_block_hours(aircraft_name),
                "range_nm": max_range,
            }
        )

    table = pd.DataFrame(rows).sort_values(
        ["feasible_all_routes", "estimated_capex_musd"],
        ascending=[False, True],
    )
    feasible = table[table["feasible_all_routes"] == True]
    if feasible.empty:
        raise RuntimeError("No candidate aircraft can cover the observed Breeze network.")
    budget = float(feasible["estimated_capex_musd"].max()) * CONFIG.budget_buffer
    return budget, table


def make_breeze_like_airlines(budget: float, yield_per_mile: float) -> AirlineSelection:
    airlines = AirlineSelection(lambda airline: airline.name == "Leader")
    airlines.apply_mofd(
        {
            "Leader": {
                "budget": budget,
                "risk_aversion": Airlines.Leader.value.risk_aversion,
                "load_factor": CONFIG.base_load_factor,
                "market_share": 1.0,
                "yield_per_mile": yield_per_mile,
                "ancillary_per_pax": CONFIG.base_ancillary_per_pax,
                "fleet": zero_fleet(),
                "moq_threshold": CONFIG.base_moq_threshold,
                "max_aircraft_types": CONFIG.base_max_aircraft_types,
            }
        }
    )
    return airlines


def validation_model_config() -> ModelConfig:
    return ModelConfig(
        mip_gap=CONFIG.mip_gap,
        bulk_discount_rate=0.0,
    )


def estimated_acquisition_cost(result: SolverResult, aircrafts: AircraftSelection) -> float:
    return sum(
        aircrafts.price(name, apply_adjustments=True) * count
        for name, count in result.orders.items()
        if count > 0
    )


def summarize_result(result: SolverResult, aircrafts: AircraftSelection) -> Dict[str, object]:
    selected_orders = {name: count for name, count in result.orders.items() if count > 0}
    dominant_type = max(selected_orders, key=selected_orders.get) if selected_orders else None
    return {
        "status": result.status,
        "objective": result.objective,
        "selected_types": len(selected_orders),
        "selected_orders": selected_orders,
        "dominant_type": dominant_type,
        "a220_selected": "A220-300" in selected_orders,
        "a220_orders": int(selected_orders.get("A220-300", 0)),
        "total_orders": int(sum(selected_orders.values())),
        "total_asm": result.total_asm,
        "weighted_casm": result.weighted_casm,
        "revenue": result.revenue,
        "operating_cost": result.operating_cost,
        "fixed_cost": result.fixed_cost,
        "acquisition_cost": estimated_acquisition_cost(result, aircrafts),
        "risk_cost": result.risk_cost,
        "bulk_discount_savings": result.bulk_discount_savings,
    }


def solve_case(route_df: pd.DataFrame, budget: float, candidates: Iterable[str] | None = None) -> Dict[str, object]:
    aircrafts = validation_aircraft_selection(candidates)
    airlines = make_breeze_like_airlines(budget, calibrated_yield_per_mile(route_df))
    optimizer = FleetOptimizer(
        aircrafts=aircrafts,
        airlines=airlines,
        airline_name="Leader",
        demand=build_demand(route_df),
        config=validation_model_config(),
    )
    return summarize_result(optimizer.solve(verbose=False), aircrafts)


def single_type_comparison(route_df: pd.DataFrame, budget: float) -> pd.DataFrame:
    rows = []
    for aircraft_name in CANDIDATE_AIRCRAFT:
        result = solve_case(route_df, budget, [aircraft_name])
        rows.append(
            {
                "aircraft": aircraft_name,
                "status": result["status"],
                "orders": result["total_orders"],
                "objective": result["objective"],
                "revenue": result["revenue"],
                "operating_cost": result["operating_cost"],
                "acquisition_cost": result["acquisition_cost"],
                "risk_cost": result["risk_cost"],
                "bulk_discount_savings": result["bulk_discount_savings"],
                "weighted_casm": result["weighted_casm"],
                "total_asm": result["total_asm"],
            }
        )
    return pd.DataFrame(rows).sort_values("objective", ascending=False)


def build_input_table(
    route_df: pd.DataFrame,
    budget: float,
    yield_per_mile: float,
    *,
    network_source: str = "schedule CSV",
) -> pd.DataFrame:
    avg_stage_len = weighted_stage_length(route_df)
    return pd.DataFrame(
        [
            {
                "Input": "Route network (schedule CSV)",
                "Value / Method": "Schedule rows aggregated to directed route segments (see data/README.md)",
                "Status": "User-provided or synthetic example",
                "Source / Rationale": network_source,
            },
            {
                "Input": "Historical validation target",
                "Value / Method": "A220 should be selected or dominant for a Breeze-like clean-sheet airline",
                "Status": "Observed target + interpretation",
                "Source / Rationale": "Breeze reported 33 A220s in fleet by end-2024; E190/E195 mainly supported charter operations",
            },
            {
                "Input": "Aircraft seat / CASM calibration",
                "Value / Method": "Use Breeze-oriented seat configs (A220=137, E190=108, E195=122) and differentiated CASM values (A220=0.1180, E190=0.1230, E195=0.1215, A319=0.1210, A320/B738=0.1195, B737Max7=0.1205)",
                "Status": "Calibrated from observed configs + harmonized economics",
                "Source / Rationale": "Observed Breeze 2024 schedule seat counts plus aircraft-family economic differentiation to avoid the unrealistic equal-CASM assumption across all conventional aircraft",
            },
            {
                "Input": "Existing fleet",
                "Value / Method": "Zero existing fleet (clean-sheet simplification)",
                "Status": "Model assumption",
                "Source / Rationale": "Chosen to isolate fleet-acquisition logic rather than legacy fleet transition effects",
            },
            {
                "Input": "Annual passenger demand",
                "Value / Method": f"{CONFIG.annual_passengers_2024:,} passengers allocated across observed routes in proportion to schedule seat supply",
                "Status": "Observed total + estimated allocation",
                "Source / Rationale": "Breeze official 2024 operating update gives annual passengers; route split inferred from observed network",
            },
            {
                "Input": "Budget",
                "Value / Method": f"{budget:,.1f} MUSD calibrated as 110% of the highest single-type acquisition cost needed to cover the observed network",
                "Status": "Calibrated",
                "Source / Rationale": "Implements the rule that budget should not mechanically exclude candidate aircraft types",
            },
            {
                "Input": "Risk aversion",
                "Value / Method": f"q = {Airlines.Leader.value.risk_aversion:.2f}",
                "Status": "Calibrated",
                "Source / Rationale": "Uses the current model-level risk calibration from params.py",
            },
            {
                "Input": "Load factor",
                "Value / Method": f"{CONFIG.base_load_factor:.2f}",
                "Status": "Estimated",
                "Source / Rationale": "Persona-style proxy used when airline-specific public load factor is unavailable",
            },
            {
                "Input": "Market share",
                "Value / Method": "1.0",
                "Status": "Structural assumption",
                "Source / Rationale": "Demand already represents Breeze's realized network; no additional market split is imposed",
            },
            {
                "Input": "Yield per mile",
                "Value / Method": f"{yield_per_mile:.4f} $/pax-mile, calibrated from 2024 revenue and weighted average stage length ({avg_stage_len:.1f} miles)",
                "Status": "Calibrated from observed totals",
                "Source / Rationale": "Total revenue anchor from Breeze 2024 operating update; ancillary revenue separated explicitly",
            },
            {
                "Input": "Ancillary revenue per pax",
                "Value / Method": f"{CONFIG.base_ancillary_per_pax:.1f} USD/pax",
                "Status": "Estimated",
                "Source / Rationale": "General persona value retained when airline-specific disclosure is unavailable",
            },
            {
                "Input": "MOQ threshold",
                "Value / Method": f"moq_threshold = {CONFIG.base_moq_threshold}",
                "Status": "Model parameter",
                "Source / Rationale": "Uses Airlines.moq_threshold via AirlineSelection override",
            },
            {
                "Input": "Bulk discount",
                "Value / Method": "Disabled (bulk_discount_rate = 0)",
                "Status": "Model assumption",
                "Source / Rationale": "Avoids confounding the validation with an additional pricing mechanism",
            },
            {
                "Input": "Max aircraft types",
                "Value / Method": str(CONFIG.base_max_aircraft_types),
                "Status": "Model assumption",
                "Source / Rationale": "Small value chosen to reflect a simple clean-sheet airline design test",
            },
        ]
    )


def write_markdown_table(df: pd.DataFrame, path: Path) -> None:
    lines = [
        "# Breeze A220 Historical Validation Inputs",
        "",
        "Partial historical validation with observed network + calibrated economic inputs.",
        "",
        "| Input | Value / Method | Status | Source / Rationale |",
        "|---|---|---|---|",
    ]
    for row in df.itertuples(index=False):
        lines.append(
            f"| {row[0]} | {str(row[1]).replace('|', '/')} | {row[2]} | {str(row[3]).replace('|', '/')} |"
        )
    path.write_text("\n".join(lines))


def build_interpretation_lines(baseline: pd.Series) -> List[str]:
    if bool(baseline["a220_selected"]):
        return [
            "- The baseline calibration recovers the historical direction of Breeze's A220 adoption.",
            "- Under the observed-network plus calibrated-economics setup, A220-300 emerges as the dominant aircraft type for the clean-sheet carrier test.",
            "- This indicates that the validation now reflects both the Breeze-like seat configuration and the differentiated mission economics across candidate aircraft.",
        ]

    return [
        "- The baseline calibration does not recover Breeze's historical A220 choice.",
        "- Under the present parameterization, the solver is still favoring a different aircraft because of network fit, acquisition cost, or remaining economic assumptions.",
        "- This should be treated as an informative mismatch and used to guide the next calibration step.",
    ]


def write_summary_markdown(
    path: Path,
    baseline_df: pd.DataFrame,
    budget_sweep_df: pd.DataFrame,
    single_type_df: pd.DataFrame,
) -> None:
    baseline = baseline_df.iloc[0]
    top_three = single_type_df.head(3)

    lines = [
        "# Breeze A220 Partial Historical Validation",
        "",
        "This test is structured as a partial historical validation with observed network data and calibrated economic inputs.",
        "",
        "## Baseline outcome",
        "",
        f"- Solver status: `{baseline['status']}`",
        f"- Dominant aircraft: `{baseline['dominant_type']}`",
        f"- A220 selected: `{baseline['a220_selected']}`",
        f"- Selected order profile: `{baseline['selected_orders']}`",
        f"- Objective value: `{baseline['objective']:.2f}`",
        "",
        "## Budget sensitivity",
        "",
        "| Budget factor | Budget (MUSD) | Dominant aircraft | A220 selected | Total orders |",
        "|---|---:|---|---|---:|",
    ]
    for row in budget_sweep_df.itertuples(index=False):
        lines.append(
            f"| {row.budget_factor:.2f} | {row.budget_musd:.1f} | {row.dominant_type} | {row.a220_selected} | {row.total_orders} |"
        )

    lines.extend(
        [
            "",
            "## Top single-type candidates under the baseline calibration",
            "",
            "| Aircraft | Objective | Acquisition cost (MUSD) | Risk cost | Weighted CASM |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in top_three.itertuples(index=False):
        lines.append(
            f"| {row.aircraft} | {row.objective:.2f} | {row.acquisition_cost:.1f} | {row.risk_cost:.2f} | {row.weighted_casm:.4f} |"
        )

    lines.extend(["", "## Interpretation", ""])
    lines.extend(build_interpretation_lines(baseline))
    path.write_text("\n".join(lines))


def default_network_csv() -> Path:
    return repo_root() / "data" / "examples" / "synthetic_network.csv"


def run_validation(network_csv: Path | None = None) -> None:
    outdir = outputs_dir()
    csv_path = network_csv or default_network_csv()
    if not csv_path.is_file():
        raise FileNotFoundError(
            f"Network CSV not found: {csv_path}\n"
            "Provide --network-csv or add data/examples/synthetic_network.csv"
        )
    route_df = load_schedule_network(csv_path)
    aircrafts = validation_aircraft_selection()
    budget, candidate_budget_df = calibrated_budget(aircrafts, route_df)
    yield_per_mile = calibrated_yield_per_mile(route_df)

    baseline = solve_case(route_df, budget)
    baseline_df = pd.DataFrame(
        [
            {
                "status": baseline["status"],
                "dominant_type": baseline["dominant_type"],
                "a220_selected": baseline["a220_selected"],
                "a220_orders": baseline["a220_orders"],
                "selected_orders": str(baseline["selected_orders"]),
                "selected_types": baseline["selected_types"],
                "total_orders": baseline["total_orders"],
                "objective": baseline["objective"],
                "revenue": baseline["revenue"],
                "operating_cost": baseline["operating_cost"],
                "fixed_cost": baseline["fixed_cost"],
                "acquisition_cost": baseline["acquisition_cost"],
                "risk_cost": baseline["risk_cost"],
                "bulk_discount_savings": baseline["bulk_discount_savings"],
                "weighted_casm": baseline["weighted_casm"],
                "total_asm": baseline["total_asm"],
            }
        ]
    )

    budget_rows = []
    for factor in CONFIG.budget_sweep_factors:
        case = solve_case(route_df, budget * factor)
        budget_rows.append(
            {
                "budget_factor": factor,
                "budget_musd": round(budget * factor, 1),
                "status": case["status"],
                "dominant_type": case["dominant_type"],
                "a220_selected": case["a220_selected"],
                "a220_orders": case["a220_orders"],
                "total_orders": case["total_orders"],
                "selected_types": case["selected_types"],
                "objective": None if case["objective"] is None else round(case["objective"], 2),
                "acquisition_cost": round(case["acquisition_cost"], 2),
            }
        )
    budget_sweep_df = pd.DataFrame(budget_rows)

    single_type_df = single_type_comparison(route_df, budget)
    input_df = build_input_table(route_df, budget, yield_per_mile, network_source=str(csv_path))

    input_df.to_csv(outdir / "breeze_validation_inputs.csv", index=False)
    write_markdown_table(input_df, outdir / "breeze_validation_inputs.md")
    candidate_budget_df.to_csv(outdir / "breeze_candidate_budget_calibration.csv", index=False)
    baseline_df.to_csv(outdir / "breeze_validation_baseline.csv", index=False)
    budget_sweep_df.to_csv(outdir / "breeze_validation_budget_sweep.csv", index=False)
    single_type_df.to_csv(outdir / "breeze_validation_single_type_comparison.csv", index=False)
    write_summary_markdown(
        outdir / "breeze_validation_summary.md",
        baseline_df,
        budget_sweep_df,
        single_type_df,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Historical validation workflow using a schedule network CSV.",
    )
    parser.add_argument(
        "--network-csv",
        type=Path,
        default=None,
        help="Path to route schedule CSV (default: data/examples/synthetic_network.csv)",
    )
    args = parser.parse_args()
    run_validation(network_csv=args.network_csv)
