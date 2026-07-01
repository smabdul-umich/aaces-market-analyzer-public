# AACES Fleet Optimization

Mixed-integer quadratic program (MIQP) for airline fleet acquisition, with a focus on when an airline should adopt **novel aircraft concepts** alongside conventional types.

You do **not** need to read the solver internals to use this repo. Most workflows are: pick parameters → run a script → read the printed summary or CSV output.

For architecture diagrams, see [CODEBASE_DIAGRAM.md](CODEBASE_DIAGRAM.md).
**Input data format:** [data/README.md](data/README.md)

### Citation

If you use any part of this codebase in a project or publication, please cite our paper:

> Sinan Abdulhak, David Kwon, Shibo Huang, Ara Mahseredjian, Parker Vascik, and Max Z. Li, *Modeling Demand for Novel Aircraft in a Competitive Market: A 2050 to 2100 Case Study for Hybrid Electric Aircraft*, AIAA AVIATION 2026 Forum. [https://arc.aiaa.org/doi/abs/10.2514/6.2026-4470](https://arc.aiaa.org/doi/abs/10.2514/6.2026-4470)

```bibtex
@inbook{doi:10.2514/6.2026-4470,
  author    = {Sinan Abdulhak and David Kwon and Shibo Huang and Ara Mahseredjian and Parker Vascik and Max Z. Li},
  title     = {Modeling Demand for Novel Aircraft in a Competitive Market: A 2050 to 2100 Case Study for Hybrid Electric Aircraft},
  booktitle = {AIAA AVIATION 2026 Forum},
  doi       = {10.2514/6.2026-4470},
  url       = {https://arc.aiaa.org/doi/abs/10.2514/6.2026-4470},
}
```

**Copyright © 2026** Sinan Abdulhak, David Kwon, Shibo Huang, Ara Mahseredjian, Parker Vascik, and Max Z. Li. See [LICENSE](LICENSE) (MIT).

---

## Quick start (5 minutes)

### 1. Install dependencies

You need **Python 3.10+**, **Gurobi** (with a valid license), and the packages in `requirements.txt`.

```bash
# Example: conda environment (adjust if you use venv)
conda create -n aaces python=3.11 -y
conda activate aaces
pip install -r requirements.txt
```

Gurobi must be installed separately and licensed ([Gurobi download](https://www.gurobi.com/downloads/)). If `import gurobipy` fails, fix Gurobi before running anything else.

### 2. Run a baseline optimization

```bash
python test_solver.py
```

This runs several example scenarios and prints comparison tables. Section 1 prints a full `SolverResult.summary()` for the Leader airline baseline.

### 3. Run a sensitivity study

```bash
# Study 1: B737Max8 vs Concept_A — all sweeps + CSV files
python study1_sensitivity.py

# Study 2: B737Max8 + A320Neo vs Concept_A
python study2_sensitivity.py
```

Outputs land in `study1_outputs/` and `study2_outputs/` as CSV files you can plot in Excel, Python, or R.

### 4. Zoom into one case (detailed utilization & fulfillment)

```bash
python study1_sensitivity.py --inspect baseline --no-sweeps
python study1_sensitivity.py --inspect casm:0.9 --no-sweeps
python study1_sensitivity.py --inspect price:0.5 --no-sweeps
python study1_sensitivity.py --inspect seats:-10 --no-sweeps
```

`--inspect` prints the full per-aircraft utilization and segment fulfillment report — useful for validating that a sweep point looks reasonable.

---

## What can I run?

| Goal | Command |
|------|---------|
| See example solves & presets | `python test_solver.py` |
| Run concept sensitivity Study 1 | `python study1_sensitivity.py` |
| Run concept sensitivity Study 2 | `python study2_sensitivity.py` |
| Inspect one study case in detail | `python study1_sensitivity.py --inspect baseline --no-sweeps` |
| Skip sweeps, only inspect | add `--no-sweeps` |
| Skip writing CSV files | add `--no-csv` |
| Show Gurobi solver log | add `--verbose-solver` |
| Run model V&V test suite | `python tests/run_model_tests.py` |
| Historical validation (Breeze A220 case) | `python historical_validation_breeze.py` |

Study CLI help:

```bash
python study1_sensitivity.py --help
```

---

## Codebase structure

```
aaces/
├── params.py                 # All model data (aircraft, airlines, demand, solver config)
├── miqp_portfolio.py         # MIQP solver (FleetOptimizer) and results (SolverResult)
├── scenarios.py              # Scenario overrides + batch runner
│
├── study_common.py           # Shared sensitivity-study logic (sweeps, CLI, CSV export)
├── study1_sensitivity.py     # Study 1: B737Max8 vs Concept_A
├── study2_sensitivity.py     # Study 2: B737Max8 + A320Neo vs Concept_A
├── study1_outputs/           # Study 1 CSV results (generated)
├── study2_outputs/           # Study 2 CSV results (generated)
│
├── notebooks/                # Interactive Jupyter tutorials (import from repo modules)
├── tests/                    # Model verification & validation test suite
├── test_solver.py            # Runnable examples for the solver & scenarios
├── historical_validation_breeze.py  # Historical validation: Breeze A220 acquisition case study
├── data/                     # Network CSV format docs + synthetic example
├── CODEBASE_DIAGRAM.md       # Architecture diagrams
│
├── experimental/             # Streamlit GUI proof of concept
└── requirements.txt
```

**Data flow:** `params.py` → `ScenarioRunner` → `FleetOptimizer.solve()` → `SolverResult`

---

## Usage examples

### Run the baseline model (Leader airline)

```python
from params import demand
from scenarios import Scenario, ScenarioRunner

runner = ScenarioRunner(airline_name="Leader", demand=demand)
result = runner.run_one(Scenario("baseline"), verbose=True)
print(result.summary())
```

Key numbers on `result`:

- `result.orders` — aircraft ordered this run
- `result.annual_profit` — revenue − operating − fixed − risk (per year)
- `result.total_profit` — `annual_profit × time_horizon_years`
- `result.concept_penetration` — share of seat-miles on novel aircraft concept types
- `result.summary()` — formatted report (utilization, fulfillment, financials)

### Apply parameter overrides (subsidy example)

Overrides go through `Scenario`; the runner applies them to a fresh copy of the catalog each time.

```python
from params import demand
from scenarios import Scenario, ScenarioRunner

scenario = Scenario(
    label="concept_subsidy_5M",
    aircraft_overrides={
        "Concept_A": {"price_adjustment": -5},
        "Concept_B": {"price_adjustment": -5},
        "Concept_C": {"price_adjustment": -5},
    },
)

runner = ScenarioRunner(airline_name="Leader", demand=demand)
result = runner.run_one(scenario)
print(result.summary())
```

`price_adjustment` and `casm_adjustment` on `Aircraft` are the supported incentive/penalty fields. They are applied when the solver reads price (budget) and CASM (operating cost).

### Run a preset sweep and compare scenarios

```python
from params import demand
from scenarios import ScenarioRunner, PRESETS

runner = ScenarioRunner(airline_name="Leader", demand=demand)
results = runner.run(PRESETS["concept_casm_sweep"])
print(ScenarioRunner.compare(results))
```

**Available presets:**

| Key | What it sweeps |
|-----|----------------|
| `"concept_subsidy_sweep"` | Concept `price_adjustment` at 0, −2, −5, −10 |
| `"concept_casm_sweep"` | Concept `casm` at 0.06, 0.08, 0.10, 0.12 |
| `"demand_sensitivity"` | Global demand scale 0.5×–1.5× |
| `"budget_sweep"` | Leader `budget` at 200–1000 |

### Build a custom sweep

```python
from params import demand
from scenarios import Scenario, ScenarioRunner

scenarios = [Scenario("baseline")] + Scenario.sweep(
    attribute="casm",
    aircrafts=["Concept_A", "Concept_B", "Concept_C"],
    values=[0.05, 0.06, 0.07, 0.08, 0.09, 0.10],
    label_prefix="concept_casm",
)

runner = ScenarioRunner(airline_name="Leader", demand=demand)
results = runner.run(scenarios)
print(ScenarioRunner.compare(results))
```

### Restrict which aircraft the solver may choose

```python
from params import Aircraft, AircraftFamily, AircraftSelection, demand
from scenarios import Scenario, ScenarioRunner

# Only novel aircraft concept types
concept_only = AircraftSelection(lambda ac: ac.family == AircraftFamily.NOVEL_AIRCRAFT_CONCEPT)

runner = ScenarioRunner(
    airline_name="Leader",
    demand=demand,
    aircraft_filter=lambda ac: ac.family == AircraftFamily.NOVEL_AIRCRAFT_CONCEPT,
)
result = runner.run_one(Scenario("baseline"))
print(result.orders)
```

### Configure solver behavior

```python
from params import ModelConfig, demand
from scenarios import Scenario, ScenarioRunner

config = ModelConfig(
    time_horizon_years=5,
    mip_gap=0.01,
    time_limit_seconds=120,
    bulk_discount_rate=0.05,
    bulk_discount_threshold=10,
)

runner = ScenarioRunner(airline_name="Leader", demand=demand, config=config)
result = runner.run_one(Scenario("baseline"))
print(f"Annual profit: {result.annual_profit:,.0f}")
print(f"Total profit ({config.time_horizon_years} yr): {result.total_profit:,.0f}")
```

### Direct solver call (debugging only)

Prefer `ScenarioRunner` for normal use — it handles overrides and isolation for you.

```python
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
```

---

## Sensitivity studies (Study 1 & 2)

These scripts implement the novel-aircraft-concept sensitivity analysis. They answer: **at what CASM, acquisition price, or seat count does the model switch from a conventional aircraft to Concept_A?**

| Study | Aircraft choice set | Output folder |
|-------|---------------------|---------------|
| Study 1 | B737Max8, Concept_A | `study1_outputs/` |
| Study 2 | B737Max8, A320Neo, Concept_A | `study2_outputs/` |

Each study runs three sweeps (holding the other Concept_A attributes fixed):

1. **CASM** — multiplicative grid (`SWEEP_FRACTIONS ×` Concept_A base CASM)
2. **Acquisition price** — multiplicative grid (`SWEEP_FRACTIONS ×` Concept_A base price)
3. **Seats** — additive grid (base seats + `SEATS_DELTAS`)

CSV columns include sweep input, absolute swept value, `concept_orders`, `{aircraft}_orders` for each conventional type in the study, `chosen_aircraft`, `total_profit`, `concept_penetration`, `weighted_casm`, and `status`.

### Changing study parameters

All catalogue values live in **`params.py`** — that is the single source of truth.

| What to change | Where |
|----------------|-------|
| Concept_A base CASM, price, seats | `Aircrafts.CONCEPT_A` in `params.py` |
| Study airline budget, risk, market share | `Airlines.Study1_Airline` in `params.py` |
| Sweep grid (fractions, seat deltas) | `SWEEP_FRACTIONS`, `SEATS_DELTAS` in `study_common.py` |
| Study demand bucket | `study_demand` in `study_common.py` |
| Which aircraft are in a study | `studyN_sensitivity.py` (`aircraft_filter`) |

Base sweep values for CASM/price/seats are read automatically from `Concept_A` in `params.py` — you should not hard-code them elsewhere.

### Adding Study 3

Copy `study2_sensitivity.py`, change the aircraft filter and `StudyConfig`, and call `run_cli()`. Everything else is shared in `study_common.py`.

---

## File reference

### `params.py` — Parameter definitions

All model inputs: aircraft specs, airline profiles, demand segments, and `ModelConfig`.

**Rules:**

- Read attributes through `AircraftSelection` and `AirlineSelection`, not by reaching into enum values directly.
- Apply scenario changes with `apply_mofd()` on a selection object — dataclasses are frozen.
- `AircraftSelection()` with no filter includes the full catalog; pass a lambda to restrict types.

**Airlines in the catalog:** `Leader`, `Follower`, `Study1_Airline` (used by sensitivity studies).

**Key classes:**

| Class | Role |
|-------|------|
| `ModelConfig` | Time horizon, big-M, MIP gap, time limit, bulk-discount rate/threshold |
| `Aircraft` / `Aircrafts` | Aircraft specifications and enum catalog |
| `AircraftSelection` | Access and override aircraft attributes; `families()`, `family_infra_cost()` |
| `Airline` / `Airlines` | Airline profiles and enum catalog |
| `AirlineSelection` | Access and override airline attributes; `fleet_count()` |
| `DemandSegment` / `Demand` | Distance buckets with passenger demand and block times |

### `miqp_portfolio.py` — Solver

`FleetOptimizer` builds the Gurobi MIQP for one airline and returns a `SolverResult`.

- Financial fields on `SolverResult` (`revenue`, `operating_cost`, etc.) are **annual**.
- Acquisition capital enters the **budget constraint**, not the objective (see the [AIAA paper](https://arc.aiaa.org/doi/abs/10.2514/6.2026-4470); equation numbers in `miqp_portfolio.py` comments trace back to the paper).
- `SolverResult.summary()` prints orders, financials, utilization, and demand fulfillment.

### `scenarios.py` — Scenario framework

The standard interface between scripts/notebooks and the solver.

- `Scenario("baseline")` — no overrides.
- Each `run_one()` uses fresh selection objects (runs are isolated).
- `ScenarioRunner.compare(results)` — side-by-side table across a sweep.

### `study_common.py` — Shared study machinery

Not usually imported directly unless you are adding a new study. Provides sweep builders, `inspect_case()`, CSV export, and the CLI used by `study1_sensitivity.py` and `study2_sensitivity.py`.

### `test_solver.py` — Examples

Runnable tour of baseline solves, presets, and custom sweeps. Good second step after `study1_sensitivity.py --inspect baseline`.

### `notebooks/` — Interactive exploration

Lightweight Jupyter notebooks that **import** from `params.py`, `scenarios.py`, and `miqp_portfolio.py` — they do not duplicate solver code. Open the folder in Jupyter or VS Code; start the kernel from the repo root so imports resolve.

| Notebook | What it covers |
|----------|----------------|
| `01_params_exploration.ipynb` | Catalog browsing, overrides via `apply_mofd()`, airline & demand accessors |
| `02_solver_exploration.ipynb` | `ScenarioRunner`, presets, `SolverResult.summary()` |

See [notebooks/README.md](notebooks/README.md) for setup notes.

---

## Retrieve parameters in Python

```python
from params import AircraftSelection, AirlineSelection, AircraftFamily

aircrafts = AircraftSelection()
print(aircrafts.names)
print(aircrafts.seats("A320Neo"))
print(aircrafts.casm("Concept_A"))
print(aircrafts.risk_coef("Concept_A"))

concepts = AircraftSelection(lambda ac: ac.family == AircraftFamily.NOVEL_AIRCRAFT_CONCEPT)
print(concepts.names)  # Concept_A, Concept_B, Concept_C

airlines = AirlineSelection()
print(airlines.budget("Leader"))
print(airlines.fleet_count("Leader", "A320Neo"))
print(airlines.budget("Study1_Airline"))
```

---

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| `ModuleNotFoundError: gurobipy` | Gurobi not installed in active environment |
| Solver exits immediately / segfault | Gurobi license issue; run outside restricted sandboxes |
| Price sweep looks flat | Budget may be non-binding — `price` affects the budget constraint, not the objective. Lower `Study1_Airline.budget` in `params.py` or inspect with `--inspect price:…` |
| Study 2 picks A320Neo over B737Max8 at baseline | Check `risk_coef` values in `params.py` — they drive the risk penalty in the objective |

---

## Historical validation (optional)

`historical_validation_breeze.py` is a **standalone study**, separate from Study 1/2 and `test_solver.py`. It tests whether the model can predict a real acquisition decision observed in history — Breeze Airways selecting the A220 — when fed that airline's network and calibrated economic inputs.

The script:

1. Loads a **route-level schedule CSV** and converts it into `Demand` segments (column schema in [data/README.md](data/README.md)).
2. Applies Breeze-like assumptions for quantities not publicly disclosed (budget, load factor, candidate aircraft set, etc. — see the script header).
3. Runs the optimizer over candidate narrow-body types and writes comparison tables to `outputs/historical_validation/`.

**Default run** — uses the bundled fictional example network (no proprietary data required):

```bash
python historical_validation_breeze.py
```

This reads `data/examples/synthetic_network.csv` automatically.

**Custom schedule file** — only if you have your own CSV in the same five-column format (`depapt`, `arrapt`, `seats`, `distance`, `NFlts`):

```bash
python historical_validation_breeze.py --network-csv /path/to/my_routes.csv
```

Replace the path with your file. Omit the flag entirely to use `data/examples/synthetic_network.csv`.

The main workflows (`test_solver.py`, `study1_sensitivity.py`, `study2_sensitivity.py`) define demand in **`params.py`** / `study_common.py` and **do not read any CSV**.

---

## Further reading

- [CODEBASE_DIAGRAM.md](CODEBASE_DIAGRAM.md) — module dependencies and layer diagram
- [AIAA paper](https://arc.aiaa.org/doi/abs/10.2514/6.2026-4470) — mathematical formulation; equation numbers in the paper correspond to comments and constraint builders in `miqp_portfolio.py`
