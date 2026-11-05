# PPP / Infrastructure Project Financial Model

**Course project, Topic 9.** A tool that models how a Public-Private Partnership (PPP) infrastructure project (toll road, metro line or Hybrid Annuity Model road) is financed. It covers the debt-equity structure, interest during construction (IDC), revenue ramp-up, lender metrics (DSCR, LLCR), Project IRR and Equity IRR, with scenarios for traffic shortfall and cost overrun.

This README is the **complete build guide, from an empty folder to a finished, validated model**. It explains the concepts, every formula, the order in which to build things, how to test them, and how to check the results by hand.

## Running the model (built from this guide)

The model described below is implemented in this folder: the engine in `src/ppp_model/`, inputs in `config/`, the dashboard in `app/dashboard.py`, tests in `tests/` and the hand check in `validation/`.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
python -m pytest                          # 197 tests, including every number in Section 11
streamlit run app/dashboard.py            # interactive dashboard
python -m ppp_model run --type toll       # headline results in the terminal (also: metro, ham)
python -m ppp_model export --type toll    # Excel workbook in outputs/
python -m ppp_model charts --type toll    # the eight Section 14.3 report charts as PNG in outputs/charts/
python -m ppp_model hand-check            # validation/hand_check.xlsx and .md
```

The base toll case reproduces Section 11 within the stated ±0.01, and all integrity checks pass. Building it surfaced a few inconsistencies in this guide: two half-cent rounding slips, the §9.8 vs §9.11 MMRA position, grant treatment under cost overruns, and HAM delays. They are documented with the choice made in [`docs/assumptions_and_limitations.md`](docs/assumptions_and_limitations.md). Formulas as implemented are in [`docs/model_methodology.md`](docs/model_methodology.md), and the AI usage log is [`docs/ai_usage_log.md`](docs/ai_usage_log.md).

---

## Table of contents

1. [Project brief](#1-project-brief)
2. [What we are building](#2-what-we-are-building)
3. [PPP finance basics](#3-ppp-finance-basics)
4. [Glossary](#4-glossary)
5. [Modelling conventions](#5-modelling-conventions)
6. [Technology choice and folder structure](#6-technology-choice-and-folder-structure)
7. [Model architecture](#7-model-architecture)
8. [Inputs (assumption sheet)](#8-inputs-assumption-sheet)
9. [Calculation logic, module by module](#9-calculation-logic-module-by-module)
10. [Scenarios and sensitivity analysis](#10-scenarios-and-sensitivity-analysis)
11. [Worked example (the mini model)](#11-worked-example-the-mini-model)
12. [Validation plan (including the hand check)](#12-validation-plan-including-the-hand-check)
13. [Step-by-step build roadmap](#13-step-by-step-build-roadmap)
14. [Outputs and dashboard](#14-outputs-and-dashboard)
15. [Role of AI and the AI usage log](#15-role-of-ai-and-the-ai-usage-log)
16. [Common mistakes](#16-common-mistakes)
17. [Deliverables checklist](#17-deliverables-checklist)
18. [Open items to confirm with the instructor](#18-open-items-to-confirm-with-the-instructor)
19. [References](#19-references)

---

## 1. Project brief

| Item | Requirement |
|---|---|
| **Problem** | PPP projects such as toll roads, metro lines and Hybrid Annuity Model (HAM) projects depend on sound financial structuring. |
| **Tool to be developed** | Models the debt-equity structure, interest during construction, revenue ramp-up, DSCR, LLCR, Project IRR and Equity IRR, with scenarios for traffic shortfall and cost overrun. |
| **Role of AI** | Model architecture, debt schedule logic, scenario setup, explanation of lender metrics. |
| **Validation** | Verify the debt repayment schedule and DSCR for selected years by hand. |

---

## 2. What we are building

A **calculation engine** that takes one set of assumptions (an *input sheet*) and produces the project's full financial picture year by year:

```
Assumptions  ─►  Construction cost + funding + IDC  ─►  Revenue - costs - tax = CFADS
             ─►  Debt schedule  ─►  DSCR / LLCR  ─►  Project IRR / Equity IRR
             ─►  Repeat for every scenario  ─►  Comparison tables + charts
```

### Features (scope)

| # | Feature | Required by brief? |
|---|---|---|
| 1 | Timeline: construction period, operations period, concession period | Yes (foundation) |
| 2 | Capital cost with phasing, escalation, contingency and overrun | Yes (cost overrun scenario) |
| 3 | Debt-equity structure (gearing), grant/VGF, sources = uses | **Yes** |
| 4 | Interest During Construction (IDC), capitalised, with the circular reference solved | **Yes** |
| 5 | Revenue with ramp-up for **Toll**, **Metro** and **HAM** | **Yes** |
| 6 | O&M, periodic major maintenance, depreciation, tax | Yes (needed for CFADS) |
| 7 | Debt schedule: equal principal, level annuity, structured %, sculpted | **Yes** |
| 8 | Cash flow waterfall and equity distributions | Yes (needed for Equity IRR) |
| 9 | Lender metrics: **DSCR**, **LLCR** (and PLCR, ICR as extras) | **Yes** |
| 10 | Returns: **Project IRR**, **Equity IRR**, NPV, payback | **Yes** |
| 11 | Scenarios: **traffic shortfall**, **cost overrun**, delay, interest-rate shock, combined | **Yes** |
| 12 | Sensitivity tables, tornado chart, break-even traffic | Extra credit |
| 13 | Automated integrity checks plus a **hand-calculation sheet** | **Yes** (validation) |
| 14 | Interactive dashboard plus Excel export | Presentation |

### Out of scope (state this in the report)

Monthly or quarterly periods (we use annual periods; semi-annual is noted as an extension), detailed working capital, refinancing, multiple debt tranches, foreign-exchange risk, and a full balance sheet. Each is listed as a possible extension in the report.

---

## 3. PPP finance basics

### 3.1 What a PPP is

In a PPP, a government authority (for example NHAI or a metro rail corporation) grants a private company the right to **design, build, finance and operate** an asset for a fixed **concession period**. The private side raises the money, builds the asset, earns revenue from it, and hands it back at the end.

The private sponsor creates a separate company for the project, the **SPV (Special Purpose Vehicle)**, also called the *Concessionaire*. Lenders lend to the SPV, not to the sponsor. They are repaid **only from the project's own cash flows**. That is why it is called *project finance*, and it is why lenders care so much about DSCR and LLCR.

```
        Government Authority (NHAI / Metro Corporation / State)
           │   Concession Agreement: rights, obligations, period
           │   (grant / VGF / HAM construction support and annuities)
           ▼
Sponsors ──equity──►  SPV (Concessionaire)  ◄──senior debt── Lenders (banks, FIs)
                       │                ▲
        EPC contract   │                │  tolls / fares / annuity payments
                       ▼                │
           EPC contractor (builds)   Users / Authority
           O&M contractor (operates)
```

### 3.2 Project life cycle

```
 Financial   Appointed                       COD                                  Concession
 close       date                            (Commercial Operation Date)          end / handback
   │───────────│──── Construction (Tc yrs) ───│──────── Operations (To yrs) ─────────│
               │ Capex spent                  │ Revenue starts (with ramp-up)        │
               │ Debt + equity drawn          │ O&M, maintenance, tax                │
               │ Interest capitalised (IDC)   │ Debt repaid from CFADS               │
               │ No revenue                   │ Dividends to equity                  │
