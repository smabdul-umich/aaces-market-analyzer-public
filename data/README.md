# Network schedule input format

The core MIQP (`test_solver.py`, `study*_sensitivity.py`) reads demand from **`params.py`** — no external CSV required for the main workflows.

The optional script `historical_validation_breeze.py` builds `Demand` segments from a **route-level schedule CSV**. That format is documented here so you can run the validation workflow with your own data.

## Required columns

| Column | Type | Description |
|--------|------|-------------|
| `depapt` | string | Origin airport code (e.g. `AP01`) |
| `arrapt` | string | Destination airport code |
| `seats` | number | Seats per flight on this row |
| `distance` | number | Stage length in **miles** |
| `NFlts` | number | Number of flights represented by this row (schedule weight) |

Rows with non-positive `NFlts`, `seats`, or `distance` are dropped.

## How the loader uses the file

`historical_validation_breeze.load_schedule_network()` (see repo):

1. Aggregates rows by directed pair `(depapt, arrapt)`.
2. Uses `max(distance)` per pair and sums `seats × NFlts` as seat-supply weight.
3. Allocates total annual passengers across segments in proportion to seat supply.
4. Computes block time as `distance / block_speed + turnaround` (defaults in `ValidationConfig`).

## Example (synthetic network data)

[`examples/synthetic_network.csv`](examples/synthetic_network.csv) — six fictional routes between `AP01`–`AP04`. **Not real airline or OAG data.**

Run the validation demo:

```bash
python historical_validation_breeze.py
# or explicitly:
python historical_validation_breeze.py --network-csv data/examples/synthetic_network.csv
```

Outputs go to `outputs/historical_validation/` (outputs are not tracked by git).

## Full OAG-style exports (internal / licensed use only)

If you have a licensed OAG (or similar) schedule export with additional columns (`carrier`, `fltno`, `deptim`, …), only the five columns above are required. Extra columns are ignored.

## Demand without CSV

You can also define custom demand data within Python:

```python
from params import Demand, DemandSegment

demand = Demand([
    DemandSegment(
        name="east_coast",
        distance_min=800,
        distance_max=1200,
        demand=500_000,      # passengers per year
        block_time=2.5,      # block hours
    ),
])
```

Then pass `demand` to `ScenarioRunner` or `FleetOptimizer` as in `test_solver.py`.
