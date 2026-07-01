# params.py
from dataclasses import dataclass, make_dataclass, field, replace
from enum import Enum
from typing import Any, Callable, Dict, Optional


# ── Model configuration ─────────────────────────────────────────────

@dataclass(frozen=True)
class ModelConfig:
    """Global parameters that govern the MIQP formulation and solver behavior.

    These are independent of aircraft, airline, and demand data.
    Pass to ``FleetOptimizer`` to override defaults.
    """
    time_horizon_years: int = 1                      # number of years the fleet operates (scales annual profit terms)
    big_m: int = 100_000                             # upper bound on orders per type (linking constraint)
    mip_gap: Optional[float] = None                  # Gurobi MIPGap (None = Gurobi default ~1e-4)
    time_limit_seconds: Optional[int] = None         # Gurobi TimeLimit (None = no limit)
    bulk_discount_rate: float = 0.00                 # delta: fractional price discount applied to bulk orders
    bulk_discount_threshold: int = 10                # minimum orders of a type required to trigger the bulk discount

# Aircraft family definitions
class AircraftFamily(Enum):
    NOVEL_AIRCRAFT_CONCEPT = 'Novel_Aircraft_Concept_Family'
    B737MAX = 'B737Max_Family'
    A320NEO = 'A320Neo_Family'
    A220 = 'A220_Family'
    E_JET = 'E-Jet_Family'

# Attributes that define an aircraft model
@dataclass(frozen=True)
class Aircraft:
    name: str
    family: AircraftFamily
    max_flights_per_day: int
    yearly_block_hours: int
    range: int
    price: float
    seats: int
    infra_cost: int
    casm: float
    # revenue_per_asm
    risk_coef: float  # technological/operational risk coefficient for this aircraft type (eq 38 risk penalty)
    # q
    # BIG
    yearly_fixed_cost: int
    price_adjustment: float = 0.0 # incentives or penalties on purchase price
    casm_adjustment: float = 0.0 # incentives or penalties on casm

    def apply_adjustment(self, attribute: str, original_value: float) -> float:
        """Apply the adjustment (incentive or penalty) to price or CASM."""
        if attribute == "price":
            return original_value + self.price_adjustment
        elif attribute == "casm":
            return original_value + self.casm_adjustment
        else:
            raise ValueError(f"Invalid attribute '{attribute}'. Only 'price' and 'casm' are allowed.")

# Defines the complete catalog of aircrafts and their attributes
class Aircrafts(Enum):
    CONCEPT_A = Aircraft(name='Concept_A', family=AircraftFamily.NOVEL_AIRCRAFT_CONCEPT, max_flights_per_day=3, yearly_block_hours=3500, range=3500, price=55, seats=189, infra_cost=100, yearly_fixed_cost=5, casm=0.12, risk_coef=268)
    CONCEPT_B = Aircraft(name='Concept_B', family=AircraftFamily.NOVEL_AIRCRAFT_CONCEPT, max_flights_per_day=4, yearly_block_hours=3000, range=2000, price=9, seats=120, infra_cost=10, yearly_fixed_cost=2, casm=0.08, risk_coef=5)
    CONCEPT_C = Aircraft(name='Concept_C', family=AircraftFamily.NOVEL_AIRCRAFT_CONCEPT, max_flights_per_day=4, yearly_block_hours=3200, range=2500, price=12, seats=150, infra_cost=10, yearly_fixed_cost=2, casm=0.08, risk_coef=5)
    B737MAX7 = Aircraft(name='B737Max7', family=AircraftFamily.B737MAX, max_flights_per_day=3, yearly_block_hours=3400, range=4430, price=50, seats=172, infra_cost=0, yearly_fixed_cost=5, casm=0.12, risk_coef=1)
    B737MAX8 = Aircraft(name='B737Max8', family=AircraftFamily.B737MAX, max_flights_per_day=3, yearly_block_hours=3500, range=3500, price=55, seats=189, infra_cost=100, yearly_fixed_cost=5, casm=0.12, risk_coef=1)
    B737MAX9 = Aircraft(name='B737Max9', family=AircraftFamily.B737MAX, max_flights_per_day=3, yearly_block_hours=3500, range=3797, price=60, seats=220, infra_cost=0, yearly_fixed_cost=5, casm=0.12, risk_coef=1)
    A319Neo = Aircraft(name='A319Neo', family=AircraftFamily.A320NEO, max_flights_per_day=3, yearly_block_hours=3300, range=4315, price=50, seats=145, infra_cost=0, yearly_fixed_cost=5, casm=0.12, risk_coef=1)
    A320Neo = Aircraft(name='A320Neo', family=AircraftFamily.A320NEO, max_flights_per_day=3, yearly_block_hours=3500, range=3400, price=55, seats=180, infra_cost=100, yearly_fixed_cost=5, casm=0.12, risk_coef=1)
    A321Nx = Aircraft(name='A321Nx', family=AircraftFamily.A320NEO, max_flights_per_day=3, yearly_block_hours=3600, range=4603, price=64, seats=244, infra_cost=0, yearly_fixed_cost=5, casm=0.12, risk_coef=1)
    A220_300 = Aircraft(name='A220-300', family=AircraftFamily.A220, max_flights_per_day=3, yearly_block_hours=3400, range=3912, price=38, seats=153, infra_cost=0, yearly_fixed_cost=5, casm=0.12, risk_coef=1)
    E190 = Aircraft(name='E190', family=AircraftFamily.E_JET, max_flights_per_day=3, yearly_block_hours=3000, range=3280, price=37.5, seats=114, infra_cost=0, yearly_fixed_cost=5, casm=0.12, risk_coef=1)
    E195 = Aircraft(name='E195', family=AircraftFamily.E_JET, max_flights_per_day=3, yearly_block_hours=3100, range=2992, price=40, seats=114, infra_cost=0, yearly_fixed_cost=5, casm=0.12, risk_coef=1)

    @classmethod
    def all_aircrafts(cls):
        return [aircraft.value for aircraft in cls]


