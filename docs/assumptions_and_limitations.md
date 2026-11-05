# Assumptions, README discrepancies and limitations

## 1. Verification of the README worked example

Before any engine code was written, Sections 11.1-11.5 were recomputed from their stated assumptions
in a separate pure-Python script, with no numpy and no model code. The built model was then checked
against both (`tests/test_worked_example.py`, `tests/test_scenarios.py`). The README is internally
consistent: every figure reproduces within its stated ±0.01, apart from the two rounding slips in §2.

| Metric | README | Model | Status |
|---|---:|---:|---|
| Total Project Cost | 1,113.08 | 1,113.0751 | ✓ |
| IDC | 113.08 | 113.0751 | ✓ |
| Debt at COD | 779.15 | 779.1525 | ✓ |
| Equity | 333.92 | 333.9225 | ✓ |
| Annuity debt service | 102.44 | 102.4381 | ✓ |
| Minimum DSCR (op year 1) | 1.26x | 1.2585x | ✓ |
| Average DSCR | 2.11x | 2.1058x | ✓ |
| LLCR at COD | 1.91x | 1.9112x (PV of CFADS 1,489.13) | ✓ |
| Project IRR | 13.94% | 13.9440% | ✓ |
| Equity IRR | 20.02% | 20.0199% | ✓ |
| Tail | 2 years | 2 years | ✓ |
| Equal principal: min DSCR / Equity IRR | 0.99x / 18.77% | 0.9928x / 18.7710% | ✓ |
| Traffic −10%: min / avg / LLCR / PIRR / EIRR | 1.11 / 1.89 / 1.72 / 12.48% / 16.98% | 1.1131 / 1.8911 / 1.7209 / 12.480% / 16.980% | ✓ |
| Traffic −20% | 0.97 / 1.68 / 1.53 / 10.90% / 13.60% | 0.9678 / 1.6765 / 1.5268 / 10.901% / 13.604% | ✓ |
| Cost +10% (debt 857.07) | 1.14 / 1.94 / 1.76 / 12.81% / 17.68% | 1.1441 / 1.9403 / 1.7642 / 12.813% / 17.681% | ✓ |
| Cost +20% | 1.05 / 1.80 / 1.64 / 11.82% / 15.59% | 1.0488 / 1.8023 / 1.6403 / 11.819% / 15.586% | ✓ |
| Combined (−20% traffic, +20% cost) | 0.81 / **1.45** / 1.31 / 9.00% / 9.44% | 0.8065 / **1.4445** / 1.3097 / 8.998% / 9.442% | ✓ (rounding, see §2.1) |
| Break-even traffic shortfall | ≈ 17.8% | 17.78% (= 1 − 122.44/148.92) | ✓ |
| Every Table 11.1 / 11.2 cell and both IRR cash-flow series | | | ✓ within ±0.01 |
| Every hand check in §12.3 (37 items) | | | ✓ difference < 10⁻⁶ |

The tests pin these values, so a later code change that breaks one of them fails the suite.

## 2. Discrepancies and ambiguities in the README, and how they were resolved

### 2.1 Rounding slips (no change to the model)
* **Combined downside average DSCR.** The README gives 1.45; the exact value is 1.44455, which rounds
  to 1.44. This looks like double rounding (1.4445 → 1.445 → 1.45). It is within ±0.01, and
  `test_readme_rounding_discrepancies` pins the exact value.
* **Table 11.2, op-year-12 revenue.** The README gives 373.35; the exact value is
  24,000 × 1.04¹¹ × 200 × 1.03¹¹ × 365 / 10⁷ = 373.34497, which rounds to 373.34. Also within ±0.01.

### 2.2 Traffic −20% also breaches 1.00x in op year 5
README §11.5 says "DSCR < 1 → shortfall in yr 1". The model also finds DSCR = 0.971 in **op year 5**,
the resurfacing year. The minimum (0.968, year 1) is as stated; the README just does not mention the
second breach. At −30% the resurfacing year becomes the binding one (0.746 in op year 5). This
matters for the report: a DSRA sized only for the ramp-up year would also be drawn in year 5.

### 2.3 MMRA position: README §9.8 vs §9.11
§9.8 puts the MMRA movement *inside* CFADS; the §9.11 waterfall lists it *below* debt service. They
give different DSCRs in maintenance years. Both are implemented (`reserves.mmra_position`). The default
is `after_debt_service`, the §9.11 waterfall order the brief asks for: it smooths equity distributions
but leaves the DSCR dip. `in_cfads` pre-funds the resurfacing inside CFADS and lifts the year-5 DSCR.
The MMRA is off in all base cases.

### 2.4 MMRA contribution formula
§9.10 gives `contribution = next MMR / years remaining`. Applied every year this does not accumulate to
the MMR cost, because the denominator changes. The model uses
`(next MMR − balance) / years remaining`, which reaches exactly the MMR cost in its year (tested).

