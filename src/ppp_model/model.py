"""Orchestrator: ``run_model(inputs) -> ModelResults`` (README §7).

Calculation order (README §7.2): timeline -> capex -> revenue -> opex -> funding + IDC ->
debt schedule <-> tax <-> CFADS -> waterfall -> metrics -> checks.

Circularities and how they are solved (README §7.3), each bounded and tolerance-controlled:
* IDC <-> debt and upfront fee <-> debt: in :mod:`ppp_model.funding`.
* Sculpting <-> tax: fixed-point iteration on CFADS in :func:`_operations`.
* DSRA funded at COD <-> debt service: outer fixed point in :func:`_solve_case`.
* DSCR-based debt sizing: bisection on the applied gearing in :func:`_size_debt`; every trial
  re-runs funding, IDC, tax and CFADS, so the sized debt is consistent with its own schedule.
Any loop that fails to converge raises :class:`ConvergenceError` with the residual.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

import numpy as np
import pandas as pd

from .capex import CapexSchedule, build_capex
from .cashflow import Waterfall, build_waterfall, compute_cfads
from .debt import DebtSchedule, build_debt_schedule, schedule_from_principal, sculpted_debt_capacity
from .errors import ConvergenceError
from .funding import FundingSchedule, solve_funding
from .inputs import ModelInputs, build_inputs
from .metrics import KeyMetrics, compute_metrics, cover_ratio_series, dscr_series, icr_series
from .opex import OpexSchedule, build_opex
from .revenue import RevenueSchedule, build_revenue
from .tax import TaxResult, TaxSchedule, compute_tax, straight_line_depreciation
from .timeline import Timeline, build_timeline

SIZING_DSCR_TOLERANCE = 1e-9
"""Numerical slack when testing 'min DSCR >= target' during DSCR-based sizing."""


@dataclass(frozen=True)
class SizingInfo:
    method: str  # gearing | gearing_and_dscr
    binding: str  # gearing | dscr
    gearing_input: float
    gearing_applied: float
    debt_at_gearing_limit: float
    debt_dscr_limit: float | None  # solved (DSCR binds) or indicative (gearing binds)
    target_dscr: float
    iterations: int
    message: str


@dataclass(frozen=True)
class _Operations:
    debt: DebtSchedule
    tax: TaxResult
    cfads: np.ndarray
    depreciation: np.ndarray
    depreciable_cost: float
    iterations: int


@dataclass(frozen=True)
class _Case:
    funding: FundingSchedule
    ops: _Operations
    dsra_iterations: int


@dataclass
class ModelResults:
    inputs: ModelInputs
    timeline: Timeline
    capex: CapexSchedule
    revenue: RevenueSchedule
    opex: OpexSchedule
    funding: FundingSchedule
    tax: TaxSchedule
    debt: DebtSchedule
    cfads: np.ndarray
    dscr: np.ndarray
    llcr: np.ndarray
    plcr: np.ndarray
    icr: np.ndarray
    waterfall: Waterfall
    project_cf: np.ndarray
    project_cf_post_grant: np.ndarray
    equity_cf: np.ndarray
    metrics: KeyMetrics
    sizing: SizingInfo
    iterations: dict[str, int]
    checks: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def integrity_ok(self) -> bool:
        return all(c.status != "fail" for c in self.checks)

    @cached_property
    def annual(self) -> pd.DataFrame:
        return annual_table(self)

    def schedule_columns(self) -> dict[str, list[str]]:
        return schedule_columns(self)


# ---------------------------------------------------------------------------------------------
# Core solves
# ---------------------------------------------------------------------------------------------


def _grant(inp: ModelInputs, capex: CapexSchedule, revenue: RevenueSchedule) -> np.ndarray:
    basis = capex.capex if inp.funding.grant_covers_overrun else capex.capex_before_overrun
    return inp.funding.grant_pct * basis + revenue.construction_support


def _operations(inp: ModelInputs, tl: Timeline, opex: OpexSchedule, funding: FundingSchedule,
                rate: float) -> _Operations:
    tx, dt, so = inp.tax, inp.debt, inp.solver
    grant_part = funding.grant_total if tx.depreciation_net_of_grant else 0.0
    dep_cost = funding.capex_total + funding.fees_total + funding.idc_total - grant_part
    dep = straight_line_depreciation(dep_cost, tl, tx.depreciation_years)
    ebitda = opex.ebitda
    amount = funding.debt_at_cod

    def tax_and_cfads(debt: DebtSchedule) -> tuple[TaxResult, np.ndarray]:
        tax = compute_tax(ebitda, dep, debt.interest, tx.rate, tx.loss_carry_forward_years, tl)
        return tax, compute_cfads(ebitda, tax.tax, opex, inp.reserves, tl)

    if dt.profile != "sculpted":
        debt = schedule_from_principal(dt.profile, amount, rate, tl, dt.structured_pct)
        tax, cfads = tax_and_cfads(debt)
        return _Operations(debt, tax, cfads, dep, dep_cost, 1)

    # Sculpting <-> tax: DS depends on CFADS, CFADS on tax, tax on interest, interest on DS.
    no_interest = compute_tax(ebitda, dep, np.zeros(tl.model_years), tx.rate, tx.loss_carry_forward_years, tl)
    cfads = compute_cfads(ebitda, no_interest.tax, opex, inp.reserves, tl)
    for iteration in range(1, so.max_iterations + 1):
        debt = build_debt_schedule("sculpted", amount, rate, tl, cfads=cfads,
                                   negative_rule=dt.sculpt_negative_principal,
                                   tol=so.tolerance, max_iter=so.max_iterations)
        tax, new_cfads = tax_and_cfads(debt)
        change = float(np.max(np.abs(new_cfads - cfads)))
        cfads = new_cfads
        if change < so.tolerance:
            return _Operations(debt, tax, cfads, dep, dep_cost, iteration)
    raise ConvergenceError(
        f"Sculpting <-> tax iteration did not converge in {so.max_iterations} iterations "
        f"(last CFADS change {change:.3e} ₹ Cr)."
    )


def _solve_case(inp: ModelInputs, tl: Timeline, capex: CapexSchedule, opex: OpexSchedule,
                grant: np.ndarray, gearing: float) -> _Case:
    rs, so = inp.reserves, inp.solver
    equity_only = capex.overrun if inp.stress.overrun_funding == "equity" else np.zeros(tl.model_years)
    dsra_loop = rs.dsra_months > 0 and rs.dsra_initial_funding == "construction"
    dsra_initial = 0.0
    for iteration in range(1, so.max_iterations + 1):
        funding = solve_funding(
            capex=capex.capex, equity_only=equity_only, grant=grant, tl=tl, gearing=gearing,
            rate=inp.interest_rate, drawdown_timing=inp.funding.drawdown_timing,
            upfront_fee=inp.funding.upfront_fee, equity_mode=inp.funding.equity_mode,
            dsra_initial=dsra_initial, tol=so.tolerance, max_iter=so.max_iterations,
        )
        ops = _operations(inp, tl, opex, funding, inp.interest_rate)
        if not dsra_loop:
            return _Case(funding, ops, iteration)
        new_initial = rs.dsra_months / 12.0 * ops.debt.debt_service[tl.cod_index]
        if abs(new_initial - dsra_initial) < so.tolerance:
            return _Case(funding, ops, iteration)
        dsra_initial = new_initial
    raise ConvergenceError(f"DSRA initial funding <-> debt did not converge in {so.max_iterations} iterations.")


def _min_dscr(case: _Case) -> float:
    ds = case.ops.debt.debt_service
    mask = ds > 1e-9
    if not mask.any():
        return np.inf
    return float(np.min(case.ops.cfads[mask] / ds[mask]))


def _indicative_dscr_capacity(inp: ModelInputs, tl: Timeline, case: _Case) -> float | None:
    """D_dscr at the case's CFADS (ignores the small tax feedback), for reporting when gearing binds."""
    target, rate, cfads = inp.debt.target_dscr, inp.interest_rate, case.ops.cfads
    if inp.debt.profile == "sculpted":
        return sculpted_debt_capacity(cfads, rate, target, tl)
    unit = schedule_from_principal(inp.debt.profile, 1.0, rate, tl, inp.debt.structured_pct).debt_service
    mask = unit > 1e-12
    if not mask.any():
        return None
    return float(np.min(cfads[mask] / (target * unit[mask])))