# Map a human aircraft model name (Aircraft.name) to the Fleet field name.
# Example: "B737Max9" -> "B737MAX9", "A220-300" -> "A220_300".
MODEL_NAME_TO_FLEET_FIELD: Dict[str, str] = {
    enum.value.name: enum.name for enum in Aircrafts
}

# Create a filtered set of aircraft based on attributes (e.g., range, seats)
# E.g., only include aircraft with range > 3000 miles: selection = AircraftSelection(lambda a: a.range > 3000)
# Also defines how to access attributes for the selected aircrafts, and can apply MOFD overrides to update attributes based on policy changes or new data
# E.g., selection.seats("A320Neo") to get the number of seats for A320Neo, or selection.price("B737Max8") to get the price for B737Max8
# E.g., selection.apply_mofd({'B737Max8': {'price': 52, 'casm': 0.11}}) to update price and casm for B737Max8 based on new information or policy changes
class AircraftSelection:
    def __init__(self, selection_filter: Callable[[Aircraft], bool] | None = None):
        aircrafts = [ enum.value for enum in Aircrafts ]

        if selection_filter is not None:
            aircrafts = list(filter(selection_filter, aircrafts))

        self._aircrafts: Dict[str, Aircraft] = { aircraft.name: aircraft for aircraft in aircrafts }

    def apply_mofd(self, overrides: Dict[str, Dict[str, int | float]]):
        """
        Update aircraft parameters using user-provided overrides.

        overrides format:
        {
            "A320Neo": {"max_flights_per_day": 4},
            "Concept_A": {"seats": 100, "range": 1800}
        }
        """
        for aircraft_name, attrs in overrides.items():

            if aircraft_name not in self._aircrafts:
                raise ValueError(f"Unknown aircraft: {aircraft_name}")

            aircraft = self._aircrafts[aircraft_name]

            # Validate attribute names
            for attr in attrs:
                if not hasattr(aircraft, attr):
                    raise ValueError(f"{attr} is not a valid Aircraft attribute")

            # Create updated aircraft instance
            updated_aircraft = replace(aircraft, **attrs)

            # Store updated version
            self._aircrafts[aircraft_name] = updated_aircraft


    @property
    def names(self) -> list[str]:
        return list(self._aircrafts.keys())

    def _resolve(self, aircraft: str | Aircraft) -> Aircraft:
        """Resolve a name or ``Aircraft`` to its (possibly overridden) catalog entry."""
        name = aircraft.name if isinstance(aircraft, Aircraft) else aircraft
        return self._aircrafts[name]

    def family(self, aircraft: str | Aircraft) -> AircraftFamily:
        return self._resolve(aircraft).family

    def max_flights_per_day(self, aircraft: str | Aircraft) -> int:
        return self._resolve(aircraft).max_flights_per_day

    def range(self, aircraft: str | Aircraft) -> int:
        return self._resolve(aircraft).range

    def price(self, aircraft: str | Aircraft, apply_adjustments: bool = False) -> float:
        """Return the price, optionally applying purchase incentives/penalties."""
        ac = self._resolve(aircraft)
        return ac.apply_adjustment("price", ac.price) if apply_adjustments else ac.price

    def seats(self, aircraft: str | Aircraft) -> int:
        return self._resolve(aircraft).seats

    def infra_cost(self, aircraft: str | Aircraft) -> int:
        return self._resolve(aircraft).infra_cost

    def yearly_fixed_cost(self, aircraft: str | Aircraft) -> int:
        return self._resolve(aircraft).yearly_fixed_cost

    def casm(self, aircraft: str | Aircraft, apply_adjustments: bool = False) -> float:
        """Return the CASM, optionally applying operating incentives/penalties."""
        ac = self._resolve(aircraft)
        return ac.apply_adjustment("casm", ac.casm) if apply_adjustments else ac.casm

    def risk_coef(self, aircraft: str | Aircraft) -> float:
        return self._resolve(aircraft).risk_coef

    def yearly_block_hours(self, aircraft: str | Aircraft) -> int:
        return self._resolve(aircraft).yearly_block_hours

    def families(self) -> Dict[AircraftFamily, list[str]]:
        """Group the selected aircraft types by family.

        Returns a mapping ``family -> [aircraft names]`` restricted to the
        types currently in this selection.  Used to express family-level
        constraints (MOQ, infrastructure cost) in the MIQP.
        """
        grouped: Dict[AircraftFamily, list[str]] = {}
        for name, aircraft in self._aircrafts.items():
            grouped.setdefault(aircraft.family, []).append(name)
        return grouped

    def family_infra_cost(self, family: AircraftFamily) -> int:
        """One-time infrastructure cost to introduce ``family`` into a fleet.

        Per-type ``infra_cost`` values are retained in the catalog; the
        family-level start-up cost is taken as the maximum infra cost across
        the family's selected member types (charged once per new family in the
        budget constraint, eq 39).
        """
        member_costs = [
            aircraft.infra_cost
            for aircraft in self._aircrafts.values()
            if aircraft.family == family
        ]
        return max(member_costs) if member_costs else 0