### 2.5 Grant formula and cost overruns
§9.3 writes `Grant[t] = grant_pct × Capex[t]`, so an overrun would raise the grant. Under the VGF
scheme the grant is fixed at award (it is the bid variable), so a cost overrun is not grant-funded.
The model computes the grant on capex *before* overrun (`grant_covers_overrun: false`). Setting it
to `true` reproduces the literal formula. The input table calls the base "% of hard capex", while the
formula uses `Capex[t]` including contingency and pre-operative costs; the model follows the formula.
The toll base has no grant, so no README number is affected.

### 2.6 Construction delays: whole years, fixed end date, indexation
* README §8.1 lists 0.5-2 years as typical. With annual periods only whole years can be modelled, so
  a fractional delay is rejected with an explanation rather than rounded.
* The concession end stays fixed (README §9.1), so operations shrink. If the delay pushes loan maturity
  past the end (for example a 3-year delay with a 15-year tenor), the model reports the unpaid balance
  (₹103.96 Cr) and warns; it never extends the concession.
* **Indexation during the delay is ambiguous.** The README formulas index traffic, tolls and O&M from
  the actual COD (exponent k − 1), which freezes traffic growth and toll indexation during the delay.
  That is the default (`indexation_basis: cod`). In reality traffic and WPI-linked tolls follow the
  calendar, so `calendar` is offered. The choice changes the delay result:

  | Delay 1 year | IDC | Debt | Min DSCR | Project IRR | Equity IRR |
  |---|---:|---:|---:|---:|---:|
  | Base, no delay | 113.08 | 779.15 | 1.2585 | 13.94% | 20.02% |
  | `cod` (README formulas, default) | 154.29 | 808.01 | 1.2136 | 12.66% | 17.53% |
  | `calendar` | 154.29 | 808.01 | 1.3040 | 13.49% | 19.23% |

  Under `calendar`, the delayed project opens to a year's more traffic and a higher toll, so its first
  DSCR exceeds the base case even though returns fall.
* The delayed spend is re-phased by stretching the cumulative S-curve (no README rule exists);
  `stress.delay_phasing` can override it.

### 2.7 HAM: "Tc + 15" with a fixed end date
A HAM concession pays 30 semi-annual instalments after COD. If the end date were fixed, a delay would
push instalments past the concession end. The HAM base therefore ties operations to COD
(`concession_end_fixed: false`): a delay moves the end date and all 15 years of annuities are kept.
This reflects the instalment structure and should be confirmed against the applicable Model
Concession Agreement. With `true`, the model drops the out-of-concession instalments and says how
much revenue they carried.

### 2.8 Level annuity is not a good default for HAM
README §9.9 lists level annuity as suited to "annuity and HAM projects". In this HAM case, HAM income
falls over time (interest on a reducing annuity balance) and there is periodic renewal in op year 12.
A level annuity under gearing-only sizing gives a minimum DSCR of **0.61x** in op year 12; equal
principal gives 0.89x. The HAM base therefore uses a **sculpted** profile, which with DSCR sizing keeps
DSCR at 1.45x and Equity IRR at 16.5%. Under DSCR sizing the other profiles get less debt and
12-13% Equity IRR.

### 2.9 Road capacity cap and leakage
§9.5.1 applies the capacity cap after leakage, i.e. to paying vehicles. Exempt vehicles also occupy
the road, so the model caps vehicles *on the road* and then applies leakage. The two agree when
leakage is zero, as in the base case.

### 2.10 Sculpting the toll base: negative principal in two years
Sculpting the toll base produces debt service below interest in op years 1 (ramp-up) and 5
(resurfacing): the README §9.9 pitfall. By default those years are floored at interest-only, so their
DSCR (1.655x, 1.917x) is below the sculpted 1.963x elsewhere, and the warning says so. The `capitalise`
rule instead capitalises 12.82 of interest and gives a flat 1.934x.

### 2.11 DSCR in moratorium years
README §9.12 says both "where DS > 0" and "min over repayment years". Interest-only moratorium years
have DS > 0 and are lender test periods, so they are included in the minimum and average. In the metro
base the minimum DSCR (1.32x) falls in moratorium year 1.

### 2.12 Interest-rate scenario
README §10.1 writes `rate_p100bp: { r: 0.11 }`, an absolute rate. Metro (9.0%) and HAM (8.75%) have
different base rates, so the scenario is a +100 bp shift (`stress.rate_shock: 0.01`). For the toll
base this is identical to r = 11%.

### 2.13 Dashboard chart 1 is two aligned panels, not a dual axis
README §14.2 draws DSCR on a secondary y-axis over the CFADS and debt-service bars. Two y-scales on one
plot imply a visual relationship that depends only on how the axes are scaled, so the dashboard puts
DSCR in an aligned panel underneath, sharing the year axis. The covenant and 1.00x lines appear in the
DSCR panel.