```

### 3.3 The three project types

| Feature | **BOT-Toll** (road) | **Metro** (PPP) | **HAM** (Hybrid Annuity Model) |
|---|---|---|---|
| Revenue source | Tolls paid by users | Fares plus non-fare revenue (advertising, property, parking) | Payments from the Authority (annuities, interest, O&M) |
| Who bears traffic risk | **SPV** | **SPV** (mostly) | **Authority** (SPV has none) |
| Government support | Viability Gap Funding (VGF) grant, if needed | Large VGF or grant usually needed | **40% of Bid Project Cost** paid during construction |
| Main risks to SPV | Traffic shortfall, cost overrun, delay | Ridership shortfall, cost overrun, delay | Cost overrun, delay, interest-rate spread, O&M cost |
| Typical lender min DSCR (indicative) | 1.20x to 1.30x | 1.25x to 1.35x | 1.10x to 1.20x |
| What the "traffic shortfall" scenario does | Cuts toll revenue | Cuts fare revenue | **No effect** on revenue (an important teaching point) |

**Why HAM exists:** many Indian BOT-Toll projects awarded around 2008 to 2013 became financially stressed because actual traffic fell short of forecasts, and because land-acquisition delays caused cost overruns. In 2016 the government introduced HAM to share the risk. The Authority funds 40% of the cost during construction and pays the rest back as annuities, so the SPV carries **no traffic risk**. Your model can show this directly: run "traffic -20%" on a toll project and on a HAM project and compare.

### 3.4 Why the structure matters

* **Too much debt:** debt service exceeds cash flow and the project defaults (DSCR < 1).
* **Too little debt:** equity has to put in more money and Equity IRR falls below what investors require.
* **Wrong repayment shape:** revenue ramps up slowly, so flat or front-loaded repayments squeeze the early years (Section 11 shows this).

The tool helps find a structure that both lenders (DSCR, LLCR) and equity (Equity IRR) accept, and shows how that structure holds up under stress.

---

## 4. Glossary

| Term | Meaning |
|---|---|
| **TPC** | Total Project Cost = hard cost + escalation + contingency + pre-operative costs + financing fees + **IDC** |
| **Hard cost / EPC cost** | Construction contract cost |
| **IDC** | Interest During Construction. Interest on loans drawn during construction. It cannot be paid (there is no revenue yet), so it is *capitalised*: added to project cost and funded by more debt and equity. |
| **Gearing (D:E)** | Share of funding from debt versus equity, for example 70:30 |
| **VGF** | Viability Gap Funding, a capital grant from government (in India, up to 20% of TPC from the Centre plus up to 20% from the sponsoring authority under the standard scheme) |
| **BPC** | Bid Project Cost (HAM). The cost quoted by the bidder, which the Authority's payments are based on. |
| **COD** | Commercial Operation Date, when revenue starts |
| **Ramp-up** | Early years of operation when traffic or ridership is below its "mature" level while users adopt the new facility |
| **AADT** | Annual Average Daily Traffic (vehicles per day) |
| **PCU** | Passenger Car Unit. A truck counts as several PCUs, which lets mixed traffic be expressed in one unit. |
| **O&M** | Operations and maintenance cost |
| **MMR** | Major maintenance or periodic renewal (for example road resurfacing every 5 years) |
| **EBITDA** | Revenue - operating costs (before interest, tax, depreciation) |
| **CFADS** | **Cash Flow Available for Debt Service** = Revenue - O&M - MMR - tax (± working capital and reserve movements) |
| **Debt service (DS)** | Interest + principal repayment due in a period |
| **DSCR** | Debt Service Coverage Ratio = CFADS / DS for one period |
| **LLCR** | Loan Life Coverage Ratio = PV of CFADS over the remaining loan life / debt outstanding |
| **PLCR** | Project Life Coverage Ratio = PV of CFADS over the remaining *concession* / debt outstanding |
| **ICR** | Interest Cover Ratio = CFADS / interest |
| **Moratorium (grace period)** | Years after COD when only interest is paid, no principal |
| **Tenor** | Number of years over which the loan is repaid |
| **Sculpting** | Shaping principal repayments so that DSCR stays at a target level every year |
| **DSRA** | Debt Service Reserve Account. Cash set aside (usually 6 months of DS) to protect lenders. |
| **MMRA** | Major Maintenance Reserve Account |
| **Waterfall** | The order in which cash is paid out: O&M, then tax, then lenders, then reserves, then equity |
| **Project IRR** | IRR of the project's cash flows before financing (as if 100% equity funded) |
| **Equity IRR** | IRR of the sponsor's cash flows: equity put in versus dividends received |
| **Tail** | Years between final loan repayment and the end of the concession (a safety buffer for lenders) |
| **Lock-up** | A rule that stops dividends if DSCR falls below a threshold |
| **Circularity** | A formula that depends on its own result (IDC, upfront fees, sculpting). It must be solved by iteration. |
| **₹ crore (Cr)** | 1 crore = 10,000,000 = 10^7 rupees. All money in this model is in ₹ crore. |

---

## 5. Modelling conventions

Set these rules on day 1 and follow them everywhere. Most model bugs come from breaking one of them.

| Convention | Rule used in this model |
|---|---|
| **Currency and unit** | ₹ crore everywhere. Traffic is in vehicles or PCU per day; rates are in ₹ per trip. Convert with `/ 1e7`. |
| **Period** | **Annual.** Model year `t = 1 … N`, with `N = Tc + To`. |
| **Operating year index** | `k = t − Tc` (k = 1 is the first year after COD) |
| **Cash flow timing** | All cash flows happen at the **end** of the year, except construction drawdowns, which are assumed to be spread evenly through the year (**mid-year convention**) for IDC. |
| **Prices** | **Nominal** (inflation included through escalation rates) |
| **Signs** | In IRR arrays: money *out* of the investor is negative, money *in* is positive |
| **Interest** | Calculated on the **opening** balance of each year (plus half the year's drawdown during construction) |
| **Inputs vs calculations** | No hard-coded numbers inside calculation code. Every number lives in the YAML input file. |
| **One formula per row** | Each line item (for example "interest") uses the same formula in every year (Excel rule: one formula copied across) |
| **Flags** | Use 0/1 flags (`is_construction`, `is_operation`, `is_repayment`) and multiply by them, instead of writing `if` statements everywhere |

---

## 6. Technology choice and folder structure

### Recommended stack

| Layer | Choice | Why |
|---|---|---|
| Calculation engine | **Python 3.11+** with `numpy` and `pandas` | Transparent, testable and version-controlled. Each formula is written once and reused for every scenario. |
| Inputs | **YAML** files (`config/`) | Human-readable. Each scenario is a small file that overrides a few base values. |
| Financial functions | Own IRR/NPV functions, cross-checked with `numpy-financial` | You understand the maths, and the cross-check catches bugs. |
| Tests | `pytest` | Automated validation that reruns on every change |
| Dashboard | **Streamlit** with `plotly` | Interactive sliders, scenario switching and charts in the browser with very little code |
| Export | `openpyxl` / `xlsxwriter` to **Excel** | Examiners and lenders read Excel. The hand check is easy to do beside it. |

> **Excel-only alternative:** every formula in this README is written so it can also be built directly in Excel. Section 13.2 maps the modules to Excel sheets. If the course requires Excel, follow the same logic and the same build order.

### Planned folder structure

```
725 PROJECT/
├── README.md                  ← this file
├── requirements.txt           ← Python packages
├── config/
│   ├── base_toll.yaml         ← base-case inputs, toll road (= worked example)
│   ├── base_metro.yaml        ← base-case inputs, metro
│   ├── base_ham.yaml          ← base-case inputs, HAM
│   └── scenarios.yaml         ← scenario overrides (traffic -10/-20/-30%, cost +10/+20%, ...)
├── src/ppp_model/
│   ├── __init__.py
│   ├── inputs.py              ← load YAML, validate, dataclasses
│   ├── timeline.py            ← years, construction/operation flags
│   ├── capex.py               ← cost, phasing, escalation, contingency, overrun
│   ├── funding.py             ← sources & uses, gearing, grant, IDC (iterative solve)
│   ├── revenue.py             ← toll / metro / HAM revenue with ramp-up
│   ├── opex.py                ← O&M, major maintenance, concession fee
│   ├── tax.py                 ← depreciation, tax with loss carry-forward
│   ├── debt.py                ← repayment profiles, moratorium, sculpting, sizing
│   ├── cashflow.py            ← CFADS, waterfall, reserves, equity distributions
│   ├── metrics.py             ← DSCR, LLCR, PLCR, ICR, IRR, NPV, payback
│   ├── scenarios.py           ← apply overrides, run all, sensitivity, break-even
│   ├── checks.py              ← integrity checks (sources=uses, debt repaid, ...)
│   ├── export.py              ← write results to Excel
│   └── model.py               ← run_model(inputs) → results (orchestrator)
├── app/
│   └── dashboard.py           ← Streamlit UI
├── tests/
│   ├── test_funding_idc.py
│   ├── test_debt.py
│   ├── test_metrics.py
│   └── test_worked_example.py ← model must reproduce Section 11 exactly
├── validation/
│   ├── hand_check.xlsx        ← independent hand / calculator verification
│   └── hand_check_scans/      ← photos of handwritten working (if required)
├── outputs/                   ← generated Excel files and charts (not hand-edited)
└── docs/
    ├── report/                ← final report
    └── ai_usage_log.md        ← record of how AI was used (Section 15)
