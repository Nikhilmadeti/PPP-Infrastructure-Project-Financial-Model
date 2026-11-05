"""CFADS and the cash-flow waterfall (README §9.8, §9.10, §9.11).

    CFADS[k] = Revenue - O&M - MMR - concession fee - Tax   (+ MMRA release - contribution if the
                                                             MMRA sits inside CFADS)
Waterfall, in the README §9.11 order, every operating year:
    CFADS
    - senior interest - senior principal          -> cash after debt service
    - DSRA top-up (+ release; a DSRA draw covers a debt-service shortfall first)
    - MMRA contribution (+ release)               (when positioned after debt service, the default)
    = cash available for equity (CFAE)
    lock-up: if DSCR < lock-up level while debt is outstanding, positive CFAE is trapped in the SPV
    = distributions to equity

A shortfall is never hidden: if CFADS < debt service the gap is recorded (``ds_shortfall``), drawn
from the DSRA if one is funded, and whatever remains becomes **sponsor support** (a negative equity
cash flow), with a warning. Reserves only move cash in time; any balance left at the end of the
concession is released to equity.

README §9.8 puts the MMRA movement inside CFADS while §9.11 lists it after debt service. Both are
offered (``reserves.mmra_position``); the default follows the §9.11 waterfall.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .debt import DebtSchedule
from .funding import FundingSchedule
from .inputs import ReserveInputs
from .opex import OpexSchedule
from .timeline import Timeline


@dataclass(frozen=True)
class Waterfall:
    cfads: np.ndarray
    debt_service: np.ndarray
    cash_after_debt_service: np.ndarray
    ds_shortfall: np.ndarray  # max(0, DS - CFADS)
    dsra_target: np.ndarray
    dsra_opening: np.ndarray
    dsra_topup: np.ndarray
    dsra_release: np.ndarray
    dsra_draw: np.ndarray
    dsra_closing: np.ndarray
    mmra_contribution: np.ndarray  # below debt service (zero when the MMRA sits inside CFADS)
    mmra_release: np.ndarray
    mmra_balance: np.ndarray
    cash_available_for_equity: np.ndarray  # after debt service and reserves, before lock-up
    lockup_trapped: np.ndarray
    lockup_released: np.ndarray
    lockup_balance: np.ndarray
    distributions: np.ndarray
    sponsor_support: np.ndarray
    equity_contribution: np.ndarray  # construction-period equity
    equity_cash_flow: np.ndarray
    cumulative_equity_cash_flow: np.ndarray
    warnings: tuple[str, ...]

    @property
    def total_sponsor_support(self) -> float:
        return float(self.sponsor_support.sum())

    @property
    def total_ds_shortfall(self) -> float:
        return float(self.ds_shortfall.sum())


def compute_cfads(ebitda: np.ndarray, tax: np.ndarray, opex: OpexSchedule, reserves: ReserveInputs,
                  tl: Timeline) -> np.ndarray:
    cfads = (ebitda - tax) * tl.is_operation
    if reserves.mmra_enabled and reserves.mmra_position == "in_cfads":
        cfads = cfads - opex.mmra_contribution + opex.mmra_release
    return cfads


def _years(tl: Timeline, mask: np.ndarray) -> str:
    return ", ".join(str(int(k)) for k in tl.op_year[mask])


def build_waterfall(*, cfads: np.ndarray, debt: DebtSchedule, dscr: np.ndarray, opex: OpexSchedule,
                    funding: FundingSchedule, reserves: ReserveInputs, tl: Timeline,
                    terminal_value: float) -> Waterfall:
    n = tl.model_years
    ds = debt.debt_service
    z = lambda: np.zeros(n)  # noqa: E731 - small local factory
    after_ds, shortfall = z(), z()
    target, d_open, topup, release, draw, d_close = z(), z(), z(), z(), z(), z()
    m_contrib, m_release, m_balance = z(), z(), z()
    cfae, trapped_in, trapped_out, trapped_bal = z(), z(), z(), z()
    dist, support = z(), z()

    ds_next = np.concatenate([ds[1:], [0.0]])
    target[tl.cod_index:] = reserves.dsra_months / 12.0 * ds_next[tl.cod_index:]
    mmra_below_ds = reserves.mmra_enabled and reserves.mmra_position == "after_debt_service"

    dsra = funding.dsra_initial
    trapped = 0.0
    for i in range(tl.cod_index, n):
        cash = cfads[i] - ds[i]
        after_ds[i] = cash
        shortfall[i] = max(0.0, -cash)

        d_open[i] = dsra
        if cash < 0 and dsra > 0:  # DSRA covers a debt-service shortfall first
            draw[i] = min(dsra, -cash)
            cash += draw[i]
            dsra -= draw[i]
        if dsra < target[i] and cash > 0:
            topup[i] = min(target[i] - dsra, cash)
            cash -= topup[i]
            dsra += topup[i]
        if dsra > target[i]:
            release[i] = dsra - target[i]
            cash += release[i]
            dsra -= release[i]
        d_close[i] = dsra

        if mmra_below_ds:
            m_contrib[i] = opex.mmra_contribution[i]
            m_release[i] = opex.mmra_release[i]
            m_balance[i] = opex.mmra_balance[i]
            cash += m_release[i] - m_contrib[i]
        cfae[i] = cash

        locked = (reserves.lockup_dscr is not None and ds[i] > 0 and np.isfinite(dscr[i])
                  and dscr[i] < reserves.lockup_dscr)
        if locked and cash > 0:
            trapped_in[i] = cash
            trapped += cash
            cash = 0.0
        elif trapped > 0:
            use = trapped if not locked else min(trapped, max(-cash, 0.0))
            trapped_out[i] = use
            trapped -= use
            cash += use
        if i == n - 1 and trapped > 0:  # end of concession: trapped cash goes to equity
            trapped_out[i] += trapped
            cash += trapped
            trapped = 0.0
        trapped_bal[i] = trapped

        dist[i] = max(0.0, cash)  # 0.0 first, so a zero balance is +0.0, not -0.0
        support[i] = max(0.0, -cash)
    # The DSRA target in the final year is zero (no further debt service), so step 3 has already
    # released the whole DSRA balance to equity by the end of the concession.

    equity_cf = -funding.equity + dist - support
    equity_cf[-1] += terminal_value

    warnings = []
    if shortfall.any():
        mask = shortfall > 1e-9
        warnings.append(
            f"Debt-service shortfall (DSCR < 1.0) in op year(s) {_years(tl, mask)}: CFADS falls "
            f"{shortfall.sum():,.2f} ₹ Cr short of debt service in total. In reality this is a payment "
            f"default; the model covers {draw.sum():,.2f} ₹ Cr from the DSRA and the rest as sponsor support."
        )
    if support.sum() > 1e-9:
        mask = support > 1e-9
        warnings.append(
            f"Sponsor support of {support.sum():,.2f} ₹ Cr is needed in op year(s) {_years(tl, mask)} "
            "(shown as negative equity cash flow)."
        )
    if trapped_in.sum() > 1e-9:
        mask = trapped_in > 1e-9
        warnings.append(f"Dividend lock-up trapped cash in op year(s) {_years(tl, mask)}.")

    return Waterfall(
        cfads=cfads,
        debt_service=ds,
        cash_after_debt_service=after_ds,
        ds_shortfall=shortfall,
        dsra_target=target,
        dsra_opening=d_open,
        dsra_topup=topup,
        dsra_release=release,
        dsra_draw=draw,
        dsra_closing=d_close,
        mmra_contribution=m_contrib,
        mmra_release=m_release,
        mmra_balance=m_balance,
        cash_available_for_equity=cfae,
        lockup_trapped=trapped_in,
        lockup_released=trapped_out,
        lockup_balance=trapped_bal,
        distributions=dist,
        sponsor_support=support,
        equity_contribution=funding.equity.copy(),
        equity_cash_flow=equity_cf,
        cumulative_equity_cash_flow=np.cumsum(equity_cf),
        warnings=tuple(warnings),
    )
