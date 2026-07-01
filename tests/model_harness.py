"""
Shared helpers for fleet-optimization model V&V tests.

Provides toy problem builders, post-solve constraint auditing, independent
objective recomputation, and diagnostic reporting.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from params import (
    Aircraft,
    AircraftFamily,
    AircraftSelection,
    Airline,
    AirlinePersonas,
    AirlineSelection,
    Airlines,
    Demand,
    DemandSegment,
    Fleets,
    ModelConfig,
)
from miqp_portfolio import FleetOptimizer, SolverResult


TOL = 1e-4  # constraint violation tolerance (absolute)


# ── Lightweight selection wrappers for toy problems ─────────────────

class ToyAircraftSelection(AircraftSelection):
  """Build an ``AircraftSelection`` from explicit ``Aircraft`` instances."""

  def __init__(self, aircraft_list: List[Aircraft]):
      self._aircrafts = {a.name: a for a in aircraft_list}


class ToyAirlineSelection(AirlineSelection):
  """Build an ``AirlineSelection`` from explicit ``Airline`` instances."""

  def __init__(self, airline_list: List[Airline]):
      self._airlines = {a.name: a for a in airline_list}


# ── Toy catalog factories ───────────────────────────────────────────

def toy_aircraft(
    name: str = "ToyJet",
    *,
    family: AircraftFamily = AircraftFamily.A220,
    seats: int = 100,
    casm: float = 0.10,
    price: float = 10.0,
    range_mi: int = 2000,
    block_hours: int = 2000,
    block_time: float = 2.0,
    risk_coef: float = 1.0,
    infra_cost: int = 0,
    yearly_fixed_cost: int = 1,
) -> Aircraft:
  return Aircraft(
      name=name,
      family=family,
      max_flights_per_day=4,
      yearly_block_hours=block_hours,
      range=range_mi,
      price=price,
      seats=seats,
      infra_cost=infra_cost,
      yearly_fixed_cost=yearly_fixed_cost,
      casm=casm,
      risk_coef=risk_coef,
  )


def toy_airline(
    name: str = "ToyAirline",
    *,
    budget: float = 500.0,
    market_share: float = 1.0,
    load_factor: float = 0.80,
    yield_per_mile: float = 0.12,
    ancillary_per_pax: float = 5.0,
    risk_aversion: float = 0.0,
    moq_threshold: int = 1,
    max_aircraft_types: int = 3,
    fleet=Fleets.Empty.value,
) -> Airline:
  return Airline(
      name=name,
      persona=AirlinePersonas.LCC,
      budget=budget,
      risk_aversion=risk_aversion,
      load_factor=load_factor,
      market_share=market_share,
      yield_per_mile=yield_per_mile,
      ancillary_per_pax=ancillary_per_pax,
      fleet=fleet,
      moq_threshold=moq_threshold,
      max_aircraft_types=max_aircraft_types,
  )


def toy_demand(
    *,
    pax: float = 10_000.0,
    distance_min: float = 800.0,
    distance_max: float = 1200.0,
    block_time: float = 2.0,
    name: str = "toy_seg",
) -> Demand:
  return Demand([
      DemandSegment(name, distance_min, distance_max, pax, block_time),
  ])


def solve(
    aircrafts: AircraftSelection,
    airlines: AirlineSelection,
    airline_name: str,
    demand: Demand,
    config: ModelConfig = ModelConfig(),
) -> Tuple[SolverResult, FleetOptimizer]:
  opt = FleetOptimizer(aircrafts, airlines, airline_name, demand, config)
  result = opt.solve()
  return result, opt


# ── Independent objective arithmetic ────────────────────────────────

def independent_financials(
    opt: FleetOptimizer,
    result: SolverResult,
) -> Dict[str, float]:
  """Recompute annual revenue / costs from solved flights and orders. Purpose: Verify Gurobi's objective matches hand-calculated formulas."""
  T = opt.config.time_horizon_years
  revenue = operating = fixed = risk = 0.0

  for aircraft in opt.aircraft_names:
      existing = result.existing_fleet[aircraft]
      orders = result.orders[aircraft]
      fixed += opt.aircrafts.yearly_fixed_cost(aircraft) * (orders + existing)
      risk += opt.risk_aversion * opt.aircrafts.risk_coef(aircraft) * orders * orders

      for segment in opt.segments:
          flights = result.flights[aircraft, segment.name]
          asm = flights * opt.aircrafts.seats(aircraft) * segment.midpoint
          pax = flights * opt.aircrafts.seats(aircraft) * opt.load_factor
          revenue += opt.yield_per_mile * asm * opt.load_factor + opt.ancillary_per_pax * pax
          operating += opt.aircrafts.casm(aircraft, apply_adjustments=True) * asm

  annual_profit = revenue - operating - fixed - risk
  return {
      "revenue": revenue,
      "operating_cost": operating,
      "fixed_cost": fixed,
      "risk_cost": risk,
      "annual_profit": annual_profit,
      "objective": T * annual_profit,
  }


