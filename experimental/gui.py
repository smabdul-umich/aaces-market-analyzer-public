"""
Streamlit proof-of-concept GUI for AACES fleet optimization.

Demonstrates how an interactive front end could let users adjust airline and
aircraft parameters, run the MIQP solver, and inspect results. A full
production GUI (multi-airline competition, schedule upload, richer charts) is
left as future work — see experimental/README.md.
"""

from __future__ import annotations

import streamlit as st

from params import Airlines, demand
from scenarios import Scenario, ScenarioRunner

st.set_page_config(page_title="AACES Fleet Optimizer", layout="wide")
st.title("AACES Fleet Acquisition Optimizer")
st.caption(
    "Proof-of-concept interface for the optimization model. "
    "Run from the repo root: `streamlit run experimental/gui.py`"
)

AIRLINE_OPTIONS = [a.value.name for a in Airlines if a.value.name in ("Leader", "Follower")]

with st.sidebar:
    st.header("Configuration")
    airline_name = st.selectbox("Airline", AIRLINE_OPTIONS, index=0)
    airline = next(a.value for a in Airlines if a.value.name == airline_name)

    budget = st.number_input(
        "Acquisition budget ($M)",
        min_value=100,
        max_value=50_000,
        value=int(airline.budget),
        step=100,
    )
    risk_aversion = st.number_input(
        "Risk aversion",
        min_value=0.0,
        max_value=5_000.0,
        value=float(airline.risk_aversion),
        step=50.0,
    )

    st.subheader("Concept aircraft incentives")
    concept_price_adj = st.slider("Concept_A price adjustment ($M)", -20.0, 20.0, 0.0, 0.5)
    concept_casm_adj = st.slider("Concept_A CASM adjustment", -0.05, 0.05, 0.0, 0.005)

    run_competition = st.toggle(
        "Competitive market simulation",
        value=False,
        help="Planned future work: rolling multi-airline dynamics tied to the solver.",
    )

    run_button = st.button("Run optimization", type="primary", use_container_width=True)

st.subheader("Supported today")
st.markdown(
    "- Adjust airline budget and risk aversion, then solve the single-airline MIQP via `ScenarioRunner`.\n"
    "- Apply MOFD-style incentives on **Concept_A** (price / CASM adjustments).\n"
    "- View the solver summary and per-aircraft orders."
)

if run_competition:
    st.info(
        "A competitive market GUI would couple rolling demand dynamics with repeated "
        "solver calls for Leader and Follower. That workflow is not wired up in this "
        "proof of concept — contributions welcome."
    )

if run_button:
    overrides: dict = {
        airline_name: {"budget": float(budget), "risk_aversion": float(risk_aversion)},
    }
    aircraft_overrides: dict = {}
    if concept_price_adj or concept_casm_adj:
        aircraft_overrides["Concept_A"] = {
            "price_adjustment": concept_price_adj,
            "casm_adjustment": concept_casm_adj,
        }

    scenario = Scenario(
        label="gui run",
        airline_overrides=overrides,
        aircraft_overrides=aircraft_overrides or None,
    )

    with st.spinner("Solving MIQP…"):
        runner = ScenarioRunner(airline_name=airline_name, demand=demand)
        result = runner.run_one(scenario)

    st.success(f"Status: {result.status} · Objective: {result.objective:,.0f}")

    st.text(result.summary())

    if result.orders:
        st.subheader("New-build orders")
        rows = [
            {"Aircraft": ac, "Orders": qty}
            for ac, qty in sorted(result.orders.items())
            if qty > 0
        ]
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.write("No new aircraft ordered.")

st.divider()
st.markdown(
    "**Future work:** schedule CSV upload, fleet editing, Altair utilization charts, "
    "and a competition mode that orchestrates repeated solves across airlines and time periods."
)