def _size_debt(inp: ModelInputs, tl: Timeline, capex, opex, grant) -> tuple[_Case, SizingInfo]:
    g_max, target = inp.funding.gearing, inp.debt.target_dscr
    full = _solve_case(inp, tl, capex, opex, grant, g_max)
    d_gearing = full.funding.debt_at_cod
    if inp.debt.sizing == "gearing":
        return full, SizingInfo("gearing", "gearing", g_max, g_max, d_gearing, None, target, 0,
                                f"Debt sized by gearing only: {g_max:.1%} of (TPC - grant).")
    if _min_dscr(full) >= target - SIZING_DSCR_TOLERANCE:
        d_dscr = _indicative_dscr_capacity(inp, tl, full)
        return full, SizingInfo(
            "gearing_and_dscr", "gearing", g_max, g_max, d_gearing, d_dscr, target, 0,
            f"Gearing binds: at {g_max:.1%} gearing the minimum DSCR ({_min_dscr(full):.3f}x) already meets the "
            f"{target:.2f}x target, so debt = {d_gearing:,.2f} ₹ Cr (indicative DSCR capacity "
            f"{d_dscr:,.2f} ₹ Cr)." if d_dscr is not None else "Gearing binds.",
        )
    lo, hi, best = 0.0, g_max, None
    iterations = 0
    for iterations in range(1, inp.solver.max_iterations + 1):
        mid = 0.5 * (lo + hi)
        case = _solve_case(inp, tl, capex, opex, grant, mid)
        if _min_dscr(case) >= target - SIZING_DSCR_TOLERANCE:
            lo, best = mid, case
        else:
            hi = mid
        if hi - lo < 1e-10:
            break
    else:
        raise ConvergenceError("DSCR-based debt sizing did not converge.")
    if best is None:
        best = _solve_case(inp, tl, capex, opex, grant, 0.0)
        message = (f"No positive debt meets the {target:.2f}x DSCR target (CFADS is too low in at least one "
                   "debt-service year); the case is shown with no debt.")
    else:
        message = (f"DSCR binds: debt cut from {d_gearing:,.2f} to {best.funding.debt_at_cod:,.2f} ₹ Cr "
                   f"(gearing {g_max:.1%} -> {lo:.2%}) so the minimum DSCR is {_min_dscr(best):.4f}x "
                   f">= {target:.2f}x target.")
    return best, SizingInfo("gearing_and_dscr", "dscr", g_max, best.funding.gearing, d_gearing,
                            best.funding.debt_at_cod, target, iterations, message)