### 2.14 Smaller items
* The planned folder tree (README §6) lists `docs/report/` and `validation/hand_check_scans/`. The build
  follows the brief's tree (`docs/model_methodology.md`, `docs/assumptions_and_limitations.md`,
  `validation/hand_check.md`). A report and scans are still to be produced.
* README §6 has a stray code-fence language tag (```` ```4 ````); it was corrected to ```` ``` ````.
* §7.2 orders funding before revenue. HAM construction support is revenue-side data that funding needs,
  so revenue is computed first; neither depends on funding, so results are unchanged.

## 3. Modelling assumptions

**Periods and timing.** Annual periods; end-of-year cash flows except the mid-year IDC convention.
Semi-annual HAM instalments are summed into their year, so the first instalment of each year is
treated as received six months late (slightly conservative).

**Prices.** Nominal. Capex escalation and HAM PIM follow the model year; operating escalation follows
the indexation basis.

**Funding.**
- One senior debt tranche at one fixed all-in rate.
- No commitment fees, refinancing, mezzanine or shareholder loans.
- The upfront fee is paid in year 1 on the debt at COD.
- In equity-first mode the transition-year draw uses the mid-year convention, which slightly
  overstates IDC.

**Tax.** A modelling convention, not a statement of Indian tax law:
- The rate is 25.17% (s.115BAA, including surcharge and cess). MAT, s.80-IA holidays, deferred tax and
  depreciation block rates are not modelled.
- Depreciation is straight-line over the operating period. The README's Ind AS revenue-based
  amortisation and the Income-tax Act WDV block method are not modelled.
- Losses carry forward without limit by default; an N-year limit is available. Business losses
  (8 years under s.72) and unabsorbed depreciation (unlimited) are not separated.
- The grant reduces the depreciable cost (configurable), in line with the usual treatment of
  asset-related government grants.

**HAM.**
- The SPV is modelled like an asset owner (fixed asset, depreciation, revenue as received). In
  practice HAM concessionaires usually account for a financial asset under Ind AS 115 / Appendix D;
  the cash flows are the same, but tax timing could differ.
- The annuity interest rate is fixed. In the MCA it is linked to a benchmark rate, so a general rise
  in rates is partly passed through; the rate +100 bp scenario therefore represents a widening spread
  between the loan rate and the annuity rate.
- PIM is a single compound index.

**Waterfall.**
- Distributions equal cash available for equity. The company-law "dividend trap" (dividends limited
  to accounting profits) is not modelled.
- Reserves earn no interest.
- Trapped lock-up cash is released when the DSCR test is next passed, or at the end of the concession.
- Terminal value at handback is zero.

**Out of scope (README §2).** Monthly or quarterly periods, working capital, refinancing, multiple
tranches, foreign exchange, and a full balance sheet.

## 4. Metro and HAM base cases are illustrative calibrations

README §8.5 and §8.6 give revenue examples but no cost or financing for metro and HAM. The values
below are assumptions chosen to give a realistic, internally consistent case. They are **not** data
from a real project; replace them with project data (README Phase 12) before drawing real-world
conclusions.

* **Metro.**
  - Revenue inputs are taken from README §8.5: 3,00,000 riders/day, ₹30 fare, +10% every 3 years,
    50/65/80/90/100% ramp-up and 15% non-fare revenue.
  - Assumed: capex ₹2,200 Cr in today's prices (about ₹220 Cr/km for 10 km), 5-year build, 35-year
    concession and 40% VGF.
  - Assumed financing: 60% gearing at 9.0%, an 18-year rising structured repayment after a 2-year
    moratorium, a 6-month DSRA funded at COD and O&M of ₹60 Cr.
  - Result: minimum DSCR 1.32x and Equity IRR 19.9% with the grant. With no grant they fall to
    0.79x and 13.4%: fare-box revenue alone cannot carry the capex, which is the README teaching
    point.
* **HAM.**
  - Contract inputs: BPC ₹1,000 Cr with the actual EPC cost at 90% of BPC (the bid margin); 40%
    construction support; 30 semi-annual instalments; 8.75% annuity interest; ₹12 Cr O&M payment;
    5% PIM.
  - Assumed financing: loan at 8.75%; sculpted repayment over 13 years; debt sized at the smaller of a
    75% gearing cap and a 1.20x DSCR.
  - Result: minimum DSCR 1.45x and Equity IRR 16.5% against a 14% hurdle.
  - Traffic shortfalls change nothing. A 20% cost overrun cuts Equity IRR to 3.0% because payments
    are fixed by the BPC; DSCR sizing then caps the debt so the minimum DSCR stays at exactly 1.20x.

## 5. Possible extensions

- Semi-annual periods (to match HAM payments and bank loans).
- Multiple debt tranches and a commitment fee.
- Lender's-case (P90) debt sizing alongside the sponsor's (P50) case.
- Per-vehicle-class toll revenue.
- Working capital.
- Accounting for the dividend trap.
- Full Income-tax Act depreciation blocks.
- Calibration to a real NHAI or metro project.
