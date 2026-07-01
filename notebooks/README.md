# Notebooks

Lightweight tutorials for exploring the AACES codebase interactively. These notebooks **import** from the repo modules (`params.py`, `scenarios.py`, `miqp_portfolio.py`) — they do not embed copies of the solver or catalog.

## Setup

1. Activate your Python environment (same one used for `pip install -r requirements.txt`).
2. Install Jupyter if needed: `pip install jupyter` (or use the VS Code / Cursor notebook UI).
3. **Start the kernel with the repo root as the working directory** so `import params` resolves correctly.

From the repo root:

```bash
jupyter notebook notebooks/01_params_exploration.ipynb
```

Or open any `.ipynb` in Cursor/VS Code and pick the `aaces` interpreter.

## Notebooks

| File | Purpose |
|------|---------|
| `01_params_exploration.ipynb` | Browse the aircraft catalog, filter by family, apply `apply_mofd()` overrides |
| `02_solver_exploration.ipynb` | Run `ScenarioRunner`, compare presets, inspect `SolverResult.summary()` |

For scripted equivalents, see `test_solver.py` and `study1_sensitivity.py --inspect baseline`.
