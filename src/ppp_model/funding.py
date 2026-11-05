"""Sources and uses, gearing, grant and Interest During Construction (README §9.3-9.4).

Uses:     USES[t] = Capex[t] + Fees[t] + IDC[t] + DSRA initial funding (end of year Tc, optional)
Sources:  Grant[t] + Debt draw[t] + Equity[t]      (checked equal to USES every year)

IDC uses the mid-year drawdown convention: money drawn during year t earns interest for ``m`` of
the year, so  IDC[t] = r x (Open[t] + m x Draw[t]).  IDC is capitalised (added to the loan and to
project cost), which makes it circular. Pro-rata mode solves each year in closed form:

            r x Open[t] + m x r x g x K[t]
    IDC[t] = ------------------------------        K[t] = Capex[t] + Fees[t] - Grant[t]
                    1 - m x r x g

Equity-first mode: equity funds every use until its commitment (1-g) x total need is spent, then
debt takes over; the transition year is solved in closed form and the commitment (which depends on
total IDC) by fixed-point iteration. A separate, deliberately simple vector iteration
(:func:`idc_by_iteration`, the README §7.3 pattern) recomputes IDC independently; the checks
require the two to agree.

Cost-overrun funding: ``pro_rata`` funds the overrun at gearing g (debt rises); ``equity`` funds 100%
of it from the sponsor, so debt and IDC are unchanged.

Upfront fee: a share of debt at COD, paid in model year 1 and funded like capex. Debt depends on
the fee and the fee on debt, so it is solved by fixed-point iteration (README §7.3).

DSRA initial funding (optional): paid in at COD (end of year Tc), funded at gearing g but earning
no IDC in year Tc because it is drawn at the year end.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .errors import ConvergenceError, FundingError
from .timeline import Timeline


@dataclass(frozen=True)
class FundingSchedule:
    capex: np.ndarray
    grant: np.ndarray
    fees: np.ndarray
    idc: np.ndarray
    dsra_funding: np.ndarray
    uses: np.ndarray
    equity_only: np.ndarray  # overrun funded 100% by equity (equity overrun mode)
    need: np.ndarray  # uses - grant: funded by debt + equity
    debt_draw: np.ndarray
    equity: np.ndarray
    sources: np.ndarray
    opening_debt: np.ndarray
    closing_debt: np.ndarray
    idc_iterative: np.ndarray  # independent recomputation, for the cross-check
    gearing: float
    rate: float
    drawdown_timing: float
    equity_mode: str
    construction_years: int
    iterations: dict[str, int] = field(default_factory=dict)

    @property
    def debt_at_cod(self) -> float:
        return float(self.closing_debt[self.construction_years - 1])

    @property
    def equity_total(self) -> float:
        return float(self.equity.sum())

    @property
    def grant_total(self) -> float:
        return float(self.grant.sum())

    @property
    def idc_total(self) -> float:
        return float(self.idc.sum())

    @property
    def fees_total(self) -> float:
        return float(self.fees.sum())

    @property
    def capex_total(self) -> float:
        return float(self.capex.sum())

    @property
    def dsra_initial(self) -> float:
        return float(self.dsra_funding.sum())

    @property
    def total_project_cost(self) -> float:
        """TPC = capex + fees + IDC (+ DSRA initial funding) = total uses."""
        return float(self.uses.sum())

    @property
    def equity_only_total(self) -> float:
        return float(self.equity_only.sum())

    @property
    def expected_debt(self) -> float:
        """Debt implied by the funding rule: g x (TPC - grant - equity-funded overrun)."""
        return self.gearing * (self.total_project_cost - self.grant_total - self.equity_only_total)


# ---------------------------------------------------------------------------------------------
# Closed-form solves
# ---------------------------------------------------------------------------------------------


def _pro_rata(base_need, equity_only, dsra, g, r, m):
    tc = base_need.size
    idc, draw, equity, opening, closing = (np.zeros(tc) for _ in range(5))
    balance = 0.0
    for t in range(tc):
        k_t = base_need[t]
        idc[t] = (r * balance + m * r * g * k_t) / (1.0 - m * r * g)
        draw[t] = g * (k_t + idc[t]) + g * dsra[t]
        equity[t] = (1.0 - g) * (k_t + idc[t] + dsra[t]) + equity_only[t]
        opening[t] = balance
        balance += draw[t]
        closing[t] = balance
    return idc, draw, equity, opening, closing, 1


def _equity_first(base_need, equity_only, dsra, g, r, m, tol, max_iter):
    tc = base_need.size
    need_ex_idc = base_need.sum() + dsra.sum()
    idc_total = 0.0
    for iteration in range(1, max_iter + 1):
        commitment = (1.0 - g) * (need_ex_idc + idc_total) + equity_only.sum()
        remaining = commitment
        idc, draw, equity, opening, closing = (np.zeros(tc) for _ in range(5))
        balance = 0.0
        for t in range(tc):
            items = base_need[t] + equity_only[t]
            if remaining >= items + r * balance:  # equity still covers this year's uses (and any IDC)
                idc[t] = r * balance
                eq_mid, draw_mid = items + idc[t], 0.0
            else:  # equity runs out this year: debt funds the rest, IDC solved in closed form
                draw_mid = (items - remaining + r * balance) / (1.0 - m * r)
                idc[t] = r * (balance + m * draw_mid)
                eq_mid = remaining
            remaining -= eq_mid
            eq_eoy = min(remaining, dsra[t])
            remaining -= eq_eoy
            draw[t] = draw_mid + (dsra[t] - eq_eoy)
            equity[t] = eq_mid + eq_eoy
            opening[t] = balance
            balance += draw[t]
            closing[t] = balance
        if abs(idc.sum() - idc_total) < tol:
            return idc, draw, equity, opening, closing, iteration
        idc_total = idc.sum()
    raise ConvergenceError(
        f"Equity-first IDC did not converge in {max_iter} iterations (last change "
        f"{abs(idc.sum() - idc_total):.3e}); check the gearing and interest rate."
    )


def idc_by_iteration(base_need, equity_only, dsra, g, r, m, equity_mode, tol, max_iter):
    """Independent fixed-point IDC solve (README §7.3): guess IDC, fund the uses, recompute IDC, repeat."""
    tc = base_need.size
    idc = np.zeros(tc)
    for iteration in range(1, max_iter + 1):
        if equity_mode == "pro_rata":
            draw_mid = g * (base_need + idc)
            draw_eoy = g * dsra
        else:
            commitment = (1.0 - g) * (base_need.sum() + dsra.sum() + idc.sum()) + equity_only.sum()
            remaining = commitment
            draw_mid = np.zeros(tc)
            draw_eoy = np.zeros(tc)
            for t in range(tc):
                uses_mid = base_need[t] + equity_only[t] + idc[t]
                eq_mid = min(remaining, uses_mid)
                draw_mid[t] = uses_mid - eq_mid
                remaining -= eq_mid
                eq_eoy = min(remaining, dsra[t])
                remaining -= eq_eoy
                draw_eoy[t] = dsra[t] - eq_eoy
        opening = np.concatenate([[0.0], np.cumsum(draw_mid + draw_eoy)[:-1]])
        new_idc = r * (opening + m * draw_mid)
        if np.max(np.abs(new_idc - idc)) < tol:
            return new_idc, iteration
        idc = new_idc
    raise ConvergenceError(f"Iterative IDC did not converge in {max_iter} iterations")


# ---------------------------------------------------------------------------------------------
# Public solve
# ---------------------------------------------------------------------------------------------


def solve_funding(
    *,
    capex: np.ndarray,
    equity_only: np.ndarray,
    grant: np.ndarray,
    tl: Timeline,
    gearing: float,
    rate: float,
    drawdown_timing: float,
    upfront_fee: float,
    equity_mode: str,
    dsra_initial: float,
    tol: float,
    max_iter: int,
) -> FundingSchedule:
    """Solve construction funding: grant, debt, equity, IDC and fees, with sources = uses."""
    tc, n = tl.construction_years, tl.model_years
    g, r, m = gearing, rate, drawdown_timing
    cap_c, eqo_c, grant_c = capex[:tc], equity_only[:tc], grant[:tc]
    dsra_c = np.zeros(tc)
    dsra_c[-1] = dsra_initial

    shortfall = cap_c - eqo_c - grant_c
    if np.any(shortfall < -1e-9):
        t_bad = int(np.argmin(shortfall)) + 1
        raise FundingError(
            f"Grant / construction support in model year {t_bad} ({grant_c[t_bad - 1]:,.2f} ₹ Cr) exceeds the "
            f"debt- and equity-fundable capex that year ({cap_c[t_bad - 1] - eqo_c[t_bad - 1]:,.2f} ₹ Cr). "
            "Align the grant or milestone phasing with the capex phasing."
        )

    fees_c = np.zeros(tc)
    for fee_iteration in range(1, max_iter + 1):
        base_need = cap_c - eqo_c - grant_c + fees_c
        if equity_mode == "pro_rata":
            idc, draw, equity, opening, closing, inner = _pro_rata(base_need, eqo_c, dsra_c, g, r, m)
        else:
            idc, draw, equity, opening, closing, inner = _equity_first(
                base_need, eqo_c, dsra_c, g, r, m, tol, max_iter
            )
        new_fees = np.zeros(tc)
        new_fees[0] = upfront_fee * closing[-1]
        if np.max(np.abs(new_fees - fees_c)) < tol:
            break  # keep the fees this pass was solved with, so sources = uses exactly
        fees_c = new_fees
    else:
        raise ConvergenceError(f"Upfront fee <-> debt did not converge in {max_iter} iterations")

    base_need = cap_c - eqo_c - grant_c + fees_c
    idc_iter, iter_count = idc_by_iteration(base_need, eqo_c, dsra_c, g, r, m, equity_mode, tol, max_iter)

    def full(x: np.ndarray) -> np.ndarray:
        out = np.zeros(n)
        out[:tc] = x
        return out

    uses_c = cap_c + fees_c + idc + dsra_c
    return FundingSchedule(
        capex=full(cap_c),
        grant=full(grant_c),
        fees=full(fees_c),
        idc=full(idc),
        dsra_funding=full(dsra_c),
        uses=full(uses_c),
        equity_only=full(eqo_c),
        need=full(uses_c - grant_c),
        debt_draw=full(draw),
        equity=full(equity),
        sources=full(grant_c + draw + equity),
        opening_debt=full(opening),
        closing_debt=full(closing),
        idc_iterative=full(idc_iter),
        gearing=g,
        rate=r,
        drawdown_timing=m,
        equity_mode=equity_mode,
        construction_years=tc,
        iterations={"fees": fee_iteration, "idc_closed_form": inner, "idc_iterative": iter_count},
    )
