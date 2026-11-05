"""Lender metrics (DSCR, LLCR, PLCR, ICR) and returns (IRR, NPV, payback) (README §9.12-9.13).

Conventions
-----------
* DSCR[k] = CFADS[k] / DS[k], only where DS[k] > 0 (moratorium years count: their DS is interest).
  Min and average DSCR are taken over those debt-service years only (README §16).
* LLCR[k] = [sum_{j=k..last repayment} CFADS[j] / (1+r)^(j-k+1) + DSRA balance] / Open[k], at the
  debt rate r. PLCR runs the same sum to the concession end. ICR[k] = CFADS[k] / Interest[k].
* NPV(i) = sum_t CF[t] / (1+i)^t for model years t = 1..N: values at financial close (start of
  year 1), the README §9.13 convention, which matches Excel's NPV(). numpy-financial's npv()
  discounts its first value by (1+i)^0, so it equals (1+i) x this NPV; IRRs agree either way.
* IRR: the NPV curve is scanned on a fine grid of rates from -99% to +1000% and every sign change is
  bisected. One root gives the IRR; several roots or none give *no* IRR (value None) and a message.
  The result is cross-checked against ``numpy_financial.irr``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy_financial as npf

from .timeline import Timeline

IRR_LOWER, IRR_UPPER = -0.99, 10.0
"""IRR search range (rate per year). An IRR outside it is reported as not found, not invented."""
IRR_GRID_POINTS = 6001
IRR_TOLERANCE = 1e-13
THRESHOLD_TOLERANCE = 1e-9
"""A ratio within this of a covenant or hurdle counts as meeting it (debt sized exactly to a target
lands on the threshold, and floating-point noise must not turn that into a breach)."""


def meets(value: float | None, threshold: float) -> bool:
    """True when ``value`` is at or above ``threshold`` (within :data:`THRESHOLD_TOLERANCE`)."""
    return value is not None and value >= threshold - THRESHOLD_TOLERANCE


@dataclass(frozen=True)
class IRRResult:
    value: float | None
    status: str  # ok | no_sign_change | multiple | no_root | invalid
    roots: tuple[float, ...]
    message: str
    npv_at_irr: float | None = None
    numpy_financial: float | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def __format__(self, spec: str) -> str:
        return format(self.value, spec) if self.ok else "n/a"

    def display(self, decimals: int = 2) -> str:
        return f"{self.value:.{decimals}%}" if self.ok else f"n/a ({self.status.replace('_', ' ')})"


@dataclass(frozen=True)
class PaybackResult:
    status: str  # achieved | not_achieved | no_investment
    model_year: int | None = None
    op_year: int | None = None
    label: str | None = None

    def display(self) -> str:
        if self.status == "achieved":
            return f"Year {self.model_year} ({self.label}, op year {self.op_year})"
        return "Not achieved within the concession" if self.status == "not_achieved" else "n/a (no equity invested)"


def npv(rate: float, cash_flows, first_period: int = 1) -> float:
    """NPV of end-of-year cash flows; the first value is discounted by (1+rate)^first_period."""
    if rate <= -1.0:
        raise ValueError("discount rate must be above -100%")
    cf = np.asarray(cash_flows, dtype=float)
    t = np.arange(first_period, first_period + cf.size, dtype=float)
    return float(np.sum(cf * (1.0 + rate) ** (-t)))


def _bisect(cf: np.ndarray, lo: float, hi: float) -> float:
    f_lo = npv(lo, cf)
    for _ in range(400):
        mid = 0.5 * (lo + hi)
        f_mid = npv(mid, cf)
        if f_mid == 0.0:
            return mid
        if (f_lo < 0) == (f_mid < 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
        if hi - lo < IRR_TOLERANCE:
            break
    return 0.5 * (lo + hi)


def numpy_financial_irr(cash_flows) -> float | None:
    try:
        value = float(npf.irr(np.asarray(cash_flows, dtype=float)))
    except Exception:  # noqa: BLE001 - any failure simply means no cross-check value
        return None
    return value if np.isfinite(value) else None


def irr(cash_flows) -> IRRResult:
    """Robust IRR: returns a value only when exactly one root exists in the search range."""
    cf = np.asarray(cash_flows, dtype=float)
    if cf.size < 2 or not np.all(np.isfinite(cf)):
        return IRRResult(None, "invalid", (), "IRR needs at least two finite cash flows.")
    significant = cf[np.abs(cf) > 1e-12]
    if significant.size == 0 or np.all(significant > 0) or np.all(significant < 0):
        return IRRResult(None, "no_sign_change", (),
                         "No IRR exists: the cash flows never change sign (all inflows or all outflows).")
    t = np.arange(1, cf.size + 1, dtype=float)
    x = np.linspace(np.log1p(IRR_LOWER), np.log1p(IRR_UPPER), IRR_GRID_POINTS)
    with np.errstate(over="ignore", invalid="ignore"):
        values = np.exp(-np.outer(x, t)) @ cf
    rates = np.expm1(x)
    finite = np.isfinite(values)
    signs = np.where(finite, np.sign(values), np.nan)
    exact = np.where(finite & (values == 0.0))[0]
    brackets = np.where(signs[:-1] * signs[1:] < 0)[0]  # NaN comparisons are False
    roots = [float(rates[j]) for j in exact]
    roots += [_bisect(cf, float(rates[j]), float(rates[j + 1])) for j in brackets]
    unique: list[float] = []
    for root in sorted(roots):
        if not unique or abs(root - unique[-1]) > 1e-9:
            unique.append(root)
    cross = numpy_financial_irr(cf)
    if len(unique) == 1:
        value = unique[0]
        return IRRResult(value, "ok", tuple(unique), "Unique IRR found.", npv(value, cf), cross)
    if len(unique) > 1:
        listed = ", ".join(f"{r:.2%}" for r in unique)
        return IRRResult(None, "multiple", tuple(unique),
                         f"Multiple IRRs ({listed}): the cash flows change sign more than once, so IRR is "
                         "not a reliable measure here; use NPV instead.", None, cross)
    return IRRResult(None, "no_root", (),
                     f"Cash flows change sign but NPV does not cross zero between {IRR_LOWER:.0%} and "
                     f"{IRR_UPPER:.0%}; no IRR is reported.", None, cross)


def dscr_series(cfads: np.ndarray, debt_service: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(debt_service > 1e-9, cfads / debt_service, np.nan)


def icr_series(cfads: np.ndarray, interest: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(interest > 1e-9, cfads / interest, np.nan)


def cover_ratio_series(cfads: np.ndarray, opening: np.ndarray, rate: float, end_index: int,
                       dsra_opening: np.ndarray, tl: Timeline) -> np.ndarray:
    """LLCR (end_index = last repayment year) or PLCR (end_index = last concession year) by year."""
    out = np.full(tl.model_years, np.nan)
    for i in range(tl.cod_index, end_index + 1):
        if opening[i] <= 1e-9:
            continue
        periods = np.arange(1, end_index - i + 2, dtype=float)
        pv = float(np.sum(cfads[i:end_index + 1] * (1.0 + rate) ** (-periods)))
        out[i] = (pv + dsra_opening[i]) / opening[i]
    return out


def payback(equity_cash_flow: np.ndarray, tl: Timeline) -> PaybackResult:
    cumulative = np.cumsum(equity_cash_flow)
    if not np.any(cumulative < -1e-9):
        return PaybackResult("no_investment")
    first_negative = int(np.argmax(cumulative < -1e-9))
    for i in range(first_negative, tl.model_years):
        if cumulative[i] >= -1e-9:
            return PaybackResult("achieved", int(tl.year[i]), int(tl.op_year[i]), tl.labels[i])
    return PaybackResult("not_achieved")


@dataclass(frozen=True)
class KeyMetrics:
    total_project_cost: float
    capex: float
    idc: float
    fees: float
    grant: float
    debt: float
    equity: float
    gearing_applied: float
    min_dscr: float | None
    min_dscr_op_year: int | None
    avg_dscr: float | None
    llcr_cod: float | None
    plcr_cod: float | None
    min_icr: float | None
    project_irr: IRRResult
    project_irr_post_grant: IRRResult
    equity_irr: IRRResult
    project_npv: float
    project_npv_post_grant: float
    equity_npv: float
    payback: PaybackResult
    debt_fully_repaid: bool
    final_repayment_op_year: int | None
    outstanding_at_end: float
    tail_years: int | None
    dscr_below_one_years: tuple[int, ...]
    dscr_below_covenant_years: tuple[int, ...]
    equity_meets_hurdle: bool | None
    sponsor_support: float
    ds_shortfall: float

    def as_dict(self) -> dict[str, object]:
        return {
            "Total Project Cost": self.total_project_cost,
            "Debt": self.debt,
            "Equity": self.equity,
            "IDC": self.idc,
            "Min DSCR": self.min_dscr,
            "Min DSCR op year": self.min_dscr_op_year,
            "Avg DSCR": self.avg_dscr,
            "LLCR at COD": self.llcr_cod,
            "Project IRR": self.project_irr.value,
            "Equity IRR": self.equity_irr.value,
            "NPV": self.project_npv,
        }


def compute_metrics(*, cfads, debt, dscr, llcr, plcr, icr, funding, project_cf, project_cf_post_grant,
                    equity_cf, discount_rate, equity_hurdle, covenant_dscr, waterfall, tl) -> KeyMetrics:
    ds_years = np.where(debt.debt_service > 1e-9)[0]
    if ds_years.size:
        window = dscr[ds_years]
        j = int(np.argmin(window))
        min_dscr = float(window[j])
        min_year = int(tl.op_year[ds_years[j]])
        avg_dscr = float(np.mean(window))
        below_one = tuple(int(tl.op_year[i]) for i in ds_years if not meets(dscr[i], 1.0))
        below_cov = tuple(int(tl.op_year[i]) for i in ds_years if not meets(dscr[i], covenant_dscr))
    else:
        min_dscr = min_year = avg_dscr = None
        below_one = below_cov = ()
    icr_valid = icr[np.isfinite(icr)]
    cod = tl.cod_index
    project = irr(project_cf)
    project_post = irr(project_cf_post_grant)
    equity = irr(equity_cf)
    tail = (tl.operating_years - debt.final_repayment_op_year) if debt.final_repayment_op_year else None
    return KeyMetrics(
        total_project_cost=funding.total_project_cost,
        capex=funding.capex_total,
        idc=funding.idc_total,
        fees=funding.fees_total,
        grant=funding.grant_total,
        debt=funding.debt_at_cod,
        equity=funding.equity_total,
        gearing_applied=funding.gearing,
        min_dscr=min_dscr,
        min_dscr_op_year=min_year,
        avg_dscr=avg_dscr,
        llcr_cod=float(llcr[cod]) if np.isfinite(llcr[cod]) else None,
        plcr_cod=float(plcr[cod]) if np.isfinite(plcr[cod]) else None,
        min_icr=float(icr_valid.min()) if icr_valid.size else None,
        project_irr=project,
        project_irr_post_grant=project_post,
        equity_irr=equity,
        project_npv=npv(discount_rate, project_cf),
        project_npv_post_grant=npv(discount_rate, project_cf_post_grant),
        equity_npv=npv(equity_hurdle, equity_cf),
        payback=payback(equity_cf, tl),
        debt_fully_repaid=debt.fully_repaid,
        final_repayment_op_year=debt.final_repayment_op_year,
        outstanding_at_end=debt.outstanding_at_end,
        tail_years=tail,
        dscr_below_one_years=below_one,
        dscr_below_covenant_years=below_cov,
        equity_meets_hurdle=meets(equity.value, equity_hurdle) if equity.ok else None,
        sponsor_support=waterfall.total_sponsor_support,
        ds_shortfall=waterfall.total_ds_shortfall,
    )