# Defines the fleet composition for each airline
Fleet = make_dataclass('Fleet', [(aircraft.name, int, field(default=0)) for aircraft in Aircrafts], frozen=True)

# A class of predefined fleets for the Leader and Follower airlines
class Fleets(Enum):
    Leader = Fleet(A220_300=20, A319Neo=40, A320Neo=70, A321Nx=120, B737MAX9=60)
    Follower = Fleet(E190=30, E195=35, A320Neo=40, B737MAX8=50)
    # Empty fleet — used by sensitivity-study airlines that start with no aircraft.
    Empty = Fleet()

# Airline persona definitions
class AirlinePersonas(Enum):
    ULCC = 'Ultra_Low_Cost_Carrier'
    LCC = 'Low_Cost_Carrier'
    FSC = 'Full_Service_Carrier'

# Attributes that define an airline (e.g., economic, strategic)
@dataclass(frozen=True)
class Airline:
    name: str
    persona: AirlinePersonas
    budget: float
    risk_aversion: float
    load_factor: float
    market_share: float
    yield_per_mile: float
    ancillary_per_pax: float
    fleet: Any
    moq_threshold: int  # minimum aircraft a family must reach (incl. existing) once any of its types is ordered (eq 50)
    max_aircraft_types: int

# Predefined airlines tied to the Fleets above
class Airlines(Enum):
    Leader = Airline(
        name='Leader',
        persona=AirlinePersonas.FSC,
        budget=5000,
        risk_aversion=500,
        load_factor=0.85,
        market_share=0.5,
        yield_per_mile=0.15,
        ancillary_per_pax=10,
        fleet=Fleets.Leader.value,
        moq_threshold=5,
        max_aircraft_types=10,
    )
    Follower = Airline(
        name='Follower',
        persona=AirlinePersonas.LCC,
        budget=4200,
        risk_aversion=500,
        load_factor=0.85,
        market_share=0.5,
        yield_per_mile=0.15,
        ancillary_per_pax=10,
        fleet=Fleets.Follower.value,
        moq_threshold=5,
        max_aircraft_types=10,
    )
    # Single-fleet airline used by Study 1 of the sensitivity analysis.
    # Starts with no aircraft, takes the entire market (market_share=1.0),
    # and is constrained to acquire at most one aircraft type.
    Study1_Airline = Airline(
        name='Study1_Airline',
        persona=AirlinePersonas.FSC,
        budget=2000,                # > 30 × $55M acquisition + infra; plenty of headroom
        risk_aversion=500,          # same as Leader/Follower so the comparison is apples-to-apples
        load_factor=0.85,
        market_share=1.0,           # serves the entire study demand
        yield_per_mile=0.15,
        ancillary_per_pax=10,
        fleet=Fleets.Empty.value,   # no existing fleet
        moq_threshold=5,
        max_aircraft_types=1,       # study constraint: only one fleet type allowed
    )