# ── Post-solve constraint auditor ───────────────────────────────────

@dataclass
class Violation:
  constraint: str
  message: str
  slack: float  # negative means violation


@dataclass
class AuditReport:
  status: str
  violations: List[Violation] = field(default_factory=list)
  warnings: List[str] = field(default_factory=list)

  @property
  def ok(self) -> bool:
      return not self.violations and self.status == "optimal"

  def summary(self) -> str:
      lines = [f"status={self.status}, violations={len(self.violations)}, warnings={len(self.warnings)}"]
      for v in self.violations:
          lines.append(f"  VIOLATION [{v.constraint}] {v.message} (slack={v.slack:+.2e})")
      for w in self.warnings:
          lines.append(f"  WARNING {w}")
      return "\n".join(lines)


def _infer_buy_family(opt: FleetOptimizer, orders: Dict[str, int]) -> Dict[AircraftFamily, int]:
  buy: Dict[AircraftFamily, int] = {}
  for family, members in opt.families.items():
      family_orders = sum(orders[a] for a in members)
      buy[family] = 1 if family_orders > 0 else 0
  return buy


def _infer_bulk_aux(
    opt: FleetOptimizer,
    orders: Dict[str, int],
    optimizer: FleetOptimizer,
) -> Tuple[Dict[str, int], Dict[str, float]]:
  """Read bulk-discount auxiliaries from the solved model when available."""
  v_active: Dict[str, int] = {}
  n_disc: Dict[str, float] = {}
  threshold = opt.bulk_discount_threshold
  for aircraft in opt.aircraft_names:
      o = orders[aircraft]
      if hasattr(optimizer, "_bulk_discount_active"):
          v_active[aircraft] = int(round(optimizer._bulk_discount_active[aircraft].X))
          n_disc[aircraft] = optimizer._discounted_orders[aircraft].X
      else:
          v_active[aircraft] = 1 if o >= threshold else 0
          n_disc[aircraft] = float(o) if o >= threshold else 0.0
  return v_active, n_disc


def audit_constraints(
    opt: FleetOptimizer,
    result: SolverResult,
    optimizer: Optional[FleetOptimizer] = None,
) -> AuditReport:
  """Check every model constraint against the reported solution."""
  report = AuditReport(status=result.status)
  if result.status != "optimal":
      report.warnings.append(f"Skipping detailed constraint audit for status={result.status}")
      return report

  orders = result.orders
  flights = result.flights
  buy_family = _infer_buy_family(opt, orders)
  if optimizer is not None and hasattr(optimizer, "_buy_family"):
      buy_family = {
          family: int(round(optimizer._buy_family[family].X))
          for family in opt.families
      }

  v_active, n_disc = _infer_bulk_aux(opt, orders, optimizer or opt)

  # 1. Budget
  acq = sum(opt.aircrafts.price(a, apply_adjustments=True) * orders[a] for a in opt.aircraft_names)
  bulk = sum(
      opt.bulk_discount_rate * opt.aircrafts.price(a, apply_adjustments=True) * n_disc[a]
      for a in opt.aircraft_names
  )
  infra = sum(
      opt.aircrafts.family_infra_cost(family) * buy_family[family]
      for family in opt.families
      if opt.existing_family_count[family] == 0
  )
  spend = acq - bulk + infra
  slack = opt.budget - spend
  if slack < -TOL:
      report.violations.append(Violation("Budget", f"spend={spend:.4f} > budget={opt.budget}", slack))

  # 2. Block hours
  for aircraft in opt.aircraft_names:
      existing = result.existing_fleet[aircraft]
      used = sum(flights[aircraft, s.name] * s.block_time for s in opt.segments)
      cap = opt.aircrafts.yearly_block_hours(aircraft) * (orders[aircraft] + existing)
      slack = cap - used
      if slack < -TOL:
          report.violations.append(
              Violation("BlockHours", f"{aircraft}: used={used:.2f} > cap={cap:.2f}", slack)
          )

  # 3. Max types
  types_used = sum(1 for a in opt.aircraft_names if orders[a] > 0)
  slack = opt.max_aircraft_types - types_used
  if slack < -TOL:
      report.violations.append(
          Violation("MaxTypes", f"types_used={types_used} > max={opt.max_aircraft_types}", slack)
      )

  # 4. Order ↔ type_used link (infer type_used)
  for aircraft in opt.aircraft_names:
      o = orders[aircraft]
      if optimizer is not None and hasattr(optimizer, "_type_used"):
          tu = int(round(optimizer._type_used[aircraft].X))
      else:
          tu = 1 if o > 0 else 0
      if o > opt.config.big_m * tu + TOL:
          report.violations.append(
              Violation("OrderTypeLink", f"{aircraft}: orders={o} but type_used={tu}", -1.0)
          )

  # 5. Bulk discount
  threshold = opt.bulk_discount_threshold
  for aircraft in opt.aircraft_names:
      o = orders[aircraft]
      v = v_active[aircraft]
      if o < threshold * v - TOL:
          report.violations.append(
              Violation("BulkDiscount_activate", f"{aircraft}: orders={o} < {threshold}*v={v}", o - threshold * v)
          )
      if o > (threshold - 1) + opt.config.big_m * v + TOL:
          report.violations.append(
              Violation("BulkDiscount_threshold", f"{aircraft}: orders={o} too high for v={v}", -1.0)
          )
      nd = n_disc[aircraft]
      if nd > opt.config.big_m * v + TOL or nd > o + TOL:
          report.violations.append(Violation("McCormick", f"{aircraft}: n_disc={nd} invalid", -1.0))
      lb = o - opt.config.big_m * (1 - v)
      if nd < lb - TOL:
          report.violations.append(Violation("McCormick_lb", f"{aircraft}: n_disc={nd} < lb={lb}", nd - lb))

  # 6. MOQ per family
  for family, members in opt.families.items():
      family_orders = sum(orders[a] for a in members)
      existing = opt.existing_family_count[family]
      bf = buy_family[family]
      if existing + family_orders < opt.moq_threshold * bf - TOL:
          report.violations.append(
              Violation("MOQ_threshold", f"{family.name}: fleet={existing+family_orders} < MOQ", -1.0)
          )
      if family_orders > opt.config.big_m * bf + TOL:
          report.violations.append(Violation("MOQ_link_ub", f"{family.name}", -1.0))
      if family_orders < bf - TOL and bf == 1:
          report.violations.append(Violation("MOQ_link_lb", f"{family.name}: orders={family_orders} < buy={bf}", -1.0))

  # 7. Demand upper bound
  for segment in opt.segments:
      pax = sum(
          flights[a, segment.name] * opt.aircrafts.seats(a) * opt.load_factor
          for a in opt.aircraft_names
      )
      cap = opt.market_share * segment.demand
      slack = cap - pax
      if slack < -TOL:
          report.violations.append(
              Violation("DemandUB", f"{segment.name}: pax={pax:.2f} > cap={cap:.2f}", slack)
          )

  # 8. Range feasibility
  for aircraft in opt.aircraft_names:
      for segment in opt.segments:
          if not segment.is_within_range(opt.aircrafts.range(aircraft)):
              f = flights[aircraft, segment.name]
              if f > TOL:
                  report.violations.append(
                      Violation("Range", f"{aircraft}/{segment.name}: flights={f}", -f)
                  )

  # Integrality
  for aircraft in opt.aircraft_names:
      if abs(orders[aircraft] - round(orders[aircraft])) > TOL:
          report.violations.append(Violation("Integrality_orders", aircraft, -1.0))
      for segment in opt.segments:
          f = flights[aircraft, segment.name]
          if abs(f - round(f)) > TOL:
              report.violations.append(Violation("Integrality_flights", f"{aircraft}/{segment.name}", -1.0))

  return report


