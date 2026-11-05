"""Automated integrity checks (README §12.1) and the hand check (README §12.3).

Two kinds of check run on every model result:
* **integrity** checks test the arithmetic (sources = uses, IDC closed form = iteration, debt
  reconciles, NPV at IRR = 0, ...). ``fail`` means the model is wrong and its numbers must not be used.
* **financial** checks test the outcome against lender and sponsor thresholds (DSCR < 1.0,
  covenant breaches, hurdle rate, maturity beyond the concession). They never fail; they ``warn``.

The hand check recomputes the README §12.3 items for the selected years with scalar formulas taken
straight from the inputs (calculator style), independently of the vectorised model code. Where the
README procedure allows a model value as a starting point (an opening balance, losses brought
forward, depreciation), the working text says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from .inputs import RUPEES_PER_CRORE, build_inputs, deep_merge, inputs_to_dict
from .metrics import meets, npv
from .revenue import build_revenue
from .timeline import build_timeline

if TYPE_CHECKING:  # pragma: no cover
    from .model import ModelResults

# Validation tolerances (README §12.1). Numerical, not financial, constants.
TOL_SOURCES_USES = 1e-3
TOL_PHASING = 1e-9
TOL_GEARING = 1e-4
TOL_REPAID = 1e-3
TOL_PRINCIPAL = 1e-3
TOL_IDC = 1e-6
TOL_NPV_AT_IRR = 1e-3
TOL_IRR_CROSS = 1e-6
TOL_IDENTITY = 1e-6
HAND_CHECK_TOLERANCE = 0.01  # README §12.3: differences < 0.01


@dataclass(frozen=True)
class CheckResult:
    id: str
    name: str
    status: str  # pass | fail | warn | info
    detail: str
    category: str  # integrity | financial
    value: float | None = None
    tolerance: float | None = None


def _integrity(cid, name, ok, detail, value=None, tol=None) -> CheckResult:
    return CheckResult(cid, name, "pass" if ok else "fail", detail, "integrity", value, tol)


def _financial(cid, name, ok, detail, value=None, tol=None) -> CheckResult:
    return CheckResult(cid, name, "pass" if ok else "warn", detail, "financial", value, tol)


def _info(cid, name, detail, category="integrity") -> CheckResult:
    return CheckResult(cid, name, "info", detail, category)


def _years(values) -> str:
    return ", ".join(str(v) for v in values)


def run_checks(res: ModelResults) -> list[CheckResult]:
    inp, tl, fu, db, wf, mt = res.inputs, res.timeline, res.funding, res.debt, res.waterfall, res.metrics
    out: list[CheckResult] = []
    op_idx = slice(tl.cod_index, tl.model_years)

    # 1. Sources = uses, every year
    gap = float(np.max(np.abs(fu.sources - fu.uses)))
    out.append(_integrity("C01", "Sources = uses (every year)", gap < TOL_SOURCES_USES,
                          f"Largest |sources - uses| = {gap:.2e} ₹ Cr", gap, TOL_SOURCES_USES))

    # 2. Phasing sums to 100%
    phasing_gap = abs(float(res.capex.phasing.sum()) - 1.0)
    out.append(_integrity("C02", "Construction phasing sums to 100%", phasing_gap < TOL_PHASING,
                          f"Sum of phasing ({res.capex.phasing_source}) - 1 = {phasing_gap:.2e}",
                          phasing_gap, TOL_PHASING))

    # 3. Debt and equity reconcile to the funding method
    base = fu.total_project_cost - fu.grant_total - fu.equity_only_total
    ratio = fu.debt_at_cod / base if base > 0 else 0.0
    eq_gap = abs(fu.total_project_cost - fu.grant_total - fu.debt_at_cod - fu.equity_total)
    gear_gap = abs(ratio - fu.gearing)
    out.append(_integrity(
        "C03", "Debt and equity reconcile to the gearing and funding method",
        gear_gap < TOL_GEARING and eq_gap < TOL_SOURCES_USES,
        f"Debt / (TPC - grant - equity-funded overrun) = {ratio:.6f} vs gearing applied {fu.gearing:.6f} "
        f"({fu.equity_mode}, overrun {inp.stress.overrun_funding}); TPC - grant - debt - equity = {eq_gap:.2e}",
        gear_gap, TOL_GEARING))

    # 4. IDC closed form = iteration
    idc_gap = float(np.max(np.abs(fu.idc - fu.idc_iterative)))
    out.append(_integrity("C04", "IDC closed form = IDC iteration", idc_gap < TOL_IDC,
                          f"Largest difference {idc_gap:.2e} ₹ Cr ({fu.iterations.get('idc_iterative')} "
                          "fixed-point iterations)", idc_gap, TOL_IDC))

    # 5. Debt balance never negative
    min_close = float(min(db.closing.min(), fu.closing_debt.min()))
    out.append(_integrity("C05", "Debt balance never negative", min_close >= -1e-9,
                          f"Lowest closing balance {min_close:,.6f} ₹ Cr", min_close))

    # 6. Principal reconciles to debt at COD
    recon = abs(float(db.principal.sum()) + db.outstanding_at_end - db.amount)
    out.append(_integrity(
        "C06", "Principal repaid + balance outstanding = debt at COD", recon < TOL_PRINCIPAL,
        f"Sum of principal {db.principal.sum():,.4f} + outstanding {db.outstanding_at_end:,.4f} - debt at COD "
        f"{db.amount:,.4f} = {recon:.2e}", recon, TOL_PRINCIPAL))

    # 7. Debt repaid within the contractual tenor (when the tenor fits the concession)
    if tl.maturity_within_concession:
        closing_at_maturity = float(db.closing[tl.index_of_op_year(tl.maturity_op_year)])
        out.append(_integrity(
            "C07", "Debt fully repaid at contractual maturity", closing_at_maturity < TOL_REPAID,
            f"Closing balance in op year {tl.maturity_op_year} = {closing_at_maturity:,.6f} ₹ Cr",
            closing_at_maturity, TOL_REPAID))
    else:
        out.append(_financial(
            "C07", "Debt fully repaid at contractual maturity", False,
            f"Maturity (op year {tl.maturity_op_year}) is after the concession end (op year {tl.operating_years}); "
            f"{db.outstanding_at_end:,.2f} ₹ Cr cannot be repaid from project revenue.",
            db.outstanding_at_end))

    # 8 and 9. NPV at IRR = 0 and cross-check with numpy-financial
    for cid_npv, cid_x, label, result, cf in (
        ("C08a", "C09a", "Project IRR", mt.project_irr, res.project_cf),
        ("C08b", "C09b", "Equity IRR", mt.equity_irr, res.equity_cf),
    ):
        if result.ok:
            residual = abs(npv(result.value, cf))
            out.append(_integrity(cid_npv, f"NPV at {label} = 0", residual < TOL_NPV_AT_IRR,
                                  f"NPV at {result.value:.6%} = {residual:.2e} ₹ Cr", residual, TOL_NPV_AT_IRR))
            if result.numpy_financial is not None:
                diff = abs(result.value - result.numpy_financial)
                out.append(_integrity(cid_x, f"{label} matches numpy-financial", diff < TOL_IRR_CROSS,
                                      f"Own solver {result.value:.8%} vs numpy_financial.irr "
                                      f"{result.numpy_financial:.8%}", diff, TOL_IRR_CROSS))
            else:
                out.append(_info(cid_x, f"{label} matches numpy-financial",
                                 "numpy_financial.irr returned no value; own solver found a unique root."))
        else:
            out.append(_info(cid_npv, f"NPV at {label} = 0", f"No IRR reported: {result.message}"))
            cross = (f" numpy_financial.irr returns {result.numpy_financial:.4%}, but it is not reported because "
                     "a unique IRR could not be established." if result.numpy_financial is not None else "")
            out.append(_info(cid_x, f"{label} matches numpy-financial", f"Not applicable.{cross}"))

    # 10. DSCR < 1.0 warning
    out.append(_financial(
        "C10", "DSCR >= 1.00x in every debt-service year", not mt.dscr_below_one_years,
        "No year below 1.00x" if not mt.dscr_below_one_years else
        f"DSCR below 1.00x in op year(s) {_years(mt.dscr_below_one_years)}: CFADS does not cover debt "
        "service (payment default without support)."))

    # 11. Maturity within the concession
    out.append(_financial(
        "C11", "Debt maturity within the concession (mor + n <= To)", tl.maturity_within_concession,
        f"mor {tl.moratorium_years} + tenor {tl.tenor_years} = {tl.maturity_op_year} vs {tl.operating_years} "
        f"operating years; contractual tail {tl.contractual_tail_years} year(s)."))

    # 12 and 13. HAM revenue invariance to traffic and to actual cost
    raw = inputs_to_dict(inp)
    if inp.project_type == "ham":
        for cid, name, override in (
            ("C12", "Traffic shortfall does not change HAM revenue", {"stress": {"demand_shortfall": 0.30}}),
            ("C13", "Cost overrun does not change HAM revenue (BPC-based)", {"stress": {"cost_overrun": 0.25}}),
        ):
            alt = build_inputs(deep_merge(raw, override))
            alt_rev = build_revenue(alt, build_timeline(alt))
            diff = float(np.max(np.abs(alt_rev.total - res.revenue.total)))
            sup = float(np.max(np.abs(alt_rev.construction_support - res.revenue.construction_support)))
            out.append(_integrity(cid, name, diff == 0.0 and sup == 0.0,
                                  f"Largest revenue change {diff:.2e} ₹ Cr; construction support change {sup:.2e}",
                                  diff, 0.0))
    else:
        bumped = min(inp.stress.demand_shortfall + 0.10, 0.95)
        alt = build_inputs(deep_merge(raw, {"stress": {"demand_shortfall": bumped}}))
        alt_rev = build_revenue(alt, build_timeline(alt))
        responds = bool(np.all(alt_rev.total[op_idx] <= res.revenue.total[op_idx] + 1e-9))
        out.append(_integrity("C12", "Traffic shortfall reduces (never raises) revenue", responds,
                              f"{inp.project_type} revenue with a further 10% shortfall is lower or equal every year"))

    # 14. PV of debt service at r equals debt at COD
    if db.fully_repaid and db.amount > 0:
        k = tl.op_year[op_idx].astype(float)
        pv = float(np.sum(db.debt_service[op_idx] * (1.0 + db.rate) ** (-k)))
        rel = abs(pv - db.amount) / db.amount
        out.append(_integrity("C14", "PV of debt service at r = debt at COD", rel < TOL_IDENTITY,
                              f"PV {pv:,.6f} vs debt {db.amount:,.6f} (relative gap {rel:.2e})", rel, TOL_IDENTITY))
    else:
        out.append(_info("C14", "PV of debt service at r = debt at COD", "Not applicable: debt not fully repaid."))

    # 15. Waterfall balances every year
    flows = (wf.cfads - wf.debt_service - wf.dsra_topup + wf.dsra_release + wf.dsra_draw - wf.mmra_contribution
             + wf.mmra_release - wf.lockup_trapped + wf.lockup_released - wf.distributions + wf.sponsor_support)
    wf_gap = float(np.max(np.abs(flows[op_idx]))) if tl.operating_years else 0.0
    out.append(_integrity("C15", "Cash-flow waterfall balances (every year)", wf_gap < TOL_IDENTITY,
                          f"Largest unexplained cash {wf_gap:.2e} ₹ Cr", wf_gap, TOL_IDENTITY))

    # 16. Reserve balances never negative
    lowest = float(min(wf.dsra_closing.min(), wf.mmra_balance.min(), wf.lockup_balance.min()))
    out.append(_integrity("C16", "Reserve balances never negative", lowest >= -1e-9,
                          f"Lowest DSRA / MMRA / lock-up balance {lowest:,.6f} ₹ Cr", lowest))

    # 17. Depreciation totals the depreciable cost
    dep_gap = abs(float(res.tax.levered.depreciation.sum()) - res.tax.depreciable_cost)
    out.append(_integrity("C17", "Depreciation = depreciable cost", dep_gap < TOL_IDENTITY,
                          f"Sum of depreciation - depreciable cost {res.tax.depreciable_cost:,.4f} = {dep_gap:.2e}",
                          dep_gap, TOL_IDENTITY))

    # 18. Tax and losses
    tax_ok = bool(np.all(res.tax.levered.tax >= 0) and np.all(res.tax.levered.loss_cf >= -1e-9))
    out.append(_integrity("C18", "Tax and tax losses never negative", tax_ok,
                          f"Total tax {res.tax.levered.tax.sum():,.2f} ₹ Cr; losses expired "
                          f"{res.tax.levered.loss_expired.sum():,.2f} ₹ Cr"))

    # 19. Principal is zero during the moratorium
    mor_principal = float(np.abs(db.principal[tl.is_moratorium > 0]).sum())
    out.append(_integrity("C19", "No principal repaid during the moratorium", mor_principal == 0.0,
                          f"Principal in moratorium years = {mor_principal:.2e} ₹ Cr", mor_principal, 0.0))

    # 20. Repayment profile shape
    out.append(_profile_check(res))

    # 21-24. Financial thresholds
    cov = inp.covenants
    if mt.min_dscr is not None:
        out.append(_financial("C21", f"Minimum DSCR >= covenant {cov.min_dscr:.2f}x", meets(mt.min_dscr, cov.min_dscr),
                              f"Minimum DSCR {mt.min_dscr:.4f}x in op year {mt.min_dscr_op_year}; below covenant in "
                              f"op year(s) {_years(mt.dscr_below_covenant_years) or 'none'}", mt.min_dscr, cov.min_dscr))
    if mt.llcr_cod is not None:
        out.append(_financial("C22", f"LLCR at COD >= covenant {cov.min_llcr:.2f}x", meets(mt.llcr_cod, cov.min_llcr),
                              f"LLCR at COD {mt.llcr_cod:.4f}x", mt.llcr_cod, cov.min_llcr))
    hurdle = inp.valuation.equity_hurdle
    if mt.equity_irr.ok:
        out.append(_financial("C23", f"Equity IRR >= hurdle {hurdle:.1%}", meets(mt.equity_irr.value, hurdle),
                              f"Equity IRR {mt.equity_irr.value:.4%}", mt.equity_irr.value, hurdle))
    else:
        out.append(_financial("C23", f"Equity IRR >= hurdle {hurdle:.1%}", False,
                              f"Equity IRR not available: {mt.equity_irr.message}"))
    out.append(_financial("C24", "No sponsor support needed", mt.sponsor_support < 1e-9,
                          f"Sponsor support {mt.sponsor_support:,.2f} ₹ Cr; debt-service shortfall "
                          f"{mt.ds_shortfall:,.2f} ₹ Cr", mt.sponsor_support))

    # 25. Debt sizing / target DSCR claims are backed by the schedule
    sz = res.sizing
    if sz.method == "gearing_and_dscr":
        target_met = mt.min_dscr is None or mt.min_dscr >= sz.target_dscr - 1e-6
        out.append(_integrity("C25", f"DSCR sizing: minimum DSCR >= {sz.target_dscr:.2f}x target", target_met,
                              f"{sz.binding} binds; minimum DSCR "
                              f"{'n/a' if mt.min_dscr is None else f'{mt.min_dscr:.4f}x'}; {sz.message}"))
    else:
        out.append(_info("C25", "DSCR sizing", f"Not used: {sz.message}"))

    # 26. Concession end not extended by a delay
    if inp.timeline.concession_end_fixed:
        fixed = tl.model_years == inp.timeline.concession_years
        out.append(_integrity("C26", "Concession end date unchanged by delay", fixed,
                              f"Model ends in year {tl.model_years} = concession {inp.timeline.concession_years} "
                              f"years; delay {tl.delay_years} year(s) shortened operations to {tl.operating_years}."))
    else:
        out.append(_info("C26", "Concession end date unchanged by delay",
                         f"concession_end_fixed is false: operations run {tl.operating_years} years from COD."))
    return out


def _profile_check(res: ModelResults) -> CheckResult:
    db, tl, inp = res.debt, res.timeline, res.inputs
    name = f"Repayment profile shape ({db.profile})"
    rep = np.where(tl.is_repayment > 0)[0]
    if db.amount <= 0 or rep.size == 0:
        return _info("C20", name, "No debt or no repayment years.")
    if db.profile == "annuity":
        spread = float(np.ptp(db.debt_service[rep]))
        return _integrity("C20", name, spread < TOL_IDENTITY, f"Debt service range across repayment years "
                          f"{spread:.2e} ₹ Cr (level annuity)", spread, TOL_IDENTITY)
    if db.profile == "equal":
        spread = float(np.ptp(db.principal[rep]))
        return _integrity("C20", name, spread < TOL_IDENTITY, f"Principal range {spread:.2e} ₹ Cr (equal "
                          "instalments)", spread, TOL_IDENTITY)
    if db.profile == "structured":
        expected = db.amount * np.asarray(inp.debt.structured_pct[: rep.size])
        gap = float(np.max(np.abs(db.principal[rep] - expected)))
        return _integrity("C20", name, gap < TOL_IDENTITY, f"Largest gap to D x s_k {gap:.2e} ₹ Cr", gap, TOL_IDENTITY)
    free = [i for i in rep if int(tl.op_year[i]) not in db.floored_years and db.debt_service[i] > 0]
    spread = float(np.ptp(res.dscr[free])) if free else 0.0
    detail = (f"DSCR in sculpted (unfloored) years = {db.sculpt_dscr:.4f}x (spread {spread:.2e}); target "
              f"{inp.debt.target_dscr:.2f}x")
    if db.floored_years:
        detail += f"; principal floored at zero in op year(s) {_years(db.floored_years)}"
    return _integrity("C20", name, spread < 1e-6, detail, spread, 1e-6)


# ---------------------------------------------------------------------------------------------
# Hand check (README §12.3)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HandCheckRow:
    section: str
    item: str
    working: str
    hand_value: float
    model_value: float

    @property
    def difference(self) -> float:
        return self.model_value - self.hand_value

    @property
    def ok(self) -> bool:
        return abs(self.difference) < HAND_CHECK_TOLERANCE


def _f(x: float, d: int = 4) -> str:
    return f"{x:,.{d}f}"


def _hand_revenue(res: ModelResults, k: int) -> tuple[float, str]:
    inp, tl = res.inputs, res.timeline
    e = k - 1 + (tl.delay_years if inp.timeline.indexation_basis == "calendar" else 0)
    sh = inp.stress.demand_shortfall
    blk = inp.revenue_block
    if inp.project_type == "toll":
        ramp = blk.ramp_up[k - 1] if k <= len(blk.ramp_up) else 1.0
        traffic = blk.aadt * (1 + blk.growth) ** e * ramp * (1 - sh)
        if blk.capacity is not None:
            traffic = min(traffic, blk.capacity)
        traffic *= 1 - blk.leakage
        rate = blk.rate * (1 + blk.rate_escalation) ** e
        value = traffic * rate * blk.days_per_year / RUPEES_PER_CRORE
        working = (f"{blk.aadt:,.0f} x {1 + blk.growth:.4f}^{e} x {ramp:.2f} x (1-{sh:.2f}) x (1-{blk.leakage:.2f}) "
                   f"x {blk.rate:,.2f} x {1 + blk.rate_escalation:.4f}^{e} x {blk.days_per_year} / 1e7")
        return value, working
    if inp.project_type == "metro":
        ramp = blk.ramp_up[k - 1] if k <= len(blk.ramp_up) else 1.0
        riders = blk.ridership * (1 + blk.growth) ** e * ramp * (1 - sh)
        if blk.capacity is not None:
            riders = min(riders, blk.capacity)
        revisions = math.floor(e / blk.fare_revision_every)
        fare = blk.fare * (1 + blk.fare_revision_pct) ** revisions
        value = riders * fare * blk.days_per_year / RUPEES_PER_CRORE * (1 + blk.non_fare_pct)
        working = (f"min({blk.ridership:,.0f} x {1 + blk.growth:.4f}^{e} x {ramp:.2f} x (1-{sh:.2f}), cap) x "
                   f"{blk.fare:.2f} x {1 + blk.fare_revision_pct:.2f}^{revisions} x {blk.days_per_year} / 1e7 "
                   f"x (1 + {blk.non_fare_pct:.2f})")
        return value, working
    a0 = (1 - blk.construction_support_pct) * blk.bid_project_cost * (1 + blk.pim_inflation) ** tl.construction_years
    per, n_inst = blk.instalments_per_year, blk.annuity_instalments
    principal = interest = 0.0
    for h in range((k - 1) * per + 1, k * per + 1):
        if h <= n_inst:
            principal += a0 / n_inst
            interest += blk.annuity_interest_rate / per * (a0 - (h - 1) * a0 / n_inst)
    om_pay = blk.om_payment * (1 + blk.pim_inflation) ** e
    working = (f"A0 = {1 - blk.construction_support_pct:.2f} x {blk.bid_project_cost:,.2f} x "
               f"{1 + blk.pim_inflation:.4f}^{tl.construction_years} = {_f(a0)}; principal {_f(principal)} + "
               f"interest {_f(interest)} + O&M payment {blk.om_payment:.2f} x {1 + blk.pim_inflation:.4f}^{e}")
    return principal + interest + om_pay, working


def _hand_principal(res: ModelResults, k: int, opening: float) -> tuple[float, str]:
    inp, tl, db = res.inputs, res.timeline, res.debt
    r, n, mor, d = db.rate, tl.tenor_years, tl.moratorium_years, db.amount
    j = k - mor
    if j < 1 or j > n:
        return 0.0, "moratorium / outside the repayment window: no principal"
    if db.profile == "annuity":
        ds = d * r / (1 - (1 + r) ** (-n)) if r else d / n
        p1 = ds - r * d
        return p1 * (1 + r) ** (j - 1), f"(DS {_f(ds)} - r x D {_f(r * d)}) x {1 + r:.4f}^{j - 1}"
    if db.profile == "equal":
        return d / n, f"D {_f(d)} / n {n}"
    if db.profile == "structured":
        s = inp.debt.structured_pct[j - 1]
        return d * s, f"D {_f(d)} x s_{j} {s:.4f}"
    ds_model = float(db.debt_service[tl.index_of_op_year(k)])
    return ds_model - r * opening, f"sculpted DS {_f(ds_model)} (model value) - interest {_f(r * opening)}"


def hand_check(res: ModelResults) -> list[HandCheckRow]:
    """README §12.3 hand check for construction year 2 and the selected operating years."""
    inp, tl, fu, db, tx = res.inputs, res.timeline, res.funding, res.debt, res.tax.levered
    rows: list[HandCheckRow] = []
    r, m, g = inp.interest_rate, inp.funding.drawdown_timing, fu.gearing

    # 1. IDC in construction year 2 (pro-rata funding): closed form, then the identity
    if inp.funding.equity_mode == "pro_rata" and tl.construction_years >= 2:
        cx = inp.capex
        phase = res.capex.phasing  # base phasing, or the stretched phasing in a delay case (model value)
        eq_only = inp.stress.overrun_funding == "equity"
        balance = 0.0
        for t in (1, 2):
            hard_before = cx.base_cost * phase[t - 1] * (1 + cx.escalation) ** (t - 1)
            hard = hard_before * (1 + inp.stress.cost_overrun)
            capex_t = hard * (1 + cx.contingency + cx.preop)
            grant_t = float(fu.grant[t - 1])
            funded = (hard_before * (1 + cx.contingency + cx.preop) if eq_only else capex_t) - grant_t
            funded += float(fu.fees[t - 1])
            idc = (r * balance + m * r * g * funded) / (1 - m * r * g)
            draw = g * (funded + idc)
            if t == 2:
                working = (f"[{r:.4f} x {_f(balance)} + {m} x {r:.4f} x {g:.4f} x {_f(funded)}] / "
                           f"(1 - {m} x {r:.4f} x {g:.4f})")
                rows.append(HandCheckRow("Construction year 2", "IDC", working, idc, float(fu.idc[1])))
                rows.append(HandCheckRow("Construction year 2", "Debt draw", f"{g:.4f} x ({_f(funded)} + {_f(idc)})",
                                         draw, float(fu.debt_draw[1])))
                rows.append(HandCheckRow("Construction year 2", "IDC identity r x (Open + m x Draw)",
                                         f"{r:.4f} x ({_f(balance)} + {m} x {_f(draw)})", r * (balance + m * draw),
                                         float(fu.idc[1])))
                rows.append(HandCheckRow("Construction year 2", "Closing debt", f"{_f(balance)} + {_f(draw)}",
                                         balance + draw, float(fu.closing_debt[1])))
            balance += draw

    d = db.amount
    if d <= 0:
        return rows

    # 2. Debt service amount (annuity) or first instalment (other profiles)
    if db.profile == "annuity":
        n = tl.tenor_years
        ds = d * r / (1 - (1 + r) ** (-n)) if r else d / n
        k_first = tl.moratorium_years + 1
        rows.append(HandCheckRow("Debt service", "Level annuity DS",
                                 f"{_f(d)} (debt at COD, model value) x {r:.4f} / (1 - {1 + r:.4f}^-{n})",
                                 ds, float(db.debt_service[tl.index_of_op_year(k_first)])))

    def year_rows(k: int, section: str, opening_from_model: bool) -> None:
        i = tl.index_of_op_year(k)
        e = float(tl.index_exponent[i])
        rev, rev_working = _hand_revenue(res, k)
        rows.append(HandCheckRow(section, "Revenue", rev_working, rev, float(res.revenue.total[i])))
        om = inp.opex.om_base * (1 + inp.opex.om_escalation) ** e
        mmr = inp.opex.mmr_base * (1 + inp.opex.om_escalation) ** e if k in res.opex.mmr_years_applied else 0.0
        fee = (inp.opex.concession_fee_pct * rev
               + inp.opex.concession_premium * (1 + inp.opex.premium_escalation) ** e)
        rows.append(HandCheckRow(section, "O&M", f"{inp.opex.om_base:.2f} x {1 + inp.opex.om_escalation:.4f}^{e:.0f}",
                                 om, float(res.opex.om[i])))
        if mmr:
            rows.append(HandCheckRow(section, "Major maintenance",
                                     f"{inp.opex.mmr_base:.2f} x {1 + inp.opex.om_escalation:.4f}^{e:.0f}",
                                     mmr, float(res.opex.mmr[i])))
        if opening_from_model:
            opening = float(db.opening[i])
            open_working = f"{_f(opening)} (closing balance of the previous year, model value)"
        elif db.profile == "annuity" and k > tl.moratorium_years + 1:
            n, j = tl.tenor_years, k - tl.moratorium_years - 1
            ds = d * r / (1 - (1 + r) ** (-n)) if r else d / n
            opening = d * (1 + r) ** j - ds * ((1 + r) ** j - 1) / r if r else d - ds * j
            open_working = f"D x {1 + r:.4f}^{j} - DS x [{1 + r:.4f}^{j} - 1] / r (annuity shortcut)"
        else:
            opening = d
            open_working = f"debt at COD {_f(d)} (model value)"
        rows.append(HandCheckRow(section, "Opening debt", open_working, opening, float(db.opening[i])))
        interest = r * opening
        rows.append(HandCheckRow(section, "Interest", f"{r:.4f} x {_f(opening)}", interest, float(db.interest[i])))
        principal, p_working = _hand_principal(res, k, opening)
        rows.append(HandCheckRow(section, "Principal", p_working, principal, float(db.principal[i])))
        rows.append(HandCheckRow(section, "Closing debt", f"{_f(opening)} - {_f(principal)}", opening - principal,
                                 float(db.closing[i])))
        dep = float(tx.depreciation[i])
        pbt = rev - om - mmr - fee - dep - interest
        loss_bf = float(tx.loss_bf[i])
        taxable = max(0.0, pbt - loss_bf) if pbt > 0 else 0.0
        tax = inp.tax.rate * taxable
        rows.append(HandCheckRow(section, "Profit before tax",
                                 f"{_f(rev)} - {_f(om)} - {_f(mmr)} - {_f(fee)} - dep {_f(dep)} (model) - {_f(interest)}",
                                 pbt, float(tx.pbt[i])))
        rows.append(HandCheckRow(section, "Tax",
                                 f"{inp.tax.rate:.4f} x max(0, {_f(pbt)} - loss b/f {_f(loss_bf)} (model value))",
                                 tax, float(tx.tax[i])))
        reserve_adj = float(res.cfads[i] - (res.opex.ebitda[i] - tx.tax[i]))
        cfads = rev - om - mmr - fee - tax + reserve_adj
        cf_working = f"{_f(rev)} - {_f(om)} - {_f(mmr)} - {_f(fee)} - {_f(tax)}"
        if abs(reserve_adj) > 1e-12:
            cf_working += f" + MMRA movement {_f(reserve_adj)} (model value)"
        rows.append(HandCheckRow(section, "CFADS", cf_working, cfads, float(res.cfads[i])))
        ds = interest + principal
        if ds > 0:
            rows.append(HandCheckRow(section, "DSCR", f"{_f(cfads)} / ({_f(interest)} + {_f(principal)})",
                                     cfads / ds, float(res.dscr[i])))

    year_rows(1, "Op year 1", opening_from_model=False)
    mmr_in_window = [k for k in res.opex.mmr_years_applied if 1 < k <= tl.last_repayment_op_year]
    if mmr_in_window:
        k = mmr_in_window[0]
        year_rows(k, f"Op year {k} (major maintenance)", opening_from_model=db.profile != "annuity")
    final_k = tl.last_repayment_op_year
    if final_k > 1 and (not mmr_in_window or final_k != mmr_in_window[0]):
        year_rows(final_k, f"Op year {final_k} (final repayment)", opening_from_model=db.profile != "annuity")
    return rows
