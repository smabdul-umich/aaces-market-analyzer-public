# study2_sensitivity.py
"""
Study 2 — Two conventional aircraft vs one novel aircraft concept.

Research question
-----------------
Same as Study 1, but with a SECOND comparable conventional aircraft (A320Neo)
added to the choice set.  Idea (per the plan): "Can our model's reasonable
behavior scale when multiple aircraft are under consideration?"

Setup highlights
----------------
* Aircraft choice set: ``{B737Max8, A320Neo, Concept_A}``.

  - B737Max8 and A320Neo are the two "comparable conventional aircraft"
    called out in the plan.  Their parameters (block hours, CASM, price,
    risk, seats, range, infra cost) are defined once in ``params.py``;
    this study never restates them.
  - Concept_A is the novel aircraft concept variant under study.
* Everything else (airline, demand, sweep grid, run logic, CLI) is reused
  verbatim from ``study_common.py`` so the only thing that changes between
  Study 1 and Study 2 is the aircraft choice set — exactly as the plan
  prescribes.

Sweeps (grids defined in study_common.py)
-----------------------------------------
1. Concept_A CASM:  multiplicative, fraction × base   (price + seats held constant).
2. Concept_A price: multiplicative, fraction × base   (CASM  + seats held constant).
3. Concept_A seats: additive, base + delta seats      (CASM  + price held constant).

Run with::

    python study2_sensitivity.py                     # all sweeps + CSVs
    python study2_sensitivity.py --inspect baseline  # just the baseline summary
    python study2_sensitivity.py --help              # full CLI
"""

from __future__ import annotations

from pathlib import Path

from params import Aircraft
from study_common import CONCEPT_AIRCRAFT, StudyConfig, run_cli


# ── Study 2 specifics ────────────────────────────────────────────

CONVENTIONAL_AIRCRAFTS = ("B737Max8", "A320Neo")


def study2_aircraft_filter(aircraft: Aircraft) -> bool:
    """B737Max8 and A320Neo (conventional) plus Concept_A (parameters in params.py)."""
    return aircraft.name in {*CONVENTIONAL_AIRCRAFTS, CONCEPT_AIRCRAFT}


STUDY_2 = StudyConfig(
    label                  = "STUDY 2",
    description            = "B737Max8 + A320Neo vs Concept_A — two comparable conventional aircraft vs one novel aircraft concept.",
    aircraft_filter        = study2_aircraft_filter,
    conventional_aircrafts = CONVENTIONAL_AIRCRAFTS,
    output_dir             = Path(__file__).parent / "study2_outputs",
    slug                   = "study2",
)


if __name__ == "__main__":
    run_cli(STUDY_2, prog_name="study2_sensitivity.py")