# ---------------------------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------------------------


def run_model(inputs: ModelInputs | dict) -> ModelResults:
    """Run the full model for one set of inputs (a validated ModelInputs or a raw dict)."""
    from .checks import run_checks  # local import: checks re-runs parts of the model

    inp = inputs if isinstance(inputs, ModelInputs) else build_inputs(inputs)
    tl = build_timeline(inp)
    capex = build_capex(inp, tl)
    revenue = build_revenue(inp, tl)
    opex = build_opex(inp, tl, revenue)
    grant = _grant(inp, capex, revenue)

    case, sizing = _size_debt(inp, tl, capex, opex, grant)
    funding, ops = case.funding, case.ops
    debt, cfads = ops.debt, ops.cfads
    rate = inp.interest_rate

    # Unlevered tax for Project IRR: no interest, depreciation on capex excluding IDC and fees.
    tx = inp.tax
    cost_pre = funding.capex_total
    cost_post = funding.capex_total - (funding.grant_total if tx.depreciation_net_of_grant else 0.0)
    zero = np.zeros(tl.model_years)
    unlev_pre = compute_tax(opex.ebitda, straight_line_depreciation(cost_pre, tl, tx.depreciation_years),
                            zero, tx.rate, tx.loss_carry_forward_years, tl)
    unlev_post = compute_tax(opex.ebitda, straight_line_depreciation(cost_post, tl, tx.depreciation_years),
                             zero, tx.rate, tx.loss_carry_forward_years, tl)
    tax = TaxSchedule(ops.tax, unlev_pre, unlev_post, ops.depreciable_cost, cost_post)

    dscr = dscr_series(cfads, debt.debt_service)
    waterfall = build_waterfall(cfads=cfads, debt=debt, dscr=dscr, opex=opex, funding=funding,
                                reserves=inp.reserves, tl=tl, terminal_value=inp.valuation.terminal_value)
    last_repay = tl.index_of_op_year(tl.last_repayment_op_year)
    llcr = cover_ratio_series(cfads, debt.opening, rate, last_repay, waterfall.dsra_opening, tl)
    plcr = cover_ratio_series(cfads, debt.opening, rate, tl.model_years - 1, waterfall.dsra_opening, tl)
    icr = icr_series(cfads, debt.interest)

    tv = np.zeros(tl.model_years)
    tv[-1] = inp.valuation.terminal_value
    op = tl.is_operation
    project_cf = -capex.capex + (opex.ebitda - unlev_pre.tax) * op + tv
    project_cf_post = -(capex.capex - funding.grant) + (opex.ebitda - unlev_post.tax) * op + tv
    equity_cf = waterfall.equity_cash_flow

    metrics = compute_metrics(
        cfads=cfads, debt=debt, dscr=dscr, llcr=llcr, plcr=plcr, icr=icr, funding=funding,
        project_cf=project_cf, project_cf_post_grant=project_cf_post, equity_cf=equity_cf,
        discount_rate=inp.valuation.discount_rate, equity_hurdle=inp.valuation.equity_hurdle,
        covenant_dscr=inp.covenants.min_dscr, waterfall=waterfall, tl=tl,
    )
    iterations = dict(funding.iterations)
    iterations.update({"sculpt_tax": ops.iterations, "dsra": case.dsra_iterations, "sizing": sizing.iterations})

    results = ModelResults(
        inputs=inp, timeline=tl, capex=capex, revenue=revenue, opex=opex, funding=funding, tax=tax,
        debt=debt, cfads=cfads, dscr=dscr, llcr=llcr, plcr=plcr, icr=icr, waterfall=waterfall,
        project_cf=project_cf, project_cf_post_grant=project_cf_post, equity_cf=equity_cf,
        metrics=metrics, sizing=sizing, iterations=iterations,
    )
    results.warnings = (list(tl.notes) + list(revenue.notes) + list(opex.notes) + list(debt.warnings)
                        + list(waterfall.warnings))
    if sizing.method == "gearing_and_dscr":
        results.warnings.append(sizing.message)
    results.checks = run_checks(results)
    return results


