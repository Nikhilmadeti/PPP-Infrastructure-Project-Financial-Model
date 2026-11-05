"""Operating costs and EBITDA (README §9.6), plus the major-maintenance reserve schedule (§9.10).

    OM[k]     = OM0  x (1 + e_om)^(k-1)
    MMR[k]    = MMR0 x (1 + e_om)^(k-1)        in the listed major-maintenance years, else 0
    ConFee[k] = fee% x Revenue[k] + premium x (1 + e_prem)^(k-1)
    Opex[k]   = OM[k] + MMR[k] + ConFee[k];   EBITDA[k] = Revenue[k] - Opex[k]

MMR is priced in op-year-1 money and escalated with O&M (the README uses e_om for both), so both
cost lines follow one price index. If a delay shortens operations, MMR years after the concession
end are dropped and reported.

MMRA: contributions are spread evenly over the years up to each MMR so that the balance equals the
MMR cost in its year, when the whole balance is released to pay it:
``contribution[k] = (MMR_next - balance) / years until MMR_next (inclusive)``. (README §9.10 writes
``next MMR / years remaining``, which does not quite accumulate to the MMR cost; this form does.)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .inputs import ModelInputs
from .revenue import RevenueSchedule
from .timeline import Timeline


@dataclass(frozen=True)
class OpexSchedule:
    om: np.ndarray
    mmr: np.ndarray
    concession_fee: np.ndarray
    total: np.ndarray
    ebitda: np.ndarray
    mmr_years_applied: tuple[int, ...]
    mmr_years_dropped: tuple[int, ...]
    mmra_contribution: np.ndarray
    mmra_release: np.ndarray
    mmra_balance: np.ndarray
    notes: tuple[str, ...]


def mmra_schedule(mmr: np.ndarray, mmr_years: tuple[int, ...], tl: Timeline) -> tuple[np.ndarray, ...]:
    contribution = np.zeros(tl.model_years)
    release = np.zeros(tl.model_years)
    balance = np.zeros(tl.model_years)
    years = sorted(mmr_years)
    running = 0.0
    for k in range(1, tl.operating_years + 1):
        i = tl.index_of_op_year(k)
        upcoming = [y for y in years if y >= k]
        if upcoming:
            k_next = upcoming[0]
            target = mmr[tl.index_of_op_year(k_next)]
            contribution[i] = (target - running) / (k_next - k + 1)
            running += contribution[i]
            if k == k_next:
                release[i] = running
                running = 0.0
        balance[i] = running
    return contribution, release, balance


def build_opex(inp: ModelInputs, tl: Timeline, revenue: RevenueSchedule) -> OpexSchedule:
    ox = inp.opex
    op, e = tl.is_operation, tl.index_exponent
    price = (1.0 + ox.om_escalation) ** e * op
    om = ox.om_base * price

    applied = tuple(sorted(y for y in ox.mmr_years if y <= tl.operating_years))
    dropped = tuple(sorted(y for y in ox.mmr_years if y > tl.operating_years))
    mmr_flag = np.isin(tl.op_year, applied).astype(float)
    mmr = ox.mmr_base * price * mmr_flag

    premium = ox.concession_premium * (1.0 + ox.premium_escalation) ** e * op
    concession_fee = ox.concession_fee_pct * revenue.total + premium
    total = om + mmr + concession_fee

    if inp.reserves.mmra_enabled and applied:
        contribution, release, balance = mmra_schedule(mmr, applied, tl)
    else:
        contribution = release = balance = np.zeros(tl.model_years)

    notes = []
    if dropped:
        notes.append(
            f"Major maintenance scheduled in op year(s) {', '.join(map(str, dropped))} falls after the "
            "shortened concession end and is excluded."
        )
    return OpexSchedule(
        om=om,
        mmr=mmr,
        concession_fee=concession_fee,
        total=total,
        ebitda=revenue.total - total,
        mmr_years_applied=applied,
        mmr_years_dropped=dropped,
        mmra_contribution=contribution,
        mmra_release=release,
        mmra_balance=balance,
        notes=tuple(notes),
    )
