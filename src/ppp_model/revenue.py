"""Revenue for the three project types, with ramp-up (README §9.5).

Timing: all revenue is received at the end of each annual period. Operating year ``k`` is model
year ``Tc + k``. Escalation uses the timeline's exponent (``k - 1`` under the README convention).

* Toll (§9.5.1):  Traffic[k] = AADT0 x (1+g_tr)^(k-1) x R[k] x (1-short), capped at road capacity,
  then x (1-leak) paying share; Revenue = Traffic x Rate x days / 1e7.
  The cap applies to vehicles *using* the road (exempt vehicles also take capacity), so leakage is
  applied after the cap. The README formula applies the cap to paying traffic; the two agree when
  leakage is zero (the base case). See docs/assumptions_and_limitations.md.
* Metro (§9.5.2): Riders[k] = min(R0 x (1+g)^(k-1) x R[k] x (1-short), capacity);
  Fare[k] = Fare0 x (1+rev%)^floor((k-1)/every); non-fare revenue = nfr% x fare revenue.
* HAM (§9.5.3):   paid by the Authority, so revenue never uses traffic. Construction support
  (40% of BPC x PIM) is paid during construction and treated as a grant in the funding. The
  remaining 60% of BPC x PIM at COD is repaid in equal semi-annual principal instalments with
  interest on the reducing balance; semi-annual payments are summed into the annual period in which
  they fall. O&M payments are indexed. Payments depend on the *Bid* Project Cost, so a cost overrun
  does not change them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .capex import effective_phasing, stretch_phasing
from .inputs import RUPEES_PER_CRORE, HamInputs, MetroInputs, ModelInputs, TollInputs
from .timeline import Timeline


@dataclass(frozen=True)
class RevenueSchedule:
    project_type: str
    total: np.ndarray  # ₹ Cr by model year
    lines: dict[str, np.ndarray]  # revenue components, ₹ Cr (sum to total)
    drivers: dict[str, np.ndarray]  # traffic, prices, indices (not money)
    construction_support: np.ndarray  # HAM construction support, ₹ Cr (zero for toll/metro)
    demand_sensitive: bool  # False for HAM: revenue does not depend on traffic
    semiannual: pd.DataFrame | None = None  # HAM annuity schedule
    details: dict[str, float] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


def ramp_factors(ramp_up: tuple[float, ...], tl: Timeline) -> np.ndarray:
    """R[k] for each model year: the listed factors for op years 1..len, then 100%; 0 in construction."""
    ramp = np.zeros(tl.model_years)
    for i, k in enumerate(tl.op_year):
        if k >= 1:
            ramp[i] = ramp_up[k - 1] if k <= len(ramp_up) else 1.0
    return ramp


def toll_revenue(toll: TollInputs, shortfall: float, tl: Timeline) -> RevenueSchedule:
    op, e = tl.is_operation, tl.index_exponent
    ramp = ramp_factors(toll.ramp_up, tl)
    mature = toll.aadt * (1.0 + toll.growth) ** e * op
    on_road = mature * ramp * (1.0 - shortfall)
    if toll.capacity is not None:
        using_road = np.minimum(on_road, toll.capacity)
        cap_binding = (on_road > toll.capacity).astype(float)
    else:
        using_road = on_road
        cap_binding = np.zeros(tl.model_years)
    paying = using_road * (1.0 - toll.leakage)
    rate = toll.rate * (1.0 + toll.rate_escalation) ** e * op
    revenue = paying * rate * toll.days_per_year / RUPEES_PER_CRORE
    notes = []
    if cap_binding.any():
        first = int(tl.op_year[np.argmax(cap_binding > 0)])
        notes.append(f"Road capacity cap of {toll.capacity:,.0f} PCU/day binds from op year {first}.")
    return RevenueSchedule(
        project_type="toll",
        total=revenue,
        lines={"Toll revenue": revenue},
        drivers={
            "Mature traffic (PCU/day)": mature,
            "Ramp-up factor": ramp,
            "Traffic after shortfall (PCU/day)": on_road,
            "Capacity cap binding (1=yes)": cap_binding,
            "Paying traffic (PCU/day)": paying,
            "Toll rate (₹/trip)": rate,
        },
        construction_support=np.zeros(tl.model_years),
        demand_sensitive=True,
        notes=tuple(notes),
    )


def metro_revenue(metro: MetroInputs, shortfall: float, tl: Timeline) -> RevenueSchedule:
    op, e = tl.is_operation, tl.index_exponent
    ramp = ramp_factors(metro.ramp_up, tl)
    mature = metro.ridership * (1.0 + metro.growth) ** e * op
    demand = mature * ramp * (1.0 - shortfall)
    if metro.capacity is not None:
        riders = np.minimum(demand, metro.capacity)
        cap_binding = (demand > metro.capacity).astype(float)
    else:
        riders = demand
        cap_binding = np.zeros(tl.model_years)
    revisions = np.floor(e / metro.fare_revision_every)
    fare = metro.fare * (1.0 + metro.fare_revision_pct) ** revisions * op
    fare_revenue = riders * fare * metro.days_per_year / RUPEES_PER_CRORE
    non_fare = metro.non_fare_pct * fare_revenue
    notes = []
    if cap_binding.any():
        first = int(tl.op_year[np.argmax(cap_binding > 0)])
        notes.append(f"Line capacity of {metro.capacity:,.0f} passengers/day binds from op year {first}.")
    return RevenueSchedule(
        project_type="metro",
        total=fare_revenue + non_fare,
        lines={"Fare revenue": fare_revenue, "Non-fare revenue": non_fare},
        drivers={
            "Mature ridership (pax/day)": mature,
            "Ramp-up factor": ramp,
            "Ridership demand (pax/day)": demand,
            "Capacity cap binding (1=yes)": cap_binding,
            "Ridership carried (pax/day)": riders,
            "Average fare (₹/trip)": fare,
        },
        construction_support=np.zeros(tl.model_years),
        demand_sensitive=True,
        notes=tuple(notes),
    )


def ham_support_milestones(ham: HamInputs, inp: ModelInputs, tl: Timeline) -> np.ndarray:
    """Share of the construction support paid in each construction year."""
    if ham.support_milestones is None:
        return effective_phasing(inp, tl)[0]  # follows physical progress = capex phasing
    return stretch_phasing(ham.support_milestones, tl.construction_years)


def ham_revenue(ham: HamInputs, inp: ModelInputs, tl: Timeline) -> RevenueSchedule:
    """HAM payments. Deliberately takes no traffic or actual-cost input (README §9.5.3)."""
    n_years = tl.model_years
    pim = (1.0 + ham.pim_inflation) ** (tl.year - 1)  # Price Index Multiple; bid date = start of year 1

    milestones = np.zeros(n_years)
    milestones[: tl.construction_years] = ham_support_milestones(ham, inp, tl)
    support = ham.construction_support_pct * ham.bid_project_cost * pim * milestones

    pim_cod = (1.0 + ham.pim_inflation) ** tl.construction_years  # price level at COD
    completion_cost = (1.0 - ham.construction_support_pct) * ham.bid_project_cost * pim_cod

    per_year = ham.instalments_per_year
    n_inst = ham.annuity_instalments
    h = np.arange(1, n_inst + 1)
    principal_h = np.full(n_inst, completion_cost / n_inst)
    opening_h = completion_cost - (h - 1) * principal_h[0]
    interest_h = ham.annuity_interest_rate / per_year * opening_h
    op_year_h = np.ceil(h / per_year).astype(int)
    semiannual = pd.DataFrame(
        {
            "Instalment": h,
            "Op year": op_year_h,
            "Period in year": (h - 1) % per_year + 1,
            "Opening balance": opening_h,
            "Annuity principal": principal_h,
            "Annuity interest": interest_h,
            "Total annuity": principal_h + interest_h,
            "Closing balance": opening_h - principal_h,
            "Within concession": op_year_h <= tl.operating_years,
        }
    )

    ann_principal = np.zeros(n_years)
    ann_interest = np.zeros(n_years)
    ann_opening = np.zeros(n_years)
    for k in range(1, tl.operating_years + 1):
        rows = semiannual[semiannual["Op year"] == k]
        if rows.empty:
            continue
        i = tl.index_of_op_year(k)
        ann_principal[i] = rows["Annuity principal"].sum()
        ann_interest[i] = rows["Annuity interest"].sum()
        ann_opening[i] = rows["Opening balance"].iloc[0]

    om_payment = ham.om_payment * (1.0 + ham.pim_inflation) ** tl.index_exponent * tl.is_operation
    notes = [
        f"Completion cost (annuity principal) = {1 - ham.construction_support_pct:.0%} x BPC "
        f"{ham.bid_project_cost:,.2f} x PIM at COD {pim_cod:.6f} = {completion_cost:,.4f} ₹ Cr, repaid in "
        f"{n_inst} instalments ({per_year} per year) with {ham.annuity_interest_rate:.2%} interest on the "
        "reducing balance; instalments within each year are summed into that annual period."
    ]
    lost = semiannual[~semiannual["Within concession"]]
    if not lost.empty:
        notes.append(
            f"{len(lost)} annuity instalment(s) worth {lost['Total annuity'].sum():,.2f} ₹ Cr fall after the "
            "concession end and are not received."
        )
    if math.ceil(n_inst / per_year) < tl.operating_years:
        notes.append("The annuity period ends before the concession: later years earn only the O&M payment.")

    return RevenueSchedule(
        project_type="ham",
        total=ann_principal + ann_interest + om_payment,
        lines={"Annuity principal": ann_principal, "Annuity interest": ann_interest, "O&M payment": om_payment},
        drivers={
            "Price Index Multiple": pim,
            "Support milestone share": milestones,
            "Annuity balance (opening)": ann_opening,
        },
        construction_support=support,
        demand_sensitive=False,
        semiannual=semiannual,
        details={"completion_cost": completion_cost, "pim_at_cod": pim_cod},
        notes=tuple(notes),
    )


def build_revenue(inp: ModelInputs, tl: Timeline) -> RevenueSchedule:
    block = inp.revenue_block
    if inp.project_type == "toll":
        return toll_revenue(block, inp.stress.demand_shortfall, tl)
    if inp.project_type == "metro":
        return metro_revenue(block, inp.stress.demand_shortfall, tl)
    return ham_revenue(block, inp, tl)  # no shortfall argument: HAM carries no traffic risk
