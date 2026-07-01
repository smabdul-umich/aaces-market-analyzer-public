# study1_sensitivity.py
"""
Study 1 — One conventional aircraft (B737Max8) vs one novel aircraft concept (Concept_A).

Research question
-----------------
Holding everything else fixed, at what Concept_A CASM (resp. acquisition cost)
does the airline switch from buying the conventional B737Max8 to buying the
concept variant?

Setup highlights
----------------
* Aircraft choice set: ``{B737Max8, Concept_A}``.  These two share their
  operational parameters in ``params.py``; they differ in family and in
  risk coefficient (``risk_coef``).  The exact values live in params.py —
  this study never restates them.
* Airline (``Study1_Airline``), demand, sweep grid, run logic, and CLI
  all live in ``study_common.py`` so this file stays trivial and Study N
  can be added the same way.

Sweeps (grids defined in study_common.py)
-----------------------------------------
1. Concept_A CASM:  multiplicative, fraction × base   (price + seats held constant).
2. Concept_A price: multiplicative, fraction × base   (CASM  + seats held constant).
3. Concept_A seats: additive, base + delta seats      (CASM  + price held constant).

Run with::

    python study1_sensitivity.py                     # all sweeps + CSVs
    python study1_sensitivity.py --inspect baseline  # just the baseline summary
    python study1_sensitivity.py --help              # full CLI
"""

from __future__ import annotations

from pathlib import Path

from params import Aircraft
from study_common import CONCEPT_AIRCRAFT, StudyConfig, run_cli


# ── Study 1 specifics ────────────────────────────────────────────

CONVENTIONAL_AIRCRAFT = "B737Max8"


def study1_aircraft_filter(aircraft: Aircraft) -> bool:
    """Only B737Max8 and Concept_A are eligible (risk values come from params.py)."""
    return aircraft.name in {CONVENTIONAL_AIRCRAFT, CONCEPT_AIRCRAFT}


STUDY_1 = StudyConfig(
    label                  = "STUDY 1",
    description            = "B737Max8 vs Concept_A — one conventional aircraft vs one novel aircraft concept.",
    aircraft_filter        = study1_aircraft_filter,
    conventional_aircrafts = (CONVENTIONAL_AIRCRAFT,),
    output_dir             = Path(__file__).parent / "study1_outputs",
    slug                   = "study1",
)


if __name__ == "__main__":
    run_cli(STUDY_1, prog_name="study1_sensitivity.py")