# ── Diagnostics ─────────────────────────────────────────────────────

def aircraft_selection_diagnostics(
    opt: FleetOptimizer,
    result: SolverResult,
) -> List[str]:
  """Explain why each aircraft type was or was not ordered."""
  lines: List[str] = []
  if result.status != "optimal":
      return [f"Non-optimal status: {result.status}"]

  for aircraft in sorted(opt.aircraft_names):
      o = result.orders[aircraft]
      if o > 0:
          util = result.utilization[aircraft]
          lines.append(
              f"SELECTED {aircraft}: orders={o}, util={util.utilization_rate:.1%}, "
              f"casm={opt.aircrafts.casm(aircraft, True):.4f}, risk_coef={opt.aircrafts.risk_coef(aircraft)}"
          )
      else:
          reasons = []
          for segment in opt.segments:
              if not segment.is_within_range(opt.aircrafts.range(aircraft)):
                  reasons.append(f"range<{segment.distance_max}mi on {segment.name}")
          if opt.aircrafts.price(aircraft, True) > opt.budget:
              reasons.append("unit price exceeds entire budget")
          if not reasons:
              reasons.append("dominated by other types on operating economics / risk / MOQ")
          lines.append(f"REJECTED {aircraft}: " + "; ".join(reasons))
  return lines


# ── Benchmark strategies ────────────────────────────────────────────

def benchmark_cheapest_casm(
    opt: FleetOptimizer,
    result: SolverResult,
) -> Optional[str]:
  """Lowest CASM type that can serve all segments."""
  eligible = []
  for aircraft in opt.aircraft_names:
      if all(s.is_within_range(opt.aircrafts.range(aircraft)) for s in opt.segments):
          eligible.append((opt.aircrafts.casm(aircraft, True), aircraft))
  if not eligible:
      return None
  return min(eligible)[1]


def benchmark_min_risk(
    opt: FleetOptimizer,
    result: SolverResult,
) -> Optional[str]:
  eligible = []
  for aircraft in opt.aircraft_names:
      if all(s.is_within_range(opt.aircrafts.range(aircraft)) for s in opt.segments):
          eligible.append((opt.aircrafts.risk_coef(aircraft), aircraft))
  if not eligible:
      return None
  return min(eligible)[1]