# ---------------------------------------------------------------------------------------------
# Annual table (the master schedule used by the dashboard and the Excel export)
# ---------------------------------------------------------------------------------------------


def annual_table(res: ModelResults) -> pd.DataFrame:
    tl, cx, fu, rv, ox, tx, db, wf = (res.timeline, res.capex, res.funding, res.revenue, res.opex,
                                      res.tax, res.debt, res.waterfall)
    lev = tx.levered
    cols: dict[str, object] = {
        "Year": tl.year,
        "Fiscal year": list(tl.labels),
        "Phase": ["Construction" if c else "Operation" for c in tl.is_construction],
        "Op year": tl.op_year,
        "Construction flag": tl.is_construction,
        "Operation flag": tl.is_operation,
        "Moratorium flag": tl.is_moratorium,
        "Repayment flag": tl.is_repayment,
        # capex
        "Phasing": cx.phasing,
        "Escalation factor": cx.escalation_factor,
        "Hard cost (before overrun)": cx.hard_cost_before_overrun,
        "Cost overrun (hard)": cx.hard_cost - cx.hard_cost_before_overrun,
        "Hard cost": cx.hard_cost,
        "Contingency": cx.contingency,
        "Pre-operative": cx.preop,
        "Capex": cx.capex,
        "Cumulative capex": cx.cumulative_capex,
        # funding
        "Upfront fees": fu.fees,
        "IDC": fu.idc,
        "IDC (iterative check)": fu.idc_iterative,
        "DSRA initial funding": fu.dsra_funding,
        "Total uses": fu.uses,
        "Grant / construction support": fu.grant,
        "Debt drawdown": fu.debt_draw,
        "Equity contribution": fu.equity,
        "of which equity-funded overrun": fu.equity_only,
        "Total sources": fu.sources,
        "Sources - uses": fu.sources - fu.uses,
    }
    cols.update(rv.drivers)
    cols.update(rv.lines)
    mmra_in_cfads = res.cfads - (ox.ebitda - lev.tax) * tl.is_operation
    cols.update({
        "Total revenue": rv.total,
        "O&M": ox.om,
        "Major maintenance": ox.mmr,
        "Concession fee": ox.concession_fee,
        "Total opex": ox.total,
        "EBITDA": ox.ebitda,
        "Depreciation": lev.depreciation,
        "Interest (tax-deductible)": lev.interest,
        "Profit before tax": lev.pbt,
        "Loss b/f": lev.loss_bf,
        "Loss used": lev.loss_used,
        "Loss expired": lev.loss_expired,
        "Taxable income": lev.taxable_income,
        "Tax": lev.tax,
        "Loss c/f": lev.loss_cf,
        "Unlevered depreciation": tx.unlevered.depreciation,
        "Unlevered tax": tx.unlevered.tax,
        "Unlevered tax (pre-grant)": tx.unlevered_pre_grant.tax,
        "MMRA movement in CFADS": mmra_in_cfads,
        "CFADS": res.cfads,
        "Opening debt": fu.opening_debt + db.opening,
        "IDC (capitalised)": fu.idc,
        "Interest paid": db.interest,
        "Principal": db.principal,
        "Debt service": db.debt_service,
        "Closing debt": fu.closing_debt + db.closing,
        "DSCR": res.dscr,
        "LLCR": res.llcr,
        "PLCR": res.plcr,
        "ICR": res.icr,
        "Cash after debt service": wf.cash_after_debt_service,
        "Debt-service shortfall": wf.ds_shortfall,
        "DSRA target": wf.dsra_target,
        "DSRA opening": wf.dsra_opening,
        "DSRA top-up": wf.dsra_topup,
        "DSRA release": wf.dsra_release,
        "DSRA draw": wf.dsra_draw,
        "DSRA closing": wf.dsra_closing,
        "MMRA contribution": wf.mmra_contribution,
        "MMRA release": wf.mmra_release,
        "MMRA balance": wf.mmra_balance,
        "Cash available for equity": wf.cash_available_for_equity,
        "Lock-up: cash trapped": wf.lockup_trapped,
        "Lock-up: cash released": wf.lockup_released,
        "Lock-up balance": wf.lockup_balance,
        "Distributions": wf.distributions,
        "Sponsor support": wf.sponsor_support,
        "Project cash flow (pre-grant)": res.project_cf,
        "Project cash flow (post-grant)": res.project_cf_post_grant,
        "Equity cash flow": res.equity_cf,
        "Cumulative equity cash flow": np.cumsum(res.equity_cf),
    })
    return pd.DataFrame(cols).set_index("Year")