# Create a filtered set of airlines based on attributes (e.g., persona, risk, market share)
# Also defines how to access attributes for the selected airlines, and can apply MOFD overrides to update attributes based on policy changes or new data
# E.g., selection.risk_aversion("Leader") to get the risk_aversion for Leader, or selection.market_share("Follower") to get the market_share for Follower
# E.g., selection.apply_mofd({'Leader': {'risk_aversion': 0.5, 'market_share': 0.3}}) to update risk_aversion and market_share for Leader based on new information or policy changes
class AirlineSelection:
    def __init__(self, selection_filter: Callable[[Airline], bool] | None = None):
        airlines = [ enum.value for enum in Airlines ]

        if selection_filter is not None:
            airlines = list(filter(selection_filter, airlines))

        self._airlines: Dict[str, Airline] = { airline.name: airline for airline in airlines }
    
    def apply_mofd(self, overrides: Dict[str, Dict[str, int | float]]):
        """
        Update airline parameters using user-provided overrides.

        overrides format:
        {
            "Leader": {"risk_aversion": 0.5},
            "Follower": {"market_share": 0.3, "load_factor": 0.85}
        }
        """
        for airline_name, attrs in overrides.items():

            if airline_name not in self._airlines:
                raise ValueError(f"Unknown airline: {airline_name}")

            airline = self._airlines[airline_name]

            # Validate attribute names
            for attr in attrs:
                if not hasattr(airline, attr):
                    raise ValueError(f"{attr} is not a valid Airline attribute")

            # Create updated airline instance
            updated_airline = replace(airline, **attrs)

            # Store updated version
            self._airlines[airline_name] = updated_airline


    @property
    def names(self) -> list[str]:
        return list(self._airlines.keys())

    def _resolve(self, airline: str | Airline) -> Airline:
        """Resolve a name or ``Airline`` to its (possibly overridden) entry."""
        name = airline.name if isinstance(airline, Airline) else airline
        return self._airlines[name]

    def persona(self, airline: str | Airline) -> AirlinePersonas:
        return self._resolve(airline).persona

    def budget(self, airline: str | Airline) -> float:
        return self._resolve(airline).budget

    def risk_aversion(self, airline: str | Airline) -> float:
        return self._resolve(airline).risk_aversion

    def load_factor(self, airline: str | Airline) -> float:
        return self._resolve(airline).load_factor

    def market_share(self, airline: str | Airline) -> float:
        return self._resolve(airline).market_share

    def yield_per_mile(self, airline: str | Airline) -> float:
        return self._resolve(airline).yield_per_mile

    def ancillary_per_pax(self, airline: str | Airline) -> float:
        return self._resolve(airline).ancillary_per_pax

    def fleet(self, airline: str | Airline) -> Any:
        return self._resolve(airline).fleet

    def moq_threshold(self, airline: str | Airline) -> int:
        return self._resolve(airline).moq_threshold

    def max_aircraft_types(self, airline: str | Airline) -> int:
        return self._resolve(airline).max_aircraft_types

    def fleet_count(self, airline: str | Airline, aircraft: str | Aircraft | Aircrafts) -> int:
        """Return the number of a given aircraft in the specified airline's fleet.

        Accepts either:
        - aircraft model name (e.g., "A320Neo", "B737Max9", "A220-300"),
        - an `Aircraft` instance,
        - or an `Aircrafts` enum member.

        Unknown aircraft returns 0.
        """
        if isinstance(aircraft, Aircrafts):
            aircraft_name = aircraft.value.name
        elif isinstance(aircraft, Aircraft):
            aircraft_name = aircraft.name
        else:
            aircraft_name = aircraft

        fleet_field = MODEL_NAME_TO_FLEET_FIELD.get(aircraft_name, aircraft_name)
        fleet = self._resolve(airline).fleet
        if not hasattr(fleet, fleet_field):
            return 0
        return int(getattr(fleet, fleet_field))

@dataclass(frozen=True)
class DemandSegment:
    name: str
    distance_min: float
    distance_max: float
    demand: float # number of passengers
    block_time: float # block hours for a one-way flight in this segment

    @property
    def midpoint(self) -> float:
        return (self.distance_min + self.distance_max) / 2

    def is_within_range(self, aircraft_range: float) -> bool:
        return self.distance_max <= aircraft_range

class Demand:
    def __init__(self, segments: list[DemandSegment]):
        self._segments = segments

    @property
    def segments(self) -> list[DemandSegment]:
        return self._segments

    def scaled(self, fraction: float) -> "Demand":
        return Demand([
            DemandSegment(
                name=s.name,
                distance_min=s.distance_min,
                distance_max=s.distance_max,
                demand=s.demand * fraction,
                block_time=s.block_time
            )
            for s in self._segments
        ])
    
demand = Demand([
    DemandSegment("0-600", 0, 600, 50000, 2.5),
    DemandSegment("600-1200", 600, 1200, 35000, 3.0),
    DemandSegment("1200-1800", 1200, 1800, 20000, 3.5),
])
