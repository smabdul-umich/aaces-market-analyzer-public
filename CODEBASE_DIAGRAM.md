# AACES Codebase Diagram

Architecture for the fleet-acquisition MIQP solver and novel-aircraft-concept sensitivity studies.

For setup and runnable examples, see [README.md](README.md).

---

## 1. Module dependency graph

```mermaid
flowchart TB
    subgraph config["Configuration — params.py"]
        MC["ModelConfig"]
        AC["Aircraft / Aircrafts"]
        AL["Airline / Airlines"]
        DM["Demand / DemandSegment"]
        ASel["AircraftSelection"]
        ALsel["AirlineSelection"]
    end

    subgraph solver["Solver — miqp_portfolio.py"]
        FO["FleetOptimizer"]
        SR["SolverResult"]
        FO --> SR
    end

    subgraph scenarios["Scenario layer — scenarios.py"]
        SC["Scenario"]
        SRU["ScenarioRunner"]
        PR["PRESETS"]
        SC --> SRU
        PR --> SC
    end

    subgraph studies["Sensitivity studies"]
        SCOM["study_common.py"]
        S1["study1_sensitivity.py"]
        S2["study2_sensitivity.py"]
        SCOM --> S1
        SCOM --> S2
    end

    subgraph demo["Examples"]
        TS["test_solver.py"]
    end

  MC --> FO
  ASel --> FO
  ALsel --> FO
  DM --> FO
  ASel --> SRU
  ALsel --> SRU
  DM --> SRU
  MC --> SRU
  FO --> SRU
  SRU --> SCOM
  SRU --> TS

    style config fill:#e8f4e8
    style solver fill:#e8e8f8
    style scenarios fill:#f0f8ff
    style studies fill:#fff8e8
    style demo fill:#f5f5f5
```

**Dependency rule:** everything reads configuration from `params.py`. The solver never imports study code; studies import the solver through `scenarios.py`.

---

## 2. End-to-end data flow

```mermaid
flowchart LR
    subgraph inputs["Inputs"]
        P["params.py\n(aircraft, airline, demand, ModelConfig)"]
        OVR["Scenario overrides\n(optional)"]
    end

    subgraph build["Build & solve"]
        SEL["AircraftSelection +\nAirlineSelection"]
        FO["FleetOptimizer.solve()"]
        GB["Gurobi MIQP"]
    end

    subgraph outputs["Outputs"]
        RES["SolverResult\n(orders, profit, utilization, …)"]
        SUM["result.summary()"]
        CMP["ScenarioRunner.compare()"]
        CSV["study*_outputs/*.csv"]
    end

    P --> SEL
    OVR --> SEL
    SEL --> FO --> GB --> RES
    RES --> SUM
    RES --> CMP
    RES --> CSV
```

Each `ScenarioRunner.run_one()` call creates **fresh** selection objects, applies that scenario's overrides, solves once, and returns one `SolverResult`. Runs do not share mutable state.

---

## 3. Layer responsibilities

```mermaid
flowchart TB
    subgraph L1["Layer 1 — Data (params.py)"]
        d1["Frozen dataclasses: Aircraft, Airline, DemandSegment"]
        d2["Enum catalogs: Aircrafts, Airlines, Fleets"]
        d3["Selection wrappers with apply_mofd() overrides"]
        d4["ModelConfig: horizon, big-M, bulk discount, solver tolerances"]
    end

    subgraph L2["Layer 2 — Solver (miqp_portfolio.py)"]
        s1["FleetOptimizer: build model, add constraints, optimize"]
        s2["Objective: T × (revenue − operating − fixed − risk)"]
        s3["Budget constraint: acquisition − bulk discount + infra"]
        s4["SolverResult: structured KPIs + summary() formatter"]
    end

    subgraph L3["Layer 3 — Scenarios (scenarios.py)"]
        c1["Scenario: named override bundle"]
        c2["Scenario.sweep / sweep_airline / sweep_demand factories"]
        c3["ScenarioRunner: override → solve → collect"]
        c4["PRESETS: ready-made sweep lists"]
    end

    subgraph L4["Layer 4 — Studies (study_*.py)"]
        t1["StudyConfig: aircraft filter + output slug"]
        t2["Sweep grids: CASM, price, seats"]
        t3["CLI: --inspect, --no-sweeps, CSV export"]
    end

    L1 --> L2 --> L3 --> L4
```

