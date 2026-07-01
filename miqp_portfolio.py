# miqp_portfolio.py
"""
Fleet-acquisition MIQP solver.

Defines ``FleetOptimizer`` (the solver class) and ``SolverResult`` (the
structured output).  All parameter objects come from ``params.py``.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import gurobipy as gp
from gurobipy import GRB, quicksum

from params import (
    AircraftFamily, AircraftSelection, AirlineSelection, Demand, ModelConfig
)


# ── Result containers ───────────────────────────────────────────────

@dataclass
class AircraftUtilization:
    """Block-hour utilization for one aircraft type."""
    aircraft: str
    total_fleet_count: int                         # existing + ordered
    block_hours_used: float                        # sum of flights × block_time across segments
    block_hours_available: float                   # total_fleet_count × yearly_block_hours
    utilization_rate: float                        # used / available  (0–1)
    flights_by_segment: Dict[str, float]           # segment name → flights assigned
    block_hours_by_segment: Dict[str, float]       # segment name → block hours consumed

    @classmethod
    def empty(cls, aircraft: str, segment_names: List[str]) -> "AircraftUtilization":
        return cls(
            aircraft=aircraft,
            total_fleet_count=0,
            block_hours_used=0,
            block_hours_available=0,
            utilization_rate=0,
            flights_by_segment={name: 0 for name in segment_names},
            block_hours_by_segment={name: 0 for name in segment_names},
        )


@dataclass
class SegmentFulfillment:
    """Demand fulfillment for one demand segment."""
    segment: str
    demand_cap: float                              # market_share × segment.demand (pax)
    seats_assigned: float                          # total pax capacity assigned (flights × seats × LF)
    fill_rate: float                               # seats_assigned / demand_cap  (0–1)
    flights_by_aircraft: Dict[str, float]          # aircraft name → flights assigned

    @classmethod
    def empty(cls, segment: str, aircraft_names: List[str]) -> "SegmentFulfillment":
        return cls(
            segment=segment,
            demand_cap=0,
            seats_assigned=0,
            fill_rate=0,
            flights_by_aircraft={name: 0 for name in aircraft_names},
        )


@dataclass
class SolverResult:
    """Structured output from a single fleet-optimization solve."""

    status: str                                    # 'optimal', 'infeasible', …
    objective: Optional[float]
    time_horizon_years: int                        # from ModelConfig

    # Decision-variable values
    orders: Dict[str, int]                         # aircraft → units ordered
    flights: Dict[Tuple[str, str], float]          # (aircraft, segment) → flights/yr

    # Fleet snapshot
    existing_fleet: Dict[str, int]                 # aircraft → pre-existing count
    total_fleet: Dict[str, int]                    # aircraft → existing + ordered

    # Financial breakdown (annual values)
    revenue: float
    operating_cost: float
    fixed_cost: float
    risk_cost: float
    bulk_discount_savings: float                    # one-time acquisition saving from bulk-order discounts

    # Capacity / penetration KPIs
    total_asm: float                               # total available seat-miles
    weighted_casm: float                           # seat-mile-weighted avg CASM
    concept_asm: float                             # novel-aircraft-concept-family seat-miles
    concept_penetration: float                     # concept_asm / total_asm

    # Operational detail
    utilization: Dict[str, AircraftUtilization]    # aircraft → utilization breakdown
    segment_fulfillment: Dict[str, SegmentFulfillment]  # segment → demand fulfillment

    @property
    def annual_profit(self) -> float:
        return self.revenue - self.operating_cost - self.fixed_cost - self.risk_cost

    @property
    def total_profit(self) -> float:
        return self.time_horizon_years * self.annual_profit

    def summary(self) -> str:
        T = self.time_horizon_years
        lines = [
            f"Status        : {self.status}",
            f"Time horizon  : {T} year{'s' if T != 1 else ''}",
            f"Objective     : {self.objective:,.2f}" if self.objective is not None else "Objective     : N/A",
            f"Total profit  : {self.total_profit:,.2f}",
            "",
            "─── Orders ───",
        ]
        for aircraft, count in sorted(self.orders.items()):
            if count > 0:
                existing = self.existing_fleet.get(aircraft, 0)
                lines.append(
                    f"  {aircraft:14s}  order {count:>4d}   "
                    f"(existing {existing:>3d}  →  total {count + existing:>4d})"
                )

        lines += [
            "",
            f"─── Financials (annual) ───",
            f"  Revenue          : {self.revenue:>14,.2f}",
            f"  Operating cost   : {self.operating_cost:>14,.2f}",
            f"  Fixed cost       : {self.fixed_cost:>14,.2f}",
            f"  Risk cost        : {self.risk_cost:>14,.2f}",
            f"  Annual profit    : {self.annual_profit:>14,.2f}",
            "",
            f"─── Acquisition (one-time) ───",
            f"  Bulk discount    : {self.bulk_discount_savings:>14,.2f}",
            "",
            "─── Capacity ───",
            f"  Total ASM        : {self.total_asm:>14,.0f}",
            f"  Weighted CASM    : {self.weighted_casm:>14.4f}" if self.weighted_casm else "  Weighted CASM    :            N/A",
            f"  Concept ASM      : {self.concept_asm:>14,.0f}",
            f"  Concept share    : {self.concept_penetration:>13.1%}",
        ]

        lines += ["", "─── Aircraft Utilization ───"]
        for aircraft, utilization in sorted(self.utilization.items()):
            if utilization.total_fleet_count == 0:
                continue
            lines.append(
                f"  {aircraft:14s}  {utilization.block_hours_used:>8,.0f} / "
                f"{utilization.block_hours_available:>8,.0f} hrs  "
                f"({utilization.utilization_rate:>5.1%})"
            )
            for segment_name in sorted(utilization.flights_by_segment):
                flight_count = utilization.flights_by_segment[segment_name]
                if flight_count > 0:
                    block_hours = utilization.block_hours_by_segment[segment_name]
                    lines.append(
                        f"    └ {segment_name:16s}  {flight_count:>8,.0f} flights  "
                        f"({block_hours:>8,.0f} hrs)"
                    )

        lines += ["", "─── Demand Fulfillment ───"]
        for segment_name, fulfillment in sorted(self.segment_fulfillment.items()):
            lines.append(
                f"  {segment_name:16s}  "
                f"{fulfillment.seats_assigned:>10,.0f} / {fulfillment.demand_cap:>10,.0f} pax  "
                f"({fulfillment.fill_rate:>5.1%})"
            )
            for aircraft, flight_count in sorted(fulfillment.flights_by_aircraft.items()):
                if flight_count > 0:
                    lines.append(f"    └ {aircraft:14s}  {flight_count:>8,.0f} flights")

        return "\n".join(lines)


# ── Solver ──────────────────────────────────────────────────────────

class FleetOptimizer:
    """Builds and solves the fleet-acquisition MIQP for one airline.

    All inputs are set at construction time via the OO parameter objects
    defined in ``params.py``.  The only public method is ``solve()``,
    which returns a self-contained ``SolverResult``.
    """

    # ── construction ─────────────────────────────────────────────

    def __init__(
        self,
        aircrafts: AircraftSelection,
        airlines: AirlineSelection,
        airline_name: str,
        demand: Demand,
        config: ModelConfig = ModelConfig(),
    ):
        # Input objects (never mutated)
        self.aircrafts    = aircrafts
        self.airlines     = airlines
        self.airline_name = airline_name
        self.demand       = demand
        self.config       = config

        # Lists used for iteration
        self.aircraft_names = aircrafts.names
        self.segments       = demand.segments
        self.segment_names  = [s.name for s in demand.segments]

        # Airline attributes used in MIQP
        self.budget                = airlines.budget(airline_name)
        self.load_factor           = airlines.load_factor(airline_name)
        self.yield_per_mile        = airlines.yield_per_mile(airline_name)
        self.ancillary_per_pax     = airlines.ancillary_per_pax(airline_name)
        self.max_aircraft_types    = airlines.max_aircraft_types(airline_name)
        self.moq_threshold         = airlines.moq_threshold(airline_name)
        self.risk_aversion         = airlines.risk_aversion(airline_name)
        self.market_share          = airlines.market_share(airline_name)

        # Bulk-order discount parameters (ModelConfig; eq 39-44)
        self.bulk_discount_rate      = config.bulk_discount_rate
        self.bulk_discount_threshold = config.bulk_discount_threshold

        # Family groupings over the selected aircraft, used for the family-level
        # MOQ (eq 50-52) and infrastructure-cost (eq 39) terms.
        self.families = aircrafts.families()                  # family -> [aircraft names]
        self.existing_family_count = {                        # existing aircraft per family (data constant)
            family: sum(airlines.fleet_count(airline_name, name) for name in members)
            for family, members in self.families.items()
        }

        # Aircraft attributes used in the MIQP. These are accessed via self.aircrafts.attr_for_aircraft(aircraft):
        #   seats              — revenue, operating cost, demand constraints
        #   casm               — operating cost (with adjustments applied)
        #   range              — range feasibility constraints
        #   price              — budget constraint
        #   infra_cost         — budget constraint
        #   yearly_fixed_cost  — fixed cost objective term
        #   yearly_block_hours — block hours constraints
        #   risk_coef          — risk cost objective term
        #   family             — concept penetration KPI, MOQ + infra-cost grouping

    # ── public API ───────────────────────────────────────────────

    def solve(self, *, verbose: bool = False) -> SolverResult:
        """Build the MIQP, solve it, and return a ``SolverResult``."""
        self._create_model(verbose)
        self._add_decision_variables()
        self._set_objective()
        self._add_constraints()
        self._model.optimize()
        return self._build_result()

    # ── model creation ───────────────────────────────────────────

    def _create_model(self, verbose: bool) -> None:
        self._model = gp.Model("Fleet_Optimization")
        if not verbose:
            self._model.setParam("OutputFlag", 0)
        if self.config.mip_gap is not None:
            self._model.setParam("MIPGap", self.config.mip_gap)
        if self.config.time_limit_seconds is not None:
            self._model.setParam("TimeLimit", self.config.time_limit_seconds)

    def _add_decision_variables(self) -> None:
        model = self._model

        # Number of aircraft to purchase per type
        self._orders = {
            aircraft: model.addVar(vtype=GRB.INTEGER, lb=0, name=f"orders_{aircraft}")
            for aircraft in self.aircraft_names
        }
        # Number of flights assigned to each aircraft type on each segment
        self._flights = {
            (aircraft, segment.name): model.addVar(vtype=GRB.INTEGER, lb=0, name=f"flights_{aircraft}_{segment.name}")
            for aircraft in self.aircraft_names
            for segment in self.segments
        }
        # Indicator: whether a fleet type is used (used to enforce max # fleet types)
        self._type_used = {
            aircraft: model.addVar(vtype=GRB.BINARY, name=f"type_used_{aircraft}")
            for aircraft in self.aircraft_names
        }
        # Indicator: whether the bulk-order discount is active for a type (v_i, eq 40-41)
        self._bulk_discount_active = {
            aircraft: model.addVar(vtype=GRB.BINARY, name=f"bulk_discount_{aircraft}")
            for aircraft in self.aircraft_names
        }
        # McCormick auxiliary for orders_i · v_i (n_i, eq 42-44): discounted order volume
        self._discounted_orders = {
            aircraft: model.addVar(vtype=GRB.CONTINUOUS, lb=0, name=f"discounted_orders_{aircraft}")
            for aircraft in self.aircraft_names
        }
        # Indicator: whether any aircraft in a family is purchased (buy_family_f, eq 50-52)
        self._buy_family = {
            family: model.addVar(vtype=GRB.BINARY, name=f"buy_family_{family.name}")
            for family in self.families
        }

        model.update()

    # ── derived quantities ───────────────────────────────────────

    def _asm(self, aircraft: str, segment) -> "gp.LinExpr":
        """Available seat-miles for a type on a segment: flights · seats · distance."""
        return (
            self._flights[aircraft, segment.name]
            * self.aircrafts.seats(aircraft)
            * segment.midpoint
        )

    def _pax(self, aircraft: str, segment) -> "gp.LinExpr":
        """Expected passengers for a type on a segment: flights · seats · load_factor."""
        return (
            self._flights[aircraft, segment.name]
            * self.aircrafts.seats(aircraft)
            * self.load_factor
        )

    # ── objective ────────────────────────────────────────────────

    def _revenue_expression(self):
        """Ticket revenue (yield · ASM · load_factor) + ancillary revenue (per PAX)."""
        return quicksum(
            self.yield_per_mile * self._asm(aircraft, segment) * self.load_factor
            + self.ancillary_per_pax * self._pax(aircraft, segment)
            for aircraft in self.aircraft_names
            for segment in self.segments
        )

    def _operating_cost_expression(self):
        """Distance-based operating cost: CASM · ASM."""
        aircrafts = self.aircrafts
        return quicksum(
            aircrafts.casm(aircraft, apply_adjustments=True) * self._asm(aircraft, segment)
            for aircraft in self.aircraft_names
            for segment in self.segments
        )

    def _fixed_cost_expression(self):
        """Yearly fixed cost over the full fleet (newly ordered + existing aircraft)."""
        aircrafts = self.aircrafts
        orders    = self._orders

        return quicksum(
            aircrafts.yearly_fixed_cost(aircraft)
            * (orders[aircraft] + self.airlines.fleet_count(self.airline_name, aircraft))
            for aircraft in self.aircraft_names
        )

    def _risk_cost_expression(self):
        """Quadratic risk penalty: risk_aversion · Σ risk_coef · orders².

        The airline's risk aversion and each aircraft type's risk coefficient
        combine to penalize large, concentrated orders of riskier types."""
        aircrafts = self.aircrafts
        orders    = self._orders

        return self.risk_aversion * quicksum(
            aircrafts.risk_coef(aircraft) * orders[aircraft] * orders[aircraft]
            for aircraft in self.aircraft_names
        )

    def _set_objective(self) -> None:
        self._revenue_expr        = self._revenue_expression()
        self._operating_cost_expr = self._operating_cost_expression()
        self._fixed_cost_expr     = self._fixed_cost_expression()
        self._risk_cost_expr      = self._risk_cost_expression()

        T = self.config.time_horizon_years

        # Annual operating profit, scaled by the planning horizon (eq 38).
        # Acquisition capital is intentionally excluded from the objective and
        # enforced through the budget constraint instead.
        annual_profit = (
            self._revenue_expr
            - self._operating_cost_expr
            - self._fixed_cost_expr
            - self._risk_cost_expr
        )

        self._model.setObjective(T * annual_profit, GRB.MAXIMIZE)

    # ── constraints ──────────────────────────────────────────────

    def _add_budget_constraint(self) -> None:
        """Acquisition spend, net of bulk discounts, plus new-family start-up
        costs must stay within the airline's capital budget (eq 39)."""
        aircrafts = self.aircrafts
        orders    = self._orders

        acquisition_cost = quicksum(
            aircrafts.price(aircraft, apply_adjustments=True) * orders[aircraft]
            for aircraft in self.aircraft_names
        )
        # Bulk-order discount applied to discounted order volume n_i (eq 39 term 2).
        bulk_discount = quicksum(
            self.bulk_discount_rate * aircrafts.price(aircraft, apply_adjustments=True) * self._discounted_orders[aircraft]
            for aircraft in self.aircraft_names
        )
        # Infrastructure / start-up cost, charged once per family and only for
        # families not already present in the airline's initial fleet (eq 39 term 3).
        infra_cost = quicksum(
            aircrafts.family_infra_cost(family) * self._buy_family[family]
            for family in self.families
            if self.existing_family_count[family] == 0
        )

        self._model.addConstr(
            acquisition_cost - bulk_discount + infra_cost <= self.budget,
            "Budget",
        )

    def _add_block_hours_constraints(self) -> None:
        aircrafts = self.aircrafts
        orders    = self._orders
        flights   = self._flights

        for aircraft in self.aircraft_names:
            existing_count = self.airlines.fleet_count(self.airline_name, aircraft)
            self._model.addConstr(
                quicksum(flights[aircraft, segment.name] * segment.block_time for segment in self.segments) 
                <= aircrafts.yearly_block_hours(aircraft) * (orders[aircraft] + existing_count),
                name=f"block_hours_{aircraft}",
            )

    def _add_max_types_constraint(self) -> None:
        type_used = self._type_used

        self._model.addConstr(
            quicksum(type_used[aircraft] for aircraft in self.aircraft_names)
            <= self.max_aircraft_types,
            "MaxTypes",
        )
    
    def _add_order_type_link_constraints(self) -> None:
        """Link order ↔ type indicator (if orders[i] > 0 then type_used[i] = 1)"""
        orders    = self._orders
        type_used = self._type_used

        for aircraft in self.aircraft_names:
            self._model.addConstr(
                orders[aircraft] <= self.config.big_m * type_used[aircraft],
                f"Link_{aircraft}",
            )
    
    def _add_bulk_discount_constraints(self) -> None:
        """Activate the bulk-order discount once a type's order meets the
        threshold, and linearize orders·v_i via McCormick (eq 40-44)."""
        orders          = self._orders
        discount_active = self._bulk_discount_active
        discounted_order_volume      = self._discounted_orders
        threshold       = self.bulk_discount_threshold
        big_m           = self.config.big_m

        for aircraft in self.aircraft_names:
            # v_i = 1 only when orders_i >= threshold (eq 40-41).
            self._model.addConstr(
                orders[aircraft] >= threshold * discount_active[aircraft],
                f"BulkDiscount_activate_{aircraft}",
            )
            self._model.addConstr(
                orders[aircraft] <= (threshold - 1) + big_m * discount_active[aircraft],
                f"BulkDiscount_threshold_{aircraft}",
            )
            # McCormick linearization of n_i = orders_i · v_i (eq 42-44).
            self._model.addConstr(
                discounted_order_volume[aircraft] <= big_m * discount_active[aircraft],
                f"McCormick_ub_v_{aircraft}",
            )
            self._model.addConstr(
                discounted_order_volume[aircraft] <= orders[aircraft],
                f"McCormick_ub_orders_{aircraft}",
            )
            self._model.addConstr(
                discounted_order_volume[aircraft] >= orders[aircraft] - big_m * (1 - discount_active[aircraft]),
                f"McCormick_lb_{aircraft}",
            )

    def _add_moq_constraints(self) -> None:
        """Minimum-order-quantity per family: introducing any type in a family
        requires the family to reach moq_threshold aircraft (existing count
        included), and links buy_family to family orders (eq 50-52)."""
        orders    = self._orders
        big_m     = self.config.big_m
        threshold = self.moq_threshold

        for family, members in self.families.items():
            family_orders        = quicksum(orders[aircraft] for aircraft in members)
            existing_count       = self.existing_family_count[family]
            buy_family           = self._buy_family[family]

            # Meet the MOQ when the family is purchased (eq 50).
            self._model.addConstr(
                existing_count + family_orders >= threshold * buy_family,
                f"MOQ_threshold_{family.name}",
            )
            # Link buy_family to family orders (eq 51-52).
            self._model.addConstr(
                family_orders <= big_m * buy_family,
                f"MOQ_link_ub_{family.name}",
            )
            self._model.addConstr(
                family_orders >= buy_family,
                f"MOQ_link_lb_{family.name}",
            )

    def _add_demand_upper_bound_constraints(self) -> None:
        """Passengers carried on a segment cannot exceed the airline's
        market-share-limited demand (eq 49)."""
        for segment in self.segments:
            self._model.addConstr(
                quicksum(self._pax(aircraft, segment) for aircraft in self.aircraft_names)
                <= self.market_share * segment.demand,
                name=f"demand_ub_{segment.name}",
            )

    def _add_range_feasibility_constraints(self) -> None:
        aircrafts = self.aircrafts
        flights   = self._flights

        for aircraft in self.aircraft_names:
            for segment in self.segments:
                if not segment.is_within_range(aircrafts.range(aircraft)):
                    self._model.addConstr(
                        flights[aircraft, segment.name] == 0,
                        name=f"range_{aircraft}_{segment.name}",
                    )

    def _add_constraints(self) -> None:
        self._add_budget_constraint()              # 1  Budget (eq 39)
        self._add_block_hours_constraints()        # 2  Block-hours utilization per type (eq 45)
        self._add_max_types_constraint()           # 3  Max distinct fleet types (eq 47)
        self._add_order_type_link_constraints()    # 4  Link order ↔ type indicator (eq 48)
        self._add_bulk_discount_constraints()      # 5  Bulk-order discount + McCormick (eq 40-44)
        self._add_moq_constraints()                # 6  Per-family minimum order quantity (eq 50-52)
        self._add_demand_upper_bound_constraints() # 7  Demand cap / market share (eq 49)
        self._add_range_feasibility_constraints()  # 8  Range feasibility (eq 46)

    # ── result extraction ────────────────────────────────────────

    def _build_utilization(
        self,
        solved_flights: Dict[Tuple[str, str], float],
        total_fleet: Dict[str, int],
    ) -> Dict[str, AircraftUtilization]:
        aircrafts  = self.aircrafts
        utilization: Dict[str, AircraftUtilization] = {}

        for aircraft in self.aircraft_names:
            fleet_count     = total_fleet[aircraft]
            hours_available = fleet_count * aircrafts.yearly_block_hours(aircraft)

            flights_by_segment:     Dict[str, float] = {}
            block_hours_by_segment: Dict[str, float] = {}
            total_hours_used = 0.0

            for segment in self.segments:
                flight_count  = solved_flights[aircraft, segment.name]
                segment_hours = flight_count * segment.block_time
                flights_by_segment[segment.name]     = flight_count
                block_hours_by_segment[segment.name] = segment_hours
                total_hours_used += segment_hours

            utilization[aircraft] = AircraftUtilization(
                aircraft=aircraft,
                total_fleet_count=fleet_count,
                block_hours_used=total_hours_used,
                block_hours_available=hours_available,
                utilization_rate=total_hours_used / hours_available if hours_available > 0 else 0.0,
                flights_by_segment=flights_by_segment,
                block_hours_by_segment=block_hours_by_segment,
            )

        return utilization

    def _build_segment_fulfillment(
        self,
        solved_flights: Dict[Tuple[str, str], float],
    ) -> Dict[str, SegmentFulfillment]:
        aircrafts = self.aircrafts
        segment_fulfillment: Dict[str, SegmentFulfillment] = {}

        for segment in self.segments:
            demand_cap           = self.market_share * segment.demand
            flights_by_aircraft: Dict[str, float] = {}
            total_seats_assigned = 0.0

            for aircraft in self.aircraft_names:
                flight_count = solved_flights[aircraft, segment.name]
                flights_by_aircraft[aircraft] = flight_count
                total_seats_assigned += flight_count * aircrafts.seats(aircraft) * self.load_factor

            segment_fulfillment[segment.name] = SegmentFulfillment(
                segment=segment.name,
                demand_cap=demand_cap,
                seats_assigned=total_seats_assigned,
                fill_rate=total_seats_assigned / demand_cap if demand_cap > 0 else 0.0,
                flights_by_aircraft=flights_by_aircraft,
            )

        return segment_fulfillment

    def _build_capacity_kpis(
        self,
        solved_flights: Dict[Tuple[str, str], float],
    ) -> Tuple[float, float, float, float]:
        """Returns (total_asm, weighted_casm, concept_asm, concept_penetration)."""
        aircrafts      = self.aircrafts
        total_asm      = 0.0
        concept_asm    = 0.0
        cost_numerator = 0.0

        for aircraft in self.aircraft_names:
            for segment in self.segments:
                asm = solved_flights[aircraft, segment.name] * aircrafts.seats(aircraft) * segment.midpoint
                total_asm      += asm
                cost_numerator += aircrafts.casm(aircraft, apply_adjustments=True) * asm
                if aircrafts.family(aircraft) == AircraftFamily.NOVEL_AIRCRAFT_CONCEPT:
                    concept_asm += asm

        weighted_casm       = cost_numerator / total_asm if total_asm > 0 else 0.0
        concept_penetration = concept_asm / total_asm if total_asm > 0 else 0.0

        return total_asm, weighted_casm, concept_asm, concept_penetration

    def _build_result(self) -> SolverResult:
        status_map = {
            GRB.OPTIMAL: "optimal",
            GRB.INFEASIBLE: "infeasible",
            GRB.INF_OR_UNBD: "infeasible_or_unbounded",
            GRB.UNBOUNDED: "unbounded",
        }
        status = status_map.get(self._model.Status, f"gurobi_{self._model.Status}")

        # if the model is not optimal, return a SolverResult with all zeros
        if self._model.Status != GRB.OPTIMAL:
            zeroed_fleet = {aircraft: 0 for aircraft in self.aircraft_names}
            return SolverResult(
                status=status, objective=None,
                time_horizon_years=self.config.time_horizon_years,
                orders=zeroed_fleet,
                flights={
                    (aircraft, segment.name): 0.0
                    for aircraft in self.aircraft_names
                    for segment in self.segments
                },
                existing_fleet={
                    aircraft: self.airlines.fleet_count(self.airline_name, aircraft)
                    for aircraft in self.aircraft_names
                },
                total_fleet=zeroed_fleet,
                revenue=0, operating_cost=0, fixed_cost=0,
                risk_cost=0, bulk_discount_savings=0,
                total_asm=0, weighted_casm=0,
                concept_asm=0, concept_penetration=0,
                utilization={
                    aircraft: AircraftUtilization.empty(aircraft, self.segment_names)
                    for aircraft in self.aircraft_names
                },
                segment_fulfillment={
                    segment.name: SegmentFulfillment.empty(segment.name, self.aircraft_names)
                    for segment in self.segments
                },
            )

        # ── read solved values ───────────────────────────────────────
        solved_orders = {
            aircraft: int(round(self._orders[aircraft].X))
            for aircraft in self.aircraft_names
        }
        solved_flights = {
            (aircraft, segment.name): self._flights[aircraft, segment.name].X
            for aircraft in self.aircraft_names
            for segment in self.segments
        }
        existing_fleet = {
            aircraft: self.airlines.fleet_count(self.airline_name, aircraft)
            for aircraft in self.aircraft_names
        }
        total_fleet = {
            aircraft: existing_fleet[aircraft] + solved_orders[aircraft]
            for aircraft in self.aircraft_names
        }

        # ── financial KPIs (from objective-component expressions) ────
        solved_revenue        = self._revenue_expr.getValue()
        solved_operating_cost = self._operating_cost_expr.getValue()
        solved_fixed_cost     = self._fixed_cost_expr.getValue()
        solved_risk_cost      = self._risk_cost_expr.getValue()
        # Realized bulk-order discount savings (eq 39 term 2).
        solved_bulk_discount  = sum(
            self.bulk_discount_rate * self.aircrafts.price(aircraft, apply_adjustments=True) * self._discounted_orders[aircraft].X
            for aircraft in self.aircraft_names
        )

        # ── aircraft utilization ─────────────────────────────────────
        utilization = self._build_utilization(solved_flights, total_fleet)

        # ── segment fulfillment ──────────────────────────────────────
        segment_fulfillment = self._build_segment_fulfillment(solved_flights)

        # ── capacity KPIs ────────────────────────────────────────────
        total_asm, weighted_casm, concept_asm, concept_penetration = self._build_capacity_kpis(solved_flights)

        return SolverResult(
            status=status,
            objective=self._model.ObjVal,
            time_horizon_years=self.config.time_horizon_years,
            orders=solved_orders,
            flights=solved_flights,
            existing_fleet=existing_fleet,
            total_fleet=total_fleet,
            revenue=solved_revenue,
            operating_cost=solved_operating_cost,
            fixed_cost=solved_fixed_cost,
            risk_cost=solved_risk_cost,
            bulk_discount_savings=solved_bulk_discount,
            total_asm=total_asm,
            weighted_casm=weighted_casm,
            concept_asm=concept_asm,
            concept_penetration=concept_penetration,
            utilization=utilization,
            segment_fulfillment=segment_fulfillment,
        )


if __name__ == "__main__":
    # Example usage with dummy data defined in params.py.
    from params import demand as default_demand

    optimizer = FleetOptimizer(
        aircrafts=AircraftSelection(),      # all aircraft
        airlines=AirlineSelection(),        # all airlines
        airline_name="Leader",
        demand=default_demand,
    )
    result = optimizer.solve(verbose=True)
    print(result.summary())
