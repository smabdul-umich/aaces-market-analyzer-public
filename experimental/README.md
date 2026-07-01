# Experimental GUI (proof of concept)

`gui.py` is a **proof of concept** for an interactive front end on top of the AACES optimization model. It shows how users could adjust parameters, launch a solve, and read results without writing Python scripts.

A full GUI would enable:

- richer parameter editing (fleet composition, aircraft catalog filters),
- schedule / network upload for demand estimation,
- visualization of utilization and segment fulfillment, and
- multi-airline competitive dynamics over time.


## Run the demo

Requires Gurobi, `streamlit`, and the packages in `requirements.txt`:

```bash
streamlit run experimental/gui.py
```

Supported batch workflows remain in the repo root: `test_solver.py`, `study1_sensitivity.py`, `study2_sensitivity.py`, and `notebooks/`.