---

## 4. Sensitivity study structure

```mermaid
flowchart TB
    subgraph study1["study1_sensitivity.py"]
        f1["aircraft_filter:\n{B737Max8, Concept_A}"]
    end

    subgraph study2["study2_sensitivity.py"]
        f2["aircraft_filter:\n{B737Max8, A320Neo, Concept_A}"]
    end

    subgraph common["study_common.py (shared)"]
        airline["Study1_Airline"]
        demand["study_demand\n(6.5M pax, 1200–1800 mi)"]
        base["BASE_CASM / PRICE / SEATS\n(from Concept_A in params.py)"]
        sweeps["CASM · price · seats sweeps"]
        cli["run_cli()"]
    end

    f1 --> common
    f2 --> common
    common --> runner["ScenarioRunner"]
    runner --> csv1["study1_outputs/"]
    runner --> csv2["study2_outputs/"]
```

Study files are thin wrappers: they only declare **which aircraft are eligible** and **where CSVs go**. All sweep logic, scenario factories, and CLI live in `study_common.py`.

---

## 5. File reference

| File | Role |
|------|------|
| **params.py** | Single source of truth for aircraft catalog, airline profiles, default demand, and `ModelConfig`. Access data through `AircraftSelection` / `AirlineSelection`, not raw enums. |
| **miqp_portfolio.py** | `FleetOptimizer` builds and solves the MIQP; `SolverResult` packages all outputs (`orders`, financials, utilization, demand fulfillment, `summary()`). |
| **scenarios.py** | Declarative `Scenario` overrides + `ScenarioRunner` for isolated batch runs. `PRESETS` holds common sweeps. |
| **study_common.py** | Shared sensitivity-study machinery: demand, sweep grids, scenario factories, result tables, CLI, CSV export. |
| **study1_sensitivity.py** | Study 1 entry point: B737Max8 vs Concept_A. |
| **study2_sensitivity.py** | Study 2 entry point: B737Max8 + A320Neo vs Concept_A. |
| **test_solver.py** | Runnable tour of baseline solves, presets, and custom sweeps. |
| **historical_validation_breeze.py** | Optional historical validation: Breeze A220 acquisition case study (schedule CSV → demand → solve). |
| **study1_outputs/** · **study2_outputs/** | CSV sweep results written by the study scripts. |
| **AIAA paper** ([doi:10.2514/6.2026-4470](https://arc.aiaa.org/doi/abs/10.2514/6.2026-4470)) | Mathematical formulation; equation numbers map to comments and constraint builders in `miqp_portfolio.py`. |

---

## 6. Key classes (quick lookup)

| Class | Module | Purpose |
|-------|--------|---------|
| `ModelConfig` | params | Time horizon, big-M, MIP gap, bulk-discount rate/threshold |
| `AircraftSelection` | params | Read / override aircraft attributes; `families()`, `family_infra_cost()` |
| `AirlineSelection` | params | Read / override airline attributes; `fleet_count()` |
| `Demand` | params | List of `DemandSegment`s; `scaled(fraction)` |
| `FleetOptimizer` | miqp_portfolio | Build + solve MIQP for one airline |
| `SolverResult` | miqp_portfolio | All outputs; `annual_profit`, `total_profit`, `summary()` |
| `Scenario` | scenarios | Named parameter overrides |
| `ScenarioRunner` | scenarios | Apply scenario → solve → return `SolverResult` |
| `StudyConfig` | study_common | Per-study label, aircraft filter, output directory |