def schedule_columns(res: ModelResults) -> dict[str, list[str]]:
    rv = res.revenue
    return {
        "Timeline": ["Fiscal year", "Phase", "Op year", "Construction flag", "Operation flag",
                     "Moratorium flag", "Repayment flag"],
        "Capex": ["Phasing", "Escalation factor", "Hard cost (before overrun)", "Cost overrun (hard)",
                  "Hard cost", "Contingency", "Pre-operative", "Capex", "Cumulative capex"],
        "Funding & IDC": ["Capex", "Upfront fees", "IDC", "DSRA initial funding", "Total uses",
                          "Grant / construction support", "Debt drawdown", "Equity contribution",
                          "of which equity-funded overrun", "Total sources", "Sources - uses",
                          "Opening debt", "Closing debt", "IDC (iterative check)"],
        "Revenue": [*rv.drivers.keys(), *rv.lines.keys(), "Total revenue"],
        "Opex & EBITDA": ["Total revenue", "O&M", "Major maintenance", "Concession fee", "Total opex", "EBITDA"],
        "Tax": ["EBITDA", "Depreciation", "Interest (tax-deductible)", "Profit before tax", "Loss b/f",
                "Loss used", "Loss expired", "Taxable income", "Tax", "Loss c/f", "Unlevered depreciation",
                "Unlevered tax", "Unlevered tax (pre-grant)"],
        "CFADS": ["Total revenue", "O&M", "Major maintenance", "Concession fee", "Tax",
                  "MMRA movement in CFADS", "CFADS"],
        "Debt schedule": ["Opening debt", "Debt drawdown", "IDC (capitalised)", "Interest paid", "Principal",
                          "Debt service", "Closing debt"],
        "Cover ratios": ["CFADS", "Debt service", "DSCR", "LLCR", "PLCR", "ICR"],
        "Waterfall": ["CFADS", "Interest paid", "Principal", "Cash after debt service", "Debt-service shortfall",
                      "DSRA top-up", "DSRA release", "DSRA draw", "DSRA closing", "MMRA contribution",
                      "MMRA release", "MMRA balance", "Cash available for equity", "Lock-up: cash trapped",
                      "Lock-up: cash released", "Distributions", "Sponsor support"],
        "Returns": ["Project cash flow (pre-grant)", "Project cash flow (post-grant)", "Equity contribution",
                    "Distributions", "Sponsor support", "Equity cash flow", "Cumulative equity cash flow"],
    }