```

### `requirements.txt` (to create in Phase 0)

```
numpy
pandas
numpy-financial
pyyaml
openpyxl
xlsxwriter
matplotlib
plotly
streamlit
pytest
```

---

## 7. Model architecture

### 7.1 Data flow

```
                    ┌──────────────────────────────────────┐
                    │  INPUTS (config/*.yaml)              │
                    │  base case  +  scenario overrides    │
                    └──────────────────┬───────────────────┘
                                       ▼
 ┌──────────────┐   ┌──────────────────────────┐   ┌──────────────────────────────┐
 │ 1 Timeline   │──►│ 2 Capex (cost, phasing,  │──►│ 3 Funding + IDC              │
 │   & flags    │   │   escalation, overrun)   │   │   (iterative: IDC ⇄ debt)    │
 └──────────────┘   └──────────────────────────┘   └───────────────┬──────────────┘
                                                                   │ debt at COD, equity in
 ┌──────────────┐   ┌──────────────────────────┐   ┌───────────────▼──────────────┐
 │ 4 Revenue    │──►│ 5 O&M + major maint.     │──►│ 6 Debt schedule ⇄ 7 Tax      │
 │  (toll/metro │   │   + concession fee       │   │          ▼                   │
 │   /HAM,      │   └──────────────────────────┘   │       8 CFADS                │
 │   ramp-up)   │                                  └───────────────┬──────────────┘
 └──────────────┘                                                  ▼
                                               ┌────────────────────────────────────┐
                                               │ 9 Waterfall: DS → reserves → equity│
                                               └──────────────────┬─────────────────┘
                                                                  ▼
                                ┌────────────────────────────────────────────────────┐
                                │ 10 Metrics: DSCR, LLCR, PLCR, Project IRR,         │
                                │    Equity IRR, NPV  ──►  checks, dashboard, Excel  │
                                └────────────────────────────────────────────────────┘
    11 Scenario engine: re-runs steps 1-10 for every scenario and collects the metrics
```

### 7.2 Calculation order

Calculate the modules in this order. Each one needs only the results of the modules before it:

1. Timeline → 2. Capex → 3. Funding and IDC → 4. Revenue → 5. Opex → 6/7/8. Debt, tax and CFADS → 9. Waterfall → 10. Metrics → 11. Scenarios.

### 7.3 Circular references and how to break them

A circularity is a loop such as "A needs B, and B needs A". The model has four:

| Loop | Why it is circular | How to solve it |
|---|---|---|
| **IDC ⇄ debt** | IDC depends on debt drawn, and debt drawn depends on project cost, which includes IDC | Closed-form formula (Section 9.4), or a fixed-point iteration |
| **Upfront fee ⇄ debt** | Fee = % × debt, and the fee is part of the cost funded by debt | Same iteration as IDC |
| **Sculpting ⇄ tax** | Sculpted debt service depends on CFADS. CFADS depends on tax. Tax depends on interest, and interest depends on the debt schedule. | Iterate until CFADS stops changing |
| **DSRA funded at COD ⇄ debt** | The initial DSRA balance is part of cost, and depends on debt service | Iterate |

**General iteration pattern (Python):**

```python
guess = 0.0
for i in range(100):
    result = compute_everything(guess)       # uses the guess for the circular item
    new_guess = result.circular_item
    if abs(new_guess - guess) < 1e-8:        # converged
        break
    guess = new_guess
else:
    raise RuntimeError("Circularity did not converge")
```

**In Excel:** either switch on *File → Options → Formulas → Enable iterative calculation*, or (preferred) use a "copy-paste" macro that pastes the IDC values as numbers and repeats until the change is zero. Always add a **circuit-breaker** switch (an input of 1/0 that zeroes the circular term) so the workbook can recover if it errors.

---

## 8. Inputs (assumption sheet)

The **base case equals the worked example in Section 11**. Optional features are set to 0 or off, so the model can be tested against hand-calculated numbers before the features are switched on. The "typical" column gives realistic values to use once the core is validated.

### 8.1 General and timeline

| Input | Symbol | Base | Typical / options | Unit |
|---|---|---|---|---|
| Project type | `project_type` | `toll` | `toll`, `metro`, `ham` | n/a |
| First model year (label only) | | FY2026-27 | | n/a |
| Construction period | `Tc` | 3 | 2 to 4 (roads), 4 to 6 (metro) | years |
| Concession period (from appointed date) | `Tcon` | 20 | 15 to 30 (toll), 30+ (metro), Tc + 15 (HAM) | years |
| Operations period | `To = Tcon − Tc` | 17 | | years |
| Construction delay (scenario) | `delay_years` | 0 | 0.5 to 2 | years |

### 8.2 Capital cost

| Input | Symbol | Base | Typical | Unit |
|---|---|---|---|---|
| Base hard cost (today's prices) | `C0` | 1,000 | from the DPR | ₹ Cr |
| Phasing by construction year | `p_t` | 30%, 40%, 30% | must sum to 100% | % |
| Capex escalation | `e_c` | 0% | 4 to 6% | % p.a. |
| Contingency | `cont` | 0% | 3 to 5% of hard cost | % |
| Pre-operative expenses | `preop` | 0% | 1 to 3% of hard cost | % |
| Cost overrun (scenario) | `overrun` | 0% | +10%, +20%, +30% | % |
| Overrun funding | `overrun_mode` | `pro_rata` | `pro_rata` or `equity` | n/a |

### 8.3 Funding and debt

| Input | Symbol | Base | Typical | Unit |
|---|---|---|---|---|
| Gearing (debt share of funding need) | `g` | 70% | 70 to 80% | % |
| Grant / VGF (% of hard capex) | `grant_pct` | 0% | 0 to 40% (VGF), 40% of BPC (HAM) | % |
| Equity drawdown mode | `eq_mode` | `pro_rata` | `pro_rata` or `equity_first` | n/a |
| Interest rate (all-in) | `r` | 10.0% | 8.5 to 11% (Indian infra loans) | % p.a. |
| Drawdown timing factor | `m` | 0.5 (mid-year) | 0.5 | n/a |
| Upfront fee | `fee` | 0% | 0.5 to 1% of debt | % |
| Moratorium after COD | `mor` | 0 | 0 to 2 | years |
| Repayment tenor (after moratorium) | `n` | 15 | 12 to 20 | years |
| Repayment profile | `profile` | `annuity` | `equal`, `annuity`, `structured`, `sculpted` | n/a |
| Structured repayment % (if `structured`) | `s_k` | n/a | list summing to 100% | % |
| Target DSCR (sculpting / sizing) | `dscr_target` | 1.30 | 1.20 to 1.40 | x |
| DSRA size | `dsra_months` | 0 | 6 | months of DS |
| Dividend lock-up DSCR | `lockup` | off | 1.10 | x |

### 8.4 Revenue: toll road

| Input | Symbol | Base | Typical | Unit |
|---|---|---|---|---|
| Traffic at COD (mature level, before ramp-up) | `AADT0` | 24,000 | from the traffic study | PCU/day |
| Traffic growth | `g_tr` | 4% | 3 to 7% | % p.a. |
| Toll rate at COD | `rate0` | 200 | (₹/PCU-km) × length | ₹ per PCU-trip |
| Toll rate escalation | `e_toll` | 3% | ≈ 3% + 40% of WPI change (NH Fee Rules 2008) | % p.a. |
| Ramp-up factors (op years 1, 2, 3, …) | `R_k` | 85%, 95%, then 100% | 70 to 100% over 2 to 4 years | % |
| Leakage / exempt vehicles | `leak` | 0% | 3 to 8% | % |
| Road capacity cap | `cap` | off | e.g. 40,000 PCU/day (4-lane) | PCU/day |
| Days per year | | 365 | | days |
| Traffic shortfall (scenario) | `short` | 0% | -10%, -20%, -30% | % |

### 8.5 Revenue: metro (used when `project_type = metro`)

| Input | Base example | Unit |
|---|---|---|
| Daily ridership at maturity (at COD) | 3,00,000 | passengers/day |
| Ridership growth | 3% | % p.a. |
| Average fare | 30 | ₹ per trip |
| Fare revision | +10% every 3 years | n/a |
| Ramp-up factors | 50%, 65%, 80%, 90%, 100% | % |
| Non-fare revenue | 15% of fare revenue | % |
| Line capacity cap | from the rolling-stock plan | passengers/day |

### 8.6 Revenue: HAM (used when `project_type = ham`)

| Input | Base example | Unit |
|---|---|---|
| Bid Project Cost (BPC) | 1,000 | ₹ Cr |
| Construction support from the Authority | 40% of BPC, paid during construction | % |
| Annuity portion | 60% of BPC, paid after COD | % |
| Number of annuity instalments | 30 semi-annual (15 years) | n/a |
| Interest on the annuity balance | rate set in the Model Concession Agreement (check which version applies) | % p.a. |
| O&M payment (bid) | 10 in op year 1, indexed | ₹ Cr p.a. |
| Inflation index (Price Index Multiple) | 5% | % p.a. |

### 8.7 Operating costs, tax and valuation

| Input | Symbol | Base | Typical | Unit |
|---|---|---|---|---|
| Routine O&M in op year 1 | `OM0` | 20 | 1.5 to 3% of hard cost | ₹ Cr |
| O&M escalation | `e_om` | 5% | 5 to 6% | % p.a. |
| Major maintenance (op-year-1 prices) | `MMR0` | 50 | resurfacing cost | ₹ Cr |
| Major maintenance years | | op yrs 5, 10, 15 | every 5 to 6 years | n/a |
| Concession fee / premium to Authority | | 0 | % of revenue or fixed | n/a |
| Corporate tax rate | `tax` | 25.17% | 25.17% (Sec 115BAA) | % |
| Depreciation | | straight-line of capitalised cost over `To` | revenue-based amortisation (Ind AS) | n/a |
| Loss carry-forward | | unlimited | 8-year limit (Income Tax Act) | n/a |
| Project discount rate (for NPV) | | 12% | WACC | % |
| Equity hurdle rate | | 15% | 14 to 18% | % |

---

## 9. Calculation logic, module by module

Notation: `t` = model year, `k` = operating year, `[t]` = value in year t. The `Excel` lines show the same formula in spreadsheet form.

### 9.1 Timeline and flags

```
N               = Tc + To
is_constr[t]    = 1 if t ≤ Tc            else 0
is_op[t]        = 1 if t > Tc            else 0
k[t]            = t − Tc  (operating year number; ≤0 during construction)
is_repay[t]     = 1 if mor < k[t] ≤ mor + n   else 0
```

**Construction delay scenario:** increase `Tc` by the delay `d` but **keep the concession end date fixed** (this is how Indian concessions normally work: the period runs from the appointed date). The operating period then shrinks to `To − d`, so a delay costs revenue years *and* adds IDC.

### 9.2 Capital cost (capex)

```
Hard[t]   = C0 × p[t] × (1 + e_c)^(t − 1) × (1 + overrun)
Cont[t]   = cont  × Hard[t]
PreOp[t]  = preop × Hard[t]
Capex[t]  = Hard[t] + Cont[t] + PreOp[t]          (before IDC and fees)
```

Excel: `=C0 * p_t * (1+e_c)^(t-1) * (1+overrun)`

**Logic:** phasing spreads the cost over the construction years. Escalation turns today's prices into the prices of the year the money is actually spent. The overrun factor is the cost-overrun scenario lever.

### 9.3 Sources and uses, gearing, grant

```
USES[t]    = Capex[t] + Fees[t] + IDC[t] (+ initial DSRA funding at COD, optional)
Grant[t]   = grant_pct × Capex[t]                     (disbursed with construction)
Need[t]    = USES[t] − Grant[t]                       (funding gap for D + E)
Draw[t]    = g × Need[t]                              (pro-rata mode)
Equity[t]  = (1 − g) × Need[t]
SOURCES[t] = Draw[t] + Equity[t] + Grant[t]
CHECK:  SOURCES[t] − USES[t] = 0   in every year
```

**Equity-first mode** (lenders often require it, because sponsors then carry the first loss): equity funds everything until its total commitment `(1−g) × total Need` is spent, then debt takes over. This **reduces IDC**, because debt is drawn later. It is a good comparison to show in the report.

**Cost-overrun funding:**
* `pro_rata`: the overrun is funded 70:30 like the rest (lenders give a standby facility). Debt goes up, so debt service goes up and DSCR falls.
* `equity`: sponsors fund 100% of the overrun (common in practice). Debt is unchanged, so DSCR is unchanged, but Equity IRR falls sharply.

### 9.4 Interest During Construction (IDC)

**Logic.** During construction there is no revenue, so interest on the loan cannot be paid. It is **added to the loan and to project cost**: interest is funded by borrowing more.

With the mid-year convention, money drawn during year t earns interest for half the year:

```
IDC[t]       = r × ( Open[t] + m × Draw[t] )          m = 0.5
Draw[t]      = g × ( K[t] + IDC[t] )                  K[t] = Capex[t] + Fees[t] − Grant[t]
Close[t]     = Open[t] + Draw[t]
Open[t+1]    = Close[t]
```

**The circularity:** `IDC` needs `Draw`, and `Draw` needs `IDC`. Substitute one equation into the other and solve for IDC, which gives a **closed form**:

```
            r × Open[t]  +  m × r × g × K[t]
IDC[t] =  ─────────────────────────────────────
                   1 − m × r × g
```

Use this formula, and also implement the iteration (Section 7.3). Then **test that both give the same answer**: that test is a validation item in its own right.

**Debt at COD** = `Close[Tc]` = all drawdowns, including capitalised IDC. This is the amount repaid in operations.

**Variants to mention:** commitment fee on undrawn debt (`c% × (facility − drawn)`), and IDC on equity-first structures (lower).

### 9.5 Revenue with ramp-up

#### 9.5.1 Toll road

```
Traffic[k]  = AADT0 × (1 + g_tr)^(k−1) × R[k] × (1 − short) × (1 − leak)
Traffic[k]  = min(Traffic[k], cap)                      (if a capacity cap is used)
Rate[k]     = rate0 × (1 + e_toll)^(k−1)
Revenue[k]  = Traffic[k] × Rate[k] × 365 / 1e7          (₹ crore)
```

* **Ramp-up `R[k]`** captures users slowly switching to the new road, for example 85% → 95% → 100%. In practice it is the most uncertain number in the model, and it hits the years in which debt is largest.
* For several vehicle classes (car, LCV, bus, truck, multi-axle), run the formula per class with its own rate and growth and add them up. Keep that as an extension and use PCU in the base.

Excel: `=AADT0*(1+g_tr)^(k-1)*INDEX(Ramp,k)*(1-short)*(1-leak)*rate0*(1+e_toll)^(k-1)*365/1E7`

#### 9.5.2 Metro

```
Riders[k]    = min( Riders0 × (1 + g_r)^(k−1) × R[k] × (1 − short), capacity )
Fare[k]      = Fare0 × (1 + rev%)^floor((k−1)/rev_every)
FareRev[k]   = Riders[k] × Fare[k] × 365 / 1e7
NonFare[k]   = nfr% × FareRev[k]
Revenue[k]   = FareRev[k] + NonFare[k]
```

Metros usually need a long ramp-up (4 to 6 years) and a large grant. Fare-box revenue alone rarely covers capex, which you can show by running a metro case with `grant_pct = 0`.

#### 9.5.3 HAM (Hybrid Annuity Model)

The SPV is paid by the Authority, not by users:

```
During construction:
  ConstrSupport[t] = 40% × BPC × PIM[t] × (share of milestones achieved in year t)
  → treated as Grant[t] in Sources (reduces the D+E need)

After COD (semi-annual, aggregated to annual):
  A0              = 60% × BPC × PIM[COD]                    (annuity principal)
  AnnPrin[h]      = A0 / 30                                 (h = half-year 1..30)
  AnnInt[h]       = (i_ham / 2) × AnnBalance[h]             (interest on reducing balance)
  AnnBalance[h+1] = AnnBalance[h] − AnnPrin[h]
  OM_pay[k]       = OM_bid × PIM[k]
  Revenue[k]      = Σ(two half-years)(AnnPrin + AnnInt) + OM_pay[k]
```

**Key insights for the report:**
* Revenue does **not** depend on traffic, so the traffic-shortfall scenario has zero effect.
* Payments are based on **BPC**, not actual cost. A cost overrun raises debt and equity but **not** revenue, so it goes straight to equity returns and DSCR.
* The SPV's main remaining financial risk is the spread between its loan rate `r` and the annuity interest rate `i_ham`. Model it with the interest-rate scenario.

### 9.6 Operating costs

```
OM[k]    = OM0 × (1 + e_om)^(k−1)
MMR[k]   = MMR0 × (1 + e_om)^(k−1)   if k is a major-maintenance year, else 0
ConFee[k]= fee% × Revenue[k]   (or fixed premium escalating)
Opex[k]  = OM[k] + MMR[k] + ConFee[k]
EBITDA[k]= Revenue[k] − Opex[k]
```

MMR creates "lumpy" years. In the worked example, DSCR dips in op year 5 because of resurfacing. That is why lenders often require an **MMRA** that saves for MMR in advance (Section 9.10).

### 9.7 Depreciation and tax

```
Dep[k]         = CapitalisedCost / To                    (straight-line; CapitalisedCost = TPC)
PBT[k]         = EBITDA[k] − Dep[k] − Interest[k]        (profit before tax)
Taxable[k]     = PBT[k] − LossBF[k]
Tax[k]         = tax × max(0, Taxable[k])
LossBF[k+1]    = max(0, −Taxable[k])                     (loss carried forward)
```

**Logic:** interest and depreciation are tax-deductible, so early years usually show tax losses. Those losses are carried forward and reduce tax in later years. Tax depends on interest, so tax must be calculated *after* the debt schedule.

> **Unlevered tax** (used only for Project IRR): the same calculation but with `Interest = 0` and depreciation on capex excluding IDC. Project IRR must not benefit from the debt tax shield.

### 9.8 CFADS

```
CFADS[k] = Revenue[k] − OM[k] − MMR[k] − ConFee[k] − Tax[k]  (± ΔWorkingCapital ± MMRA movement)
```

CFADS is the single most important line in project finance. It is the cash that **can** be used to pay lenders. Everything lenders measure is CFADS divided by something.

### 9.9 Debt schedule

The core rows (every repayment profile uses these four):

```
Open[k]      = Close[k−1]                (Open[1] = Debt at COD)
Interest[k]  = r × Open[k]
Principal[k] = depends on profile (below)  × is_repay[k]
Close[k]     = Open[k] − Principal[k]
DS[k]        = Interest[k] + Principal[k]
```

During a moratorium (`k ≤ mor`), `Principal = 0`, so `DS = Interest` (interest is paid from CFADS, not capitalised).

#### Repayment profiles

| Profile | Principal formula | DS shape | When used |
|---|---|---|---|
| **Equal principal** (straight-line) | `P = D / n` | Highest at the start, falling | Simple; bad fit for ramp-up projects |
| **Level annuity** (mortgage-style) | `DS = D × r / (1 − (1+r)^−n)`, `P[k] = DS − Interest[k]` | Flat | Annuity and HAM projects; good default |
| **Structured / ballooning** | `P[k] = D × s[k]`, with `Σ s = 100%` | Rising, as set by the bank | Common in Indian bank loans |
| **Sculpted** | `DS[k] = CFADS[k] / DSCR_target`, `P[k] = DS[k] − Interest[k]` | Follows CFADS | Best fit: constant DSCR |

Excel annuity: `DS = PMT(r, n, -D)`; principal: `= PPMT(r, k-mor, n, -D)`; interest: `= IPMT(...)`.

#### Debt sizing (how much debt the project can carry)

Two limits apply, and the **smaller** one binds:

```
D_gearing = g × (TPC − Grant)                                   (gearing limit)
D_dscr    = Σ_{k=1..n} [ CFADS[k] / DSCR_target ] / (1 + r)^k    (DSCR / sculpting limit)
D         = min(D_gearing, D_dscr)
```

**Why the PV formula works:** for any loan where interest is charged on the opening balance at rate `r`, the PV at `r` of all debt service equals the loan amount. So if each year's debt service is `CFADS/target`, the loan it can repay is the PV of those amounts.

**Sculpting when gearing binds:** if `D_gearing < D_dscr`, scale debt service as `DS[k] = CFADS[k] × D / PV(CFADS)`. Every year then has the same DSCR, equal to `PV(CFADS)/D`, which is higher than the target.

> **Sculpting pitfall:** if CFADS grows quickly, sculpted DS in early years can be *less than the interest*. Principal then comes out negative (the loan grows). Add the constraint `Principal ≥ 0`, or size debt by DSCR, and report it.

### 9.10 Reserve accounts (optional, add after the core is validated)

```
DSRA target[k]   = (dsra_months / 12) × DS[k+1]
DSRA movement[k] = target[k] − target[k−1]          (+ = cash put in, − = cash released)
MMRA contribution[k] = next MMR / years remaining until that MMR
```

Reserves move cash **in time** (from good years to bad years). They do not create cash. When funded, they reduce cash to equity in early years and release it later.

### 9.11 Cash flow waterfall and equity distributions

The payment priority, in strict order:

```
  Revenue
− O&M, MMR, concession fee
− Tax
= CFADS
− Senior interest
− Senior principal
− DSRA top-up (+ release)
− MMRA contribution (+ release)
= Cash available for equity (CFAE)
  IF lock-up active and DSCR[k] < lockup → cash is trapped (kept in the SPV)
= Distributions to equity (dividends)
```

If CFADS < DS (DSCR < 1), CFAE is **negative**. That is a **shortfall**. In the model, either draw on the DSRA or treat it as sponsor support (a negative equity cash flow). Always raise a **"DSCR < 1.0" warning flag**, because in reality it is a payment default.

### 9.12 Lender metrics

#### DSCR (Debt Service Coverage Ratio)

```
DSCR[k] = CFADS[k] / (Interest[k] + Principal[k])      only where DS[k] > 0
Min DSCR = min over repayment years;  Avg DSCR = average over repayment years
```

* **Meaning:** how many times this year's cash covers this year's debt payment.
* **Cushion:** a DSCR of 1.26 means CFADS can fall by `1 − 1/1.26 = 20.6%` that year before the project cannot pay.
* **Thresholds (indicative):** toll min 1.20 to 1.30x; HAM or annuity 1.10 to 1.20x; below 1.0x means default.

#### LLCR (Loan Life Coverage Ratio)

```
                Σ_{j=k..last repayment year} CFADS[j] / (1 + r)^(j − k + 1)   (+ DSRA balance)
LLCR[k]  =   ──────────────────────────────────────────────────────────────────────────────
                                    Open[k]  (debt outstanding at start of year k)
```

* **Meaning:** if all cash for the rest of the loan life went to lenders, how many times would it repay the remaining debt (in PV terms)? DSCR looks at one year; LLCR looks at the **whole remaining loan**.
* Discount at the **debt interest rate** `r`.
* LLCR at COD is the headline figure; lenders typically want ≥ 1.30 to 1.40x.

#### PLCR and ICR (extras)

```
PLCR[k] = PV of CFADS over the remaining CONCESSION / Open[k]     (includes the "tail")
ICR[k]  = CFADS[k] / Interest[k]
```

PLCR > LLCR shows how much cushion the tail adds after the loan is repaid.

### 9.13 Returns: Project IRR and Equity IRR

**IRR** is the discount rate at which NPV = 0:

```
NPV(i) = Σ_t CF[t] / (1 + i)^t ;      IRR = the i that makes NPV(i) = 0
```

Solve by **bisection** (always converges if NPV changes sign) or Newton's method. Cross-check with `numpy_financial.irr` and Excel `IRR()`.

| Return | Cash flow per year | What it measures |
|---|---|---|
| **Project IRR** (post-tax, unlevered) | `−Capex[t]` during construction (excluding IDC and fees); `EBITDA[k] − UnleveredTax[k]` in operations | Quality of the project itself, independent of how it is financed |
| **Project IRR, post-grant** | Same, but capex net of the grant | Return after government support (report both if a grant exists) |
| **Equity IRR** | `−Equity[t]` during construction; `+Distributions[k]` in operations (plus terminal value, usually 0 at handback) | Sponsor's return. It must beat the equity hurdle rate (about 15%). |

**Leverage effect:** `Equity IRR > Project IRR` whenever Project IRR is higher than the **after-tax cost of debt**, `r × (1 − tax)`. In the worked example, 13.94% > 10% × (1 − 0.2517) = 7.48%, so debt boosts equity returns to 20.02%. Leverage also amplifies losses: in the combined downside scenario Equity IRR collapses to about the level of Project IRR.

Also compute: **NPV** at the project discount rate, and **equity payback year** (first year cumulative equity cash flow ≥ 0).

---

## 10. Scenarios and sensitivity analysis

### 10.1 Scenario engine

A scenario is the **base inputs plus a small set of overrides**. Never copy the whole input file.

```yaml
# config/scenarios.yaml
base:            {}
traffic_m10:     { short: 0.10 }
traffic_m20:     { short: 0.20 }
traffic_m30:     { short: 0.30 }
slow_rampup:     { ramp: [0.70, 0.80, 0.90, 1.00] }
cost_p10:        { overrun: 0.10 }
cost_p20:        { overrun: 0.20 }
cost_p20_equity: { overrun: 0.20, overrun_mode: equity }
delay_1yr:       { delay_years: 1 }
rate_p100bp:     { r: 0.11 }
combined_down:   { short: 0.20, overrun: 0.20 }
```

```python
def run_scenario(base: dict, overrides: dict) -> Results:
    inputs = deep_merge(base, overrides)   # base is never modified
    return run_model(inputs)

summary = {name: key_metrics(run_scenario(base, ov)) for name, ov in scenarios.items()}
```

### 10.2 Scenario output table (one row per scenario)

| Columns |
|---|
| Scenario · TPC · Debt · Equity · IDC · Min DSCR (year) · Avg DSCR · LLCR at COD · Project IRR · Equity IRR · NPV · Debt fully repaid? · Any DSCR < 1.0? · Equity IRR ≥ hurdle? |

### 10.3 Sensitivity and break-even

* **Tornado chart:** move each key input by ±10% one at a time and plot the change in Equity IRR (and in min DSCR). It shows which assumption matters most. Traffic and capex usually top the list.
* **Two-way table:** traffic shortfall (0 to -30%) × cost overrun (0 to +30%), showing min DSCR (colour-code below 1.0 red, 1.0 to 1.2 amber). In Excel this is a Data Table; in Python, two nested loops.
* **Break-even traffic shortfall:** the shortfall at which min DSCR = 1.00. Solve by bisection on `short`. In the worked example it is ≈ **17.8%**, because the year-1 DSCR binds: `1 − 122.44/148.92`. Also find the shortfall at which Equity IRR = hurdle rate.
* **Lender's case vs sponsor's case:** lenders often size debt on a conservative traffic case (for example P90), while sponsors look at the expected case (P50).

---

## 11. Worked example (the mini model)

This small but complete toll-road case is the **base case** of the model. It serves three purposes:
1. It shows every calculation with real numbers.
2. It is the **regression test**: the built model must reproduce these numbers (±0.01).
3. It is the reference for the **hand validation** in Section 12.

**Inputs:** hard cost ₹1,000 Cr; phasing 30/40/30 over 3 years; no escalation, contingency, fees or grant; gearing 70:30 pro-rata; interest 10%; mid-year drawdown; concession 20 years (3 construction + 17 operations); AADT 24,000 PCU/day at COD, growing 4%; toll ₹200 per PCU-trip, escalating 3%; ramp-up 85%, 95%, 100%; O&M ₹20 Cr escalating 5%; MMR ₹50 Cr (escalated at 5%) in op years 5, 10, 15; tax 25.17%; straight-line depreciation of TPC over 17 years; loss carry-forward; **level annuity repayment over 15 years from COD, no moratorium**.

### 11.1 Construction phase: funding and IDC (₹ Cr)

| Year t | Capex K | Opening debt | IDC | Uses (K + IDC) | Debt draw (70%) | Equity (30%) | Closing debt |
|---|---|---|---|---|---|---|---|
| 1 | 300.00 | 0.00 | 10.88 | 310.88 | 217.62 | 93.26 | 217.62 |
| 2 | 400.00 | 217.62 | 37.06 | 437.06 | 305.94 | 131.12 | 523.56 |
| 3 | 300.00 | 523.56 | 65.14 | 365.14 | 255.59 | 109.54 | 779.15 |
| **Total** | **1,000.00** | | **113.08** | **1,113.08** (= TPC) | **779.15** | **333.92** | |

IDC is 11.3% of hard cost, a significant cost of financing that a model without IDC would miss. Check: 779.15 / 1,113.08 = 70.0% ✓.

### 11.2 Operations phase: revenue, CFADS, debt schedule and DSCR (₹ Cr)

Annuity debt service = `779.1525 × 0.10 / (1 − 1.10^−15)` = **102.44** every year.

| Op yr k | Revenue | O&M | MMR | Tax | **CFADS** | Opening debt | Interest | Principal | Closing debt | **DS** | **DSCR** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 148.92 | 20.00 | 0.00 | 0.00 | 128.92 | 779.15 | 77.92 | 24.52 | 754.63 | 102.44 | **1.26** |
| 2 | 178.29 | 21.00 | 0.00 | 0.47 | 156.82 | 754.63 | 75.46 | 26.98 | 727.65 | 102.44 | 1.53 |
| 3 | 201.04 | 22.05 | 0.00 | 10.26 | 168.73 | 727.65 | 72.77 | 29.67 | 697.98 | 102.44 | 1.65 |
| 4 | 215.35 | 23.15 | 0.00 | 14.33 | 177.87 | 697.98 | 69.80 | 32.64 | 665.34 | 102.44 | 1.74 |
| 5 | 230.68 | 24.31 | 60.78 | 3.42 | 142.18 | 665.34 | 66.53 | 35.90 | 629.44 | 102.44 | 1.39 |
| 6 | 247.11 | 25.53 | 0.00 | 23.45 | 198.13 | 629.44 | 62.94 | 39.49 | 589.94 | 102.44 | 1.93 |
| 7 | 264.70 | 26.80 | 0.00 | 28.55 | 209.35 | 589.94 | 58.99 | 43.44 | 546.50 | 102.44 | 2.04 |
| 8 | 283.55 | 28.14 | 0.00 | 34.05 | 221.36 | 546.50 | 54.65 | 47.79 | 498.71 | 102.44 | 2.16 |
| 9 | 303.74 | 29.55 | 0.00 | 39.98 | 234.21 | 498.71 | 49.87 | 52.57 | 446.14 | 102.44 | 2.29 |
| 10 | 325.36 | 31.03 | 77.57 | 26.85 | 189.92 | 446.14 | 44.61 | 57.82 | 388.32 | 102.44 | 1.85 |
| 11 | 348.53 | 32.58 | 0.00 | 53.27 | 262.68 | 388.32 | 38.83 | 63.61 | 324.72 | 102.44 | 2.56 |
| 12 | 373.35 | 34.21 | 0.00 | 60.71 | 278.43 | 324.72 | 32.47 | 69.97 | 254.75 | 102.44 | 2.72 |
| 13 | 399.93 | 35.92 | 0.00 | 68.73 | 295.28 | 254.75 | 25.47 | 76.96 | 177.79 | 102.44 | 2.88 |
| 14 | 428.40 | 37.71 | 0.00 | 77.38 | 313.31 | 177.79 | 17.78 | 84.66 | 93.13 | 102.44 | 3.06 |
| 15 | 458.90 | 39.60 | 99.00 | 61.80 | 258.51 | 93.13 | 9.31 | 93.13 | 0.00 | 102.44 | 2.52 |
| 16 | 491.58 | 41.58 | 0.00 | 96.78 | 353.21 | 0.00 | n/a | n/a | n/a | 0.00 | n/a (tail) |
| 17 | 526.58 | 43.66 | 0.00 | 105.07 | 377.85 | 0.00 | n/a | n/a | n/a | 0.00 | n/a (tail) |

Depreciation = 1,113.0751 / 17 = 65.4750 per year. Year 1 has a tax loss of 14.47, carried forward and used in year 2.

### 11.3 Headline results (base case)

| Metric | Value | Comment |
|---|---|---|
| Total Project Cost | ₹1,113.08 Cr | incl. IDC 113.08 |
| Debt / Equity | ₹779.15 / ₹333.92 Cr | 70 : 30 |
| **Min DSCR** | **1.26x** (op year 1) | ramp-up year with the largest interest |
| Avg DSCR | 2.11x | |
| **LLCR at COD** | **1.91x** | PV of CFADS (yrs 1 to 15 at 10%) = 1,489.13 ÷ 779.15 |
| **Project IRR** (post-tax, unlevered) | **13.94%** | |
| **Equity IRR** | **20.02%** | leverage effect |
| Tail | 2 years | op years 16 and 17 |

Cash flows for checking IRR in Excel (`=IRR(range)`), years t = 1 … 20:

```
Project: -300, -400, -300, 111.28, 132.51, 148.74, 158.63, 123.76, 180.62, 192.83, 205.93,
         219.98, 177.02, 251.23, 268.58, 287.19, 307.16, 254.49, 351.54, 376.18      → 13.94%
Equity:  -93.26, -131.12, -109.54, 26.48, 54.38, 66.29, 75.43, 39.74, 95.70, 106.91, 118.92,
         131.77, 87.48, 160.24, 175.99, 192.84, 210.87, 156.07, 353.21, 377.85      → 20.02%
```

### 11.4 Why the repayment profile matters (same project, different profile)

| Profile | Min DSCR | Equity IRR | Comment |
|---|---|---|---|
| Level annuity (base) | 1.26x | 20.02% | flat DS fits ramp-up reasonably well |
| Equal principal | **0.99x** (op yr 1) | 18.77% | front-loaded DS during ramp-up: **default in year 1** |

Lesson: with ramp-up, **front-loaded repayment kills year-1 DSCR**. That is why real loans use annuity, ballooning or sculpted repayment, or a moratorium.

### 11.5 Scenario results (expected output of the scenario engine)

| Scenario | Min DSCR | Avg DSCR | LLCR @COD | Project IRR | Equity IRR | Verdict |
|---|---|---|---|---|---|---|
| Base | 1.26 | 2.11 | 1.91 | 13.94% | 20.02% | Bankable |
| Traffic -10% | 1.11 | 1.89 | 1.72 | 12.48% | 16.98% | Below toll covenant (~1.20) |
| Traffic -20% | **0.97** | 1.68 | 1.53 | 10.90% | 13.60% | **DSCR < 1 → shortfall in yr 1** |
| Cost +10% (pro-rata) | 1.14 | 1.94 | 1.76 | 12.81% | 17.68% | Debt rises to 857.07 |
| Cost +20% (pro-rata) | 1.05 | 1.80 | 1.64 | 11.82% | 15.59% | Thin coverage |
| Combined (-20% traffic, +20% cost) | **0.81** | 1.45 | 1.31 | 9.00% | 9.44% | **Not bankable** |

Break-even traffic shortfall (min DSCR = 1.00) ≈ **17.8%**.

---

## 12. Validation plan (including the hand check)

Validation has three layers: automated integrity checks (every run), unit tests (on every code change) and the **hand check** (the brief's explicit requirement).

### 12.1 Automated integrity checks (`checks.py`, shown on the dashboard)

| # | Check | Formula | Tolerance |
|---|---|---|---|
| 1 | Sources = Uses | `Σ Sources − Σ Uses` each year | < 0.001 |
| 2 | Phasing sums to 100% | `Σ p_t − 1` | < 1e-9 |
| 3 | Gearing respected | `Debt / (TPC − Grant) − g` | < 0.0001 |
| 4 | Debt fully repaid | `Close[last repayment year]` | < 0.001 |
| 5 | Principal repaid = debt drawn | `Σ Principal − Debt at COD` | < 0.001 |
| 6 | Balance never negative | `min(Close) ≥ 0` | n/a |
| 7 | IDC closed form = IDC iteration | difference | < 1e-6 |
| 8 | NPV at the computed IRR ≈ 0 | `NPV(IRR)` | < 0.001 |
| 9 | DSCR < 1.0 in any year? | flag (warning, not error) | n/a |
| 10 | Debt maturity ≤ concession end | `mor + n ≤ To` | n/a |

### 12.2 Unit tests (`pytest`), including "degenerate case" tests

Degenerate cases are inputs where you **know** the answer without the model:

| Test | Set inputs | Expected result |
|---|---|---|
| Zero interest | `r = 0` | IDC = 0, interest = 0, DS = principal only |
| No debt | `g = 0` | IDC = 0, Equity IRR = Project IRR (if tax treatment matches) |
| Annuity is flat | `profile = annuity` | DS identical every repayment year |
| Annuity identity | annuity | `P[k] = P[1] × (1+r)^(k−1)` |
| Equal principal identity | equal | `Interest[k] = r × D × (1 − (k−1)/n)` |
| Sculpting | sculpted, `D = D_dscr` | DSCR = target every year |
| PV identity | any profile | `Σ DS[k] / (1+r)^k = Debt at COD` |
| No ramp-up / growth | `R = 1`, `g_tr = e_toll = 0` | Revenue constant |
| Worked example | base YAML | reproduces every number in Section 11 (±0.01) |
| Known IRR | CF = [-100, 110] | IRR = 10% |

### 12.3 Hand check (required by the brief)

**Which years to check (the reason for each choice goes in the report):**
1. **Construction year 2:** proves the IDC logic.
2. **Op year 1:** first repayment year, largest debt, ramp-up year, and the minimum DSCR.
3. **Op year 5:** a major-maintenance year; DSCR dips.
4. **Op year 15:** final repayment year; the loan must close at exactly zero.

**Procedure:** using only a calculator and the *inputs* (not model outputs, except the opening balance where noted), compute each item, write it in `validation/hand_check.xlsx` (or on paper, scanned) and compare with the model. Record the difference.

#### Hand check 1: IDC in construction year 2

```
Opening debt = 217.6166 (closing of year 1)
IDC2 = [0.10 × 217.6166 + 0.5 × 0.10 × 0.70 × 400] / (1 − 0.5 × 0.10 × 0.70)
     = [21.7617 + 14.0000] / 0.965 = 35.7617 / 0.965 = 37.0587
Draw2 = 0.70 × (400 + 37.0587) = 305.9411
Verify: 0.10 × (217.6166 + 0.5 × 305.9411) = 0.10 × 370.5872 = 37.0587  ✓
Closing = 217.6166 + 305.9411 = 523.5577  ✓
```

#### Hand check 2: debt service amount (annuity)

```
1.10^15 = 4.177248  →  1/4.177248 = 0.239392  →  1 − 0.239392 = 0.760608
DS = 779.1525 × 0.10 / 0.760608 = 779.1525 × 0.131474 = 102.4381  ✓
```

#### Hand check 3: op year 1 (min DSCR year)

```
Revenue   = 24,000 × 1.04^0 × 0.85 × 200 × 1.03^0 × 365 / 1e7 = 148.9200
O&M       = 20.0000 ;  MMR = 0
Interest  = 0.10 × 779.1525 = 77.9153
PBT       = 148.92 − 20.00 − 65.4750 (dep) − 77.9153 = −14.4703  → tax = 0, loss c/f 14.4703
CFADS     = 148.9200 − 20.0000 − 0 = 128.9200
Principal = 102.4381 − 77.9153 = 24.5229
Closing   = 779.1525 − 24.5229 = 754.6297
DSCR      = 128.9200 / 102.4381 = 1.2585  ✓
```

#### Hand check 4: op year 5 (major-maintenance year)

```
Revenue   = 24,000 × 1.04^4 × 1.00 × 200 × 1.03^4 × 365 / 1e7
          = 24,000 × 1.169859 × 225.1018 × 365 / 1e7 = 230.6834
O&M       = 20 × 1.05^4 = 24.3101 ;   MMR = 50 × 1.05^4 = 60.7753
Opening   = 665.3419  (shortcut: B4 = D(1+r)^4 − DS × [(1+r)^4 − 1]/r
                       = 779.1525 × 1.4641 − 102.4381 × 4.641 = 665.34 ✓)
Interest  = 0.10 × 665.3419 = 66.5342
Principal = 102.4381 − 66.5342 = 35.9039   (shortcut: 24.5229 × 1.1^4 = 35.904 ✓)
PBT       = 230.6834 − 24.3101 − 60.7753 − 65.4750 − 66.5342 = 13.5888
Tax       = 0.2517 × 13.5888 = 3.4203  (no loss left to carry forward)
CFADS     = 230.6834 − 24.3101 − 60.7753 − 3.4203 = 142.1777
DSCR      = 142.1777 / 102.4381 = 1.3879  ✓
```

#### Hand check 5: op year 15 (final repayment)

```
Principal = 24.5229 × 1.1^14 = 24.5229 × 3.797498 = 93.1256 = Opening balance  ✓
Interest  = 0.10 × 93.1256 = 9.3126 ;  DS = 9.3126 + 93.1256 = 102.4382 ≈ 102.4381 ✓ (rounding)
Closing   = 93.1256 − 93.1256 = 0.0000  ✓  (loan fully repaid)
DSCR      = 258.5112 / 102.4381 = 2.5236  ✓
```

#### Hand-check record template

| Year | Item | Hand value | Model value | Difference | OK? |
|---|---|---|---|---|---|
| C2 | IDC | 37.0587 | | | |
| Op 1 | Interest | 77.9153 | | | |
| Op 1 | Principal | 24.5229 | | | |
| Op 1 | Closing balance | 754.6297 | | | |
| Op 1 | CFADS | 128.9200 | | | |
| Op 1 | DSCR | 1.2585 | | | |
| Op 5 | DSCR | 1.3879 | | | |
| Op 15 | Closing balance | 0.0000 | | | |

> When the full model is built with your own project data, repeat the same five checks with your own numbers. The method stays the same.

---

## 13. Step-by-step build roadmap

Build in thin vertical slices and **test each phase before moving on**. Each phase ends with a "done when" condition.

### 13.1 Phases (Python route)

#### Phase 0: Setup (½ day)
1. Install Python 3.11+ (3.13 is already installed on this machine) and VS Code.
2. Open a terminal in `725 PROJECT` and create a virtual environment:
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
   If PowerShell refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.
3. Create the folders from Section 6. Optionally run `git init` and commit after every phase: free version history for the report.
4. **Done when:** `python -c "import numpy, pandas, streamlit"` runs without error.

#### Phase 1: Inputs and timeline (½ day)
1. Write `config/base_toll.yaml` with every input in Section 8 (base values).
2. `inputs.py`: load YAML into a dataclass, and validate it (phasing sums to 1, `0 ≤ g ≤ 1`, tenor fits the concession).
3. `timeline.py`: build arrays `t`, `k`, `is_constr`, `is_op`, `is_repay` (length N = 20).
4. **Done when:** printing the timeline shows 3 construction years and 17 operation years, and bad inputs raise clear errors.

#### Phase 2: Capex, funding and IDC (1 day)
1. `capex.py`: Section 9.2.
2. `funding.py`: Section 9.3 and 9.4, both the closed-form IDC and the iterative IDC.
3. **Done when:** the output equals Table 11.1, Sources = Uses, and closed form = iteration.

#### Phase 3: Revenue: toll first (½ day)
1. `revenue.py`: `toll_revenue(inputs, timeline)` from Section 9.5.1.
2. **Done when:** the Revenue column equals Table 11.2.

#### Phase 4: Opex, depreciation, tax, CFADS (1 day)
1. `opex.py` (Section 9.6), `tax.py` (Section 9.7), CFADS in `cashflow.py` (Section 9.8).
2. Tax needs interest, so first write the debt schedule as a stub with the annuity profile, or build Phase 5 alongside.
3. **Done when:** Tax and CFADS columns equal Table 11.2.

#### Phase 5: Debt schedule (1 to 2 days, the core of the project)
1. `debt.py`: the opening/interest/principal/closing engine (Section 9.9).
2. Implement profiles in this order: equal → annuity → structured → sculpted (with the tax iteration).
3. Add the moratorium and debt sizing (`min(gearing, DSCR)`).
4. **Done when:** Table 11.2 is reproduced, the closing balance is 0 at year 15, and the degenerate tests in Section 12.2 pass.

#### Phase 6: Waterfall and reserves (½ to 1 day)
1. `cashflow.py`: waterfall (Section 9.11) giving the equity distributions and shortfall flags.
2. Optional: DSRA, MMRA, lock-up (Section 9.10).
3. **Done when:** equity cash flows equal the series in Section 11.3.

#### Phase 7: Metrics (1 day)
1. `metrics.py`: DSCR, min/avg, LLCR (each year), PLCR, ICR, `irr()` by bisection, `npv()`, payback.
2. **Done when:** Section 11.3 results match, and `irr()` agrees with `numpy_financial.irr`.

#### Phase 8: Scenarios and sensitivity (1 day)
1. `scenarios.py`: deep-merge overrides, run all scenarios, build the summary table.
2. Add the tornado data, the two-way table and the break-even bisection.
3. **Done when:** the scenario table equals Section 11.5 and break-even ≈ 17.8%.

#### Phase 9: Metro and HAM modules (1 to 2 days)
1. Add `metro_revenue` and `ham_revenue` (Section 9.5.2 and 9.5.3), and switch on `project_type`.
2. For HAM: construction support → grant, annuity revenue, and the cost overrun hitting equity.
3. **Done when:** the HAM case shows **no change** under traffic shortfall, and the metro case needs a grant to be viable.

#### Phase 10: Validation (½ to 1 day, ongoing)
1. `checks.py` (Section 12.1) runs on every model run.
2. `tests/`: all tests in Section 12.2.
3. Complete the hand-check sheet (Section 12.3) for the selected years.
4. **Done when:** `pytest` is all green and the hand-check sheet shows differences < 0.01.

#### Phase 11: Dashboard and Excel export (1 to 2 days)
1. `export.py`: one sheet per module, plus Summary, Scenarios and Checks.
2. `app/dashboard.py`: see Section 14.2.
3. Run it from the project folder. The model package lives in `src/`, so put that folder on Python's path first:
   ```powershell
   $env:PYTHONPATH = "src"
   streamlit run app/dashboard.py
   ```
4. **Done when:** the base case shows exactly the Section 11.3 numbers, moving the traffic-shortfall slider to 20% turns Min DSCR red at 0.97x straight away, and the Excel download opens correctly.

#### Phase 12: Real case study, report and presentation (2 to 3 days)
1. Optional but strong: calibrate to a real project using public data (NHAI or state PPP project cost, traffic counts, concession period) and state your sources.
2. Write the report (structure in Section 17) and finish the AI usage log.

### 13.2 Excel route: sheet map (if Excel is required or wanted as a mirror)

| Sheet | Contents | Key Excel functions |
|---|---|---|
| `Cover` | Title, instructions, colour legend (inputs blue, formulas black, checks green/red) | n/a |
| `Inputs` | All assumptions (Section 8), scenario selector | `CHOOSE`, `INDEX` |
| `Scenarios` | Override table, one column per scenario | `INDEX/MATCH` |
| `Timeline` | Years, flags | `IF`, `AND` |
| `Capex_Funding` | Capex, sources & uses, IDC (circular, with circuit breaker) | iterative calc |
| `Revenue` | Toll / metro / HAM blocks | `INDEX` for ramp-up |
| `Opex_Tax` | O&M, MMR, depreciation, tax with loss c/f | `MAX`, `MIN` |
| `Debt` | Debt schedule, all profiles | `PMT`, `PPMT`, `IPMT` |
| `Waterfall` | CFADS → DS → reserves → equity | n/a |
| `Metrics` | DSCR, LLCR, IRRs, NPV | `MIN`, `AVERAGE`, `NPV`, `IRR`, `XIRR` |
| `Sensitivity` | Two-way data table, tornado | Data → What-If → Data Table |
| `Checks` | All integrity checks, master check cell | `ABS`, `AND` |
| `Dashboard` | Charts | n/a |
| `HandCheck` | Calculator verification of selected years | n/a |

---

## 14. Outputs and dashboard

### 14.1 Dashboard layout (Streamlit)

```
┌───────────────────────────┬─────────────────────────────────────────────────────────┐
│ SIDEBAR                   │  KPI CARDS: Min DSCR | Avg DSCR | LLCR | Proj IRR |      │
│ Project type [toll ▼]     │             Equity IRR | TPC | Debt | IDC   (red/green)  │
│ Scenario     [base ▼]     ├─────────────────────────────────────────────────────────┤
│ Traffic shortfall  ──●──  │  Chart 1: CFADS vs Debt Service (bars) + DSCR (line)     │
│ Cost overrun       ──●──  │           with covenant line at 1.20x and 1.00x          │
│ Interest rate      ──●──  ├─────────────────────────────────────────────────────────┤
│ Gearing            ──●──  │  Chart 2: Debt balance over time    Chart 3: Revenue     │
│ Repayment profile [▼]     │                                     with ramp-up         │
│ Tenor / moratorium        ├─────────────────────────────────────────────────────────┤
│ [Download Excel]          │  Scenario comparison table   |  Tornado chart            │
│                           │  Integrity checks: ✓ ✓ ✓ ✓   |  Sources & uses           │
└───────────────────────────┴─────────────────────────────────────────────────────────┘
```

### 14.2 How to build each part in Streamlit

`app/dashboard.py` only **shows** results: it reads the controls, calls `run_model()` / `run_scenario()` and draws what comes back. Put no finance maths in it, so the dashboard can never disagree with the tested model. Read the covenant DSCR and the equity hurdle from the config rather than typing them into the dashboard.

| Dashboard part | Streamlit / Plotly |
|---|---|
| Page setup | `st.set_page_config(layout="wide")` so the charts use the full width |
| Sidebar controls | `st.sidebar.selectbox` for project type, scenario and repayment profile; `st.sidebar.slider` for traffic shortfall, cost overrun, interest rate, gearing, tenor and moratorium. Picking a scenario sets the sliders' starting values |
| KPI cards | `st.columns` with an `st.metric` in each. Show the status as coloured text (`:green[...]`, `:orange[...]`, `:red[...]`): DSCR green at or above the covenant, amber from 1.00x up to the covenant, red below 1.00x; Equity IRR green at or above the hurdle, red below |
| Chart 1: CFADS vs debt service + DSCR | Plotly `make_subplots(specs=[[{"secondary_y": True}]])`: bars for CFADS and debt service, DSCR as a line on the second y-axis, plus flat lines at the covenant and at 1.00x. Draw it with `st.plotly_chart` |
| Charts 2 and 3, sources and uses | Plotly line chart (debt balance), bar chart (revenue), stacked bar chart (sources and uses) |
| Tornado | Plotly horizontal bar chart (`orientation="h"`): the low and high changes as two traces, largest range at the top |
| Heat map and scenario table | `st.dataframe(df.style.map(colour))`, where `colour` returns red below 1.00x and amber up to the covenant |
| Integrity checks | One `st.success` or `st.error` line per check |
| Download Excel | `st.download_button` with the workbook from `export.py`, written to memory (`io.BytesIO`) instead of to a file |

Streamlit re-runs the whole script every time a control changes. One model run takes milliseconds, but the scenario table, tornado, heat map and break-even search need about 100 runs together. Put them in a function marked `@st.cache_data`, so the same inputs are only calculated once.

### 14.3 Charts for the report

1. Sources and uses of funds (stacked bar: hard cost, IDC; debt, equity, grant)
2. Revenue build-up showing the ramp-up effect
3. **CFADS vs debt service with the DSCR line**: the most important chart
4. Debt outstanding over time, showing the tail
5. Scenario comparison: min DSCR and Equity IRR per scenario
6. Tornado chart (Equity IRR sensitivity)
7. Heat map: traffic shortfall × cost overrun → min DSCR
8. Repayment-profile comparison (equal vs annuity vs sculpted DSCR curves)

---

## 15. Role of AI and the AI usage log

The brief assigns AI four roles. Here is how to use it for each, and what **you** must still verify:

| AI role (from brief) | What AI does | What you must verify yourself |
|---|---|---|
| **Model architecture** | Proposes modules, calculation order, folder layout and conventions (this README) | That the structure covers every brief requirement; that the calculation order has no hidden dependency |
| **Debt schedule logic** | Derives formulas (annuity, sculpting, IDC closed form) and writes code | Hand-check selected years (Section 12.3); degenerate-case tests |
| **Scenario setup** | Proposes scenarios, override mechanism and break-even method | That scenarios are realistic for Indian PPPs and that the base case is untouched |
| **Explanation of lender metrics** | Explains DSCR, LLCR, PLCR, thresholds and interpretation | Cite primary sources (lender term sheets, textbooks, MCA documents) for thresholds |

### AI usage log template (`docs/ai_usage_log.md`)

| Date | Phase | What I asked AI | What AI produced | How I verified it | Changes I made |
|---|---|---|---|---|---|
| 2026-10-13 | Architecture | Build-from-scratch README for the PPP model | This README (architecture, formulas, worked example) | Recomputed IDC year 2 and op-year-1 DSCR by hand | n/a |
| | | | | | |

**Good practice:** never accept a formula you cannot explain in your own words. Every AI-generated number must pass the checks in Section 12.

---

## 16. Common mistakes

| Mistake | Consequence | Fix |
|---|---|---|
| Forgetting IDC, or not funding it | TPC and debt understated by about 10% | Section 9.4 |
| Interest on the closing balance instead of the opening balance | Interest is wrong and the circularity gets worse | Always `r × Open` |
| Growth or escalation applied from the wrong year (`k` instead of `k−1`) | Everything is off by one year of growth | Year 1 of operations = base value |
| Ramp-up applied cumulatively, or forgotten | Revenue wrong in the critical early years | `R[k]` multiplies; it is not compounded |
| Including IDC in Project IRR capex | Project IRR then depends on financing | Project IRR uses capex *excluding* IDC and fees |
| Using levered tax in Project IRR | Project IRR overstated (debt tax shield) | Separate unlevered tax |
| DSCR averaged over non-repayment years | Average looks better than it is | Only years with DS > 0 |
| LLCR discounted at the equity rate or the WACC | LLCR wrong | Discount at the debt rate `r` |
| Repayment beyond the concession end | Impossible (no revenue rights) | Check `mor + n ≤ To` |
| Sculpting with negative principal | Loan grows silently | Constraint `P ≥ 0` (Section 9.9) |
| Scenario edits that overwrite base inputs | Base case corrupted | Deep-merge copies (Section 10.1) |
| Delay scenario that extends the concession | Hides the real cost of delay | Keep the concession end fixed |
| HAM cost overrun increasing revenue | Wrong: payments are based on BPC | Revenue uses BPC, not actual cost |
| Mixing ₹, lakh and crore | Off by 100x or 10^7 | Everything in ₹ crore; convert once |

---

## 17. Deliverables checklist

- [ ] Working model (Python engine and/or Excel) with toll, metro and HAM
- [ ] Base-case YAML files and scenario file
- [ ] Integrity checks all passing, `pytest` all green
- [ ] Hand-check sheet for the selected years (debt schedule + DSCR), with differences < 0.01
- [ ] Dashboard (Streamlit) and Excel export
- [ ] Scenario table: traffic shortfall, cost overrun, delay, rate shock, combined
- [ ] Sensitivity: tornado, two-way table, break-even traffic
- [ ] AI usage log
- [ ] Report, suggested structure:
  1. Introduction and PPP background (BOT, metro, HAM)
  2. Model architecture and conventions
  3. Methodology: formulas for IDC, revenue, CFADS, debt, DSCR, LLCR, IRR
  4. Base-case results
  5. Scenario and sensitivity results, and the lender's view
  6. Validation: integrity checks + hand calculation
  7. Role of AI: what it did and how it was verified
  8. Limitations and extensions
  9. Conclusion
- [ ] Presentation slides

---

## 18. Open items to confirm with the instructor

1. Python + Excel export acceptable, or **Excel-only** required?
2. Is a **real case study** expected (a specific NHAI or metro project), or is an illustrative case enough?
3. Primary project type to emphasise: toll, metro or HAM (the model supports all three)?
4. **Annual** periods acceptable, or semi-annual (HAM annuities are semi-annual)?
5. Form of the hand validation: handwritten scans or a calculator table?
6. Report length, format and submission date.

*(This README will be updated once the detailed requirements are shared.)*

---

## 19. References

* E.R. Yescombe, *Principles of Project Finance* (2nd ed.), Academic Press: project finance structure, DSCR, LLCR, sculpting.
* E.R. Yescombe & E. Farquharson, *Public-Private Partnerships for Infrastructure*: PPP contract and financial structures.
* P. Gatti, *Project Finance in Theory and Practice*: cash flow waterfall, cover ratios, base vs downside cases.
* NHAI / MoRTH, *Model Concession Agreement* for BOT (Toll) and for Hybrid Annuity Model: payment mechanisms, concession period, construction support.
* Ministry of Finance (DEA), *Scheme for Financial Support to PPPs in Infrastructure (VGF Scheme)*.
* National Highways Fee (Determination of Rates and Collection) Rules, 2008: toll rate revision.
* FAST Standard (Financial modelling standard: flexible, appropriate, structured, transparent): modelling conventions.
