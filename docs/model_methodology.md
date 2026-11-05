# Model methodology

This document describes how the Python engine in `src/ppp_model/` calculates every number, in the
order it calculates them. The README is the specification; this file records how each formula was
implemented and where an interpretation was needed. Departures from the README are explained in
`docs/assumptions_and_limitations.md`.

All money is in ₹ crore. Rates and shares are decimals in the code and YAML (0.10 = 10%).

## 1. How to run it

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .                      # makes `import ppp_model` work everywhere

python -m pytest                      # 197 automated tests
python -m ppp_model run --type toll   # headline results and checks for a base case
python -m ppp_model scenarios --type ham
python -m ppp_model export --type metro          # writes outputs/ppp_model_metro_base.xlsx
python -m ppp_model charts --type metro          # README §14.3 report charts in outputs/charts/metro/
python -m ppp_model hand-check --type toll       # writes validation/hand_check.xlsx and .md
streamlit run app/dashboard.py        # interactive dashboard
```

From Python:

```python
from ppp_model import load_inputs, run_model, base_config_path
res = run_model(load_inputs(base_config_path("toll")))
res.metrics.min_dscr, res.metrics.equity_irr.value   # 1.2585, 0.2002
res.annual                                           # every line item, one row per year
```

## 2. Architecture and calculation order

| Step | Module | Produces |
|---|---|---|
| 0 | `inputs.py` | Typed, validated `ModelInputs` from YAML (+ scenario overrides) |
| 1 | `timeline.py` | Years, operating-year index `k`, 0/1 flags, escalation exponent |
| 2 | `capex.py` | Phased, escalated capex with contingency, pre-operative cost and overrun |
| 3 | `revenue.py` | Toll / metro / HAM revenue; HAM construction support |
| 4 | `opex.py` | O&M, major maintenance (MMR), concession fee, EBITDA, MMRA schedule |
| 5 | `funding.py` | Sources and uses, grant, debt and equity draws, IDC, fees |
| 6 | `debt.py` + `tax.py` | Debt schedule ⇄ tax ⇄ CFADS (iterated for sculpting) |
| 7 | `cashflow.py` | CFADS and the waterfall (DSRA, MMRA, lock-up, distributions, sponsor support) |
| 8 | `metrics.py` | DSCR, LLCR, PLCR, ICR, IRRs, NPV, payback |
| 9 | `checks.py` | Integrity checks, financial warnings, hand check |
| 10 | `scenarios.py` | Scenario table, two-way table, tornado, break-even, profile comparison |
| 11 | `export.py` | Excel workbook (values, no formulas) |
| 12 | `report_charts.py` | The eight README §14.3 report charts as PNG (Matplotlib) |
| — | `model.py` | `run_model()`: runs steps 1-9 and assembles `ModelResults` and the annual table |

`app/dashboard.py` contains no financial formulas. It calls `run_model()` and the scenario functions
and displays what they return.

Revenue and opex are computed before funding (README §7.2 lists funding first). Neither depends on
funding, and the HAM construction support, a revenue item, is needed by the funding module as its
grant.

## 3. Conventions (README §5)

* **Periods.** Annual. Model year `t = 1..N`; operating year `k = t - Tc`. With no delay,
  `N = Tcon = 20` and `Tc = 3` in the toll base.
* **Timing.** Cash flows at the end of each year, except construction drawdowns, which earn interest
  for `m = 0.5` of the year (mid-year convention).
* **Escalation exponent.** In operating year `k` prices and traffic grow by `(1+g)^(k-1)`, so op year 1
  carries the base value (README §16). Under `indexation_basis: calendar` the exponent is the number of
  years since the *scheduled* COD instead; it differs only in a delay case (see §11).
* **Interest.** On the opening balance (plus `m` × the drawdown during construction).
* **Signs.** In IRR arrays money out of the investor is negative.
* **No hard-coded financial numbers.** Every assumption is in `config/*.yaml`. The only constants in
  code are the unit definition 1 crore = 10^7 rupees and numerical tolerances.

## 4. Inputs and validation

`inputs.py` maps each YAML block onto a frozen dataclass. Validation is strict and reports every
problem at once:

* unknown keys (with a "did you mean" suggestion), missing keys, wrong types, whole-number fields
  given fractions (for example a 0.5-year delay);
* ranges: gearing in [0, 1), rates within sensible bounds, ramp-up factors in (0, 1], target DSCR ≥ 1;
* consistency: phasing, structured repayment and milestone shares sum to 100% with the right number of
  entries; the revenue block matches the project type; mor + n ≤ operating years in the base case;
  major-maintenance years fall inside operations; HAM annuities fit the operating period; HAM has no
  separate grant; a delay leaves at least one operating year.

Nothing is clipped or replaced. A failure raises `InputValidationError` listing each message.

### README symbols → YAML keys

| README | YAML key | README | YAML key |
|---|---|---|---|
| `Tc` | `timeline.construction_years` | `AADT0` | `revenue.toll.aadt` |
| `Tcon` | `timeline.concession_years` | `g_tr` | `revenue.toll.growth` |
| `delay_years` | `stress.delay_years` | `rate0` | `revenue.toll.rate` |
| `C0` | `capex.base_cost` | `e_toll` | `revenue.toll.rate_escalation` |
| `p_t` | `capex.phasing` | `R_k` | `revenue.<type>.ramp_up` |
| `e_c` | `capex.escalation` | `leak` | `revenue.toll.leakage` |
| `cont` | `capex.contingency` | `cap` | `revenue.toll.capacity` |
| `preop` | `capex.preop` | `short` | `stress.demand_shortfall` |
| `overrun` | `stress.cost_overrun` | `OM0` | `opex.om_base` |
| `overrun_mode` | `stress.overrun_funding` | `e_om` | `opex.om_escalation` |
| `g` | `funding.gearing` | `MMR0` | `opex.mmr_base` |
| `grant_pct` | `funding.grant_pct` | `tax` | `tax.rate` |
| `eq_mode` | `funding.equity_mode` | `r` | `debt.interest_rate` (+ `stress.rate_shock`) |
| `m` | `funding.drawdown_timing` | `n` | `debt.tenor_years` |
| `fee` | `funding.upfront_fee` | `mor` | `debt.moratorium_years` |
| `profile` | `debt.profile` | `s_k` | `debt.structured_pct` |
| `dscr_target` | `debt.target_dscr` | `dsra_months` | `reserves.dsra_months` |
| `lockup` | `reserves.lockup_dscr` | `i_ham` | `revenue.ham.annuity_interest_rate` |

Scenario levers (`short`, `overrun`, `overrun_mode`, `delay_years`, rate shock) live in one `stress`
block, all zero in the base files, so each scenario overrides only that block.

## 5. Timeline (README §9.1)

```
is_constr[t] = t ≤ Tc      is_op[t] = t > Tc      k[t] = t − Tc
is_moratorium[t] = 1 ≤ k ≤ mor
is_repay[t] = mor < k ≤ min(mor + n, To)
```

**Construction delay.** `Tc → Tc + d`. With `concession_end_fixed: true` (toll, metro, and the README
rule) `N` is unchanged and operations shrink to `To − d`. If that pushes the loan maturity past the
concession end, the model does not extend anything. The repayments that would fall outside the
concession are not made, the unpaid balance is reported, and checks C07/C11 warn. HAM uses
`concession_end_fixed: false`, so the 15-year annuity period runs from the actual COD (see the
assumptions file).

## 6. Capital cost (README §9.2)

```
Hard[t]  = C0 × p[t] × (1 + e_c)^(t−1) × (1 + overrun)
Cont[t]  = cont × Hard[t];   PreOp[t] = preop × Hard[t]
Capex[t] = Hard[t] + Cont[t] + PreOp[t]
```

The capex before overrun is kept separately so that an equity-funded overrun and a grant fixed at
award can be identified. In a delay case the phasing is re-spread over `Tc + d` years by stretching
the cumulative S-curve (30/40/30 → 22.5/27.5/27.5/22.5), unless `stress.delay_phasing` gives it
explicitly.

## 7. Funding and IDC (README §9.3-9.4)

```
USES[t]   = Capex[t] + Fees[t] + IDC[t] (+ DSRA initial funding at the end of year Tc)
Grant[t]  = grant_pct × Capex_before_overrun[t]  (+ HAM construction support[t])
K[t]      = Capex[t] + Fees[t] − Grant[t] − EquityFundedOverrun[t]
IDC[t]    = r × (Open[t] + m × Draw[t])
```

**Pro-rata (closed form).** Substituting `Draw = g × (K + IDC)` gives

```
IDC[t] = (r × Open[t] + m × r × g × K[t]) / (1 − m × r × g)
Draw[t] = g × (K[t] + IDC[t]);   Equity[t] = (1 − g) × (K[t] + IDC[t]) + EquityFundedOverrun[t]
```

**Equity-first.** Equity's commitment is `(1 − g) × total need + equity-funded overrun`. Equity pays
every use until the commitment is spent; in the year it runs out the debt draw solves
`Draw = (uses − equity remaining + r × Open) / (1 − m × r)`. The commitment depends on total IDC, so it
is iterated to convergence. Total debt still equals `g × (TPC − grant)`, but IDC is lower because
debt is drawn later: in the toll base, 77.37 against 113.08.

**Independent check.** `idc_by_iteration()` re-solves IDC with the README §7.3 fixed-point loop
(guess IDC, fund the uses, recompute IDC). It shares no algebra with the closed form. Check C04
requires the two to agree within 10⁻⁶. In the base case they differ by 3.6 × 10⁻¹³.

**Upfront fee.** `fee × debt at COD`, paid in year 1 and funded like capex; solved by fixed-point
iteration because debt includes the fee.

**Cost-overrun funding.** `pro_rata`: the overrun is part of `K`, so debt rises (857.07 at +10%).
`equity`: the overrun is removed from `K` and added 100% to equity, so debt and IDC are unchanged.

**Sources = uses** holds in every year by construction and is re-checked (C01). Gearing is checked as
`Debt / (TPC − Grant − equity-funded overrun) = g` (C03).

## 8. Revenue (README §9.5)

**Toll.** `Traffic[k] = AADT0 × (1+g_tr)^(k−1) × R[k] × (1−short)`, capped at road capacity, then
`× (1−leak)` for the paying share; `Revenue = Traffic × rate0 × (1+e_toll)^(k−1) × 365 / 10^7`.
`R[k]` multiplies (it is not compounded) and is 100% after the listed years.

**Metro.** `Riders[k] = min(R0 × (1+g)^(k−1) × R[k] × (1−short), capacity)`;
`Fare[k] = Fare0 × (1+rev%)^floor((k−1)/every)`; non-fare revenue = `nfr% × fare revenue`.

**HAM.** Paid by the Authority. The function takes no traffic input, so a shortfall cannot reach it.
* Construction support: `40% × BPC × PIM[t] × milestone share[t]`, with `PIM[t] = (1+π)^(t−1)` from
  the bid date. It is treated as the grant in sources and uses.
* Completion cost (annuity principal): `A0 = 60% × BPC × PIM at COD`, with PIM at COD `(1+π)^Tc`.
* 30 semi-annual instalments: principal `A0/30` each; interest `i_ham/2 × opening annuity balance`.
  Instalments falling in operating year `k` are summed into that annual period.
* O&M payment: `om_payment × (1+π)^(k−1)` (bid amount in op-year-1 prices).

Payments depend on the Bid Project Cost, not actual cost, so a cost overrun leaves revenue unchanged.
Checks C12 and C13 re-run HAM revenue with a 30% shortfall and a 25% overrun and require identical
results.

## 9. Operating costs (README §9.6)

```
OM[k]  = OM0 × (1+e_om)^(k−1)
MMR[k] = MMR0 × (1+e_om)^(k−1)  in listed major-maintenance years
ConFee[k] = fee% × Revenue[k] + premium × (1+e_prem)^(k−1)
EBITDA[k] = Revenue[k] − OM[k] − MMR[k] − ConFee[k]
```

**MMRA (optional).** Contributions are spread evenly up to each MMR,
`contribution[k] = (MMR_next − balance) / years until MMR_next`, so the balance equals the MMR cost
in its year and is then released to pay it.

## 10. Debt, tax and CFADS (README §9.7-9.9)

**Debt schedule.** `Interest[k] = r × Open[k]`, `Close[k] = Open[k] − Principal[k]`, `DS = I + P`.

| Profile | Principal in repayment year j = k − mor |
|---|---|
| equal | `D / n` |
| annuity | `(DS − r × D) × (1+r)^(j−1)`, with `DS = D × r / (1 − (1+r)^−n)` |
| structured | `D × s[j]` |
| sculpted | `DS[k] = CFADS[k] × λ`, with `λ` solved so the loan is repaid at maturity |

Interest-only during the moratorium. Principal never exceeds the balance, and floating-point residue
of at most 10⁻⁹ × D is cleared at contractual maturity; a real shortfall is never cleared.

**Sculpting.** Without constraints `λ = D × (1+r)^−mor / PV_r(CFADS over the repayment years)`, so
every repayment year has `DSCR = 1/λ`. When gearing binds this is `PV(CFADS)/D` (README §9.9).
If sculpted debt service would be below interest (the README pitfall), the default `floor` rule makes
that year interest-only and re-solves `λ` by bisection on the final balance. The alternative
`capitalise` rule lets principal go negative explicitly (the loan grows). Both cases are reported.
In the toll base, sculpting floors op years 1 and 5.

**Debt sizing.** `sizing: gearing` uses `D = g × (TPC − grant)`. `gearing_and_dscr` first runs the
gearing case. If its minimum DSCR is below the target it bisects on the applied gearing, re-running
funding, IDC, tax and CFADS each time, to find the largest debt whose own schedule meets the target.
This is `min(D_gearing, D_DSCR)` (README §9.9). For a sculpted profile the README formula
`D_DSCR = (1+r)^mor × Σ (CFADS[k]/target)/(1+r)^k` is also reported. Example: toll base sized at a
1.30x target gives debt 754.29 (gearing 67.98%) and a minimum DSCR of exactly 1.300000.

**Tax.**

```
Dep[k]   = depreciable cost / L      (L = operating years unless set; remainder written off at handback)
PBT[k]   = EBITDA[k] − Dep[k] − Interest[k]
Tax[k]   = tax × max(0, PBT[k] − losses brought forward)
```

Depreciable cost = capex + fees + IDC, net of the grant when `depreciation_net_of_grant`. Losses carry
forward without limit by default, which reproduces the README recurrence exactly (a property test
checks 50 random cases). With `loss_carry_forward_years: L`, losses are tracked by year of origin,
used oldest first, and lapse after L years.

**Unlevered tax** (Project IRR only): same rules, interest = 0, depreciation on capex excluding IDC and
fees. A pre-grant version depreciates gross capex; the post-grant version follows the net-of-grant
setting.

**Circularity.** For equal, annuity and structured profiles the schedule does not depend on CFADS, so
tax follows directly. For sculpting, debt service depends on CFADS, CFADS on tax, tax on interest and
interest on the schedule. The model iterates on CFADS until the largest change is below 10⁻¹⁰ and
raises `ConvergenceError` if it is not reached. A DSRA funded at COD adds an outer loop on the initial
DSRA amount.

**CFADS** = `Revenue − OM − MMR − ConFee − Tax` (+ MMRA release − contribution when the MMRA sits
inside CFADS).

## 11. Waterfall (README §9.10-9.11)

Each operating year, in the README §9.11 order:

1. Cash after debt service = CFADS − interest − principal. A negative value is a debt-service
   shortfall (DSCR < 1). It is recorded, drawn from the DSRA if funded, and any remainder becomes
   **sponsor support**, a negative equity cash flow, with a warning.
2. DSRA: top up towards `dsra_months/12 × next year's DS` from available cash (a reserve cannot create
   cash, so it may take more than a year to fill) and release any excess. The target is zero after
   the last payment, so the DSRA is returned to equity.
3. MMRA contribution and release (when positioned after debt service, the default).
4. Lock-up: if DSCR is below `lockup_dscr` while debt is outstanding, positive cash is trapped and
   released when the test is next passed, or at the end of the concession.
5. Distributions to equity.

Check C15 confirms that every rupee is accounted for, every year.

## 12. Metrics (README §9.12-9.13)

* `DSCR[k] = CFADS[k] / DS[k]` where `DS > 0`. Minimum and average are taken over those years only.
* `LLCR[k] = [Σ_{j=k..last repayment} CFADS[j]/(1+r)^(j−k+1) + DSRA balance] / Open[k]`.
* `PLCR[k]` is the same to the concession end. `ICR[k] = CFADS[k] / Interest[k]`.
* **Project IRR**: `−Capex[t]` (excluding IDC and fees) during construction, `EBITDA − unlevered tax` in
  operations. **After grant**: capex net of the grant. **Equity IRR**: `−equity contributions`, then
  distributions minus sponsor support.
* `NPV(i) = Σ CF[t]/(1+i)^t` for t = 1..N, valued at financial close like Excel's `NPV()`.
  `numpy_financial.npv` discounts its first value at t = 0, so it equals `(1+i) ×` this NPV.
* **IRR solver**: evaluates NPV on 6,001 rates from −99% to +1,000% (log-spaced in `1+i`), bisects
  every sign change to 10⁻¹³, and reports a value only if exactly one root exists. Otherwise it
  returns `None` with the status `no_sign_change`, `multiple` (all roots listed) or `no_root`. Each IRR
  is cross-checked against `numpy_financial.irr` (C09) and must give `|NPV| < 0.001` (C08).
* **Payback**: first model year in which cumulative equity cash flow is ≥ 0.

## 13. Scenarios and sensitivity (README §10)

* `scenarios.yaml` holds overrides; `overrides_for(type)` merges common overrides with `by_type`
  ones. Each run is `deep_merge(base, overrides)` on a new dict, so the base is never modified (tested).
* **Two-way table**: shortfall × overrun grid of minimum DSCR (or Equity IRR).
* **Tornado**: each listed input × (1 ± 10%), one at a time; ranked by Equity IRR range; the minimum
  DSCR effect is shown alongside. The variables are listed per project type in `scenarios.yaml`.
* **Break-even shortfall**: coarse scan from 0 to 95%, then bisection to 10⁻⁷ inside the first
  bracket. Results are `found` (with the binding year), `not_reached`, `already_breached` (below the
  threshold with no shortfall) or `not_applicable` (HAM). The same search finds the shortfall at which
  Equity IRR equals the hurdle.
* **Profile comparison**: the same inputs run with each of the four profiles.

## 14. Validation

Automated checks run on every model result (`checks.py`, shown on the dashboard and in Excel):

| ID | Check | Kind |
|---|---|---|
| C01 | Sources = uses every year (< 0.001) | integrity |
| C02 | Phasing sums to 100% (< 10⁻⁹) | integrity |
| C03 | Debt / (TPC − grant − equity-funded overrun) = gearing (< 10⁻⁴) | integrity |
| C04 | IDC closed form = iteration (< 10⁻⁶) | integrity |
| C05 | Debt balance never negative | integrity |
| C06 | Σ principal + balance outstanding = debt at COD (< 0.001) | integrity |
| C07 | Debt repaid at contractual maturity (< 0.001) | integrity (warn if the tenor exceeds the concession) |
| C08 | NPV at Project / Equity IRR ≈ 0 (< 0.001) | integrity |
| C09 | IRR = numpy-financial (< 10⁻⁶) | integrity |
| C10 | DSCR ≥ 1.00x in every debt-service year | financial warning |
| C11 | Debt maturity within the concession (mor + n ≤ To) | financial warning |
| C12 | HAM: traffic shortfall leaves revenue unchanged (toll/metro: shortfall never raises revenue) | integrity |
| C13 | HAM: cost overrun leaves revenue unchanged | integrity |
| C14 | PV of debt service at r = debt at COD | integrity |
| C15 | Waterfall balances every year | integrity |
| C16 | Reserve balances never negative | integrity |
| C17 | Depreciation totals the depreciable cost | integrity |
| C18 | Tax and tax losses never negative | integrity |
| C19 | No principal during the moratorium | integrity |
| C20 | Repayment profile shape (annuity flat; equal constant; structured = D × s; sculpted DSCR flat) | integrity |
| C21-C24 | Minimum DSCR, LLCR, Equity IRR hurdle, sponsor support | financial warnings |
| C25 | DSCR-based sizing really achieves the target | integrity |
| C26 | A delay does not extend a fixed concession | integrity |

Unit tests (`tests/`, 197 tests) cover every README §12.2 degenerate case:
- zero interest, no debt, flat annuity;
- the annuity and equal-principal identities;
- sculpting at target, the PV identity, and constant revenue;
- the worked example and the known IRR.

They also cover README §11.1–§11.5 and the hand check, input validation, scenario isolation, reserves
and the Excel export. The hand check (`checks.hand_check`, written to `validation/hand_check.*`)
recomputes construction year 2, the annuity payment, op year 1, the first major-maintenance year and
the final repayment year from the inputs with scalar formulas.
