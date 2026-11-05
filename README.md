# PPP Infrastructure Project Financial Model

Course project, Topic 9. A Python model of how a Public-Private Partnership (PPP) infrastructure project is financed: a BOT toll road, a metro line or a Hybrid Annuity Model (HAM) road. From one set of assumptions it builds the project's finances year by year: construction cost, debt and equity, interest during construction (IDC), revenue with ramp-up, operating costs, tax, cash flow available for debt service (CFADS) and the debt schedule. It then reports what lenders and investors check (DSCR, LLCR, Project IRR, Equity IRR) and re-runs everything under stress (traffic shortfall, cost overrun, delay, rate rise) to show whether the structure stays bankable.

This guide covers what has been built, how to run it, how it works, and how the five of us split the work of learning it and finishing the report and slides. Status as of 28 October 2026.

> **Two documents.** This README describes the finished build. [overview.md](overview.md) is the original specification: concepts, glossary, every formula, the worked example and the build plan. It used to be named README.md, so wherever the code, configs or docs cite "README §N", read **overview.md §N**.
>
> **How it was built.** The engine, dashboard, tests and docs were generated with AI assistance (Claude) from that specification, then checked against it. [docs/ai_usage_log.md](docs/ai_usage_log.md) records what AI produced and how each part was verified. The course rule is that we must be able to explain every formula ourselves; the [team plan](#10-team-plan) is how we get there.

## Contents

1. [What we built](#1-what-we-built)
2. [Status](#2-status)
3. [Setup and running](#3-setup-and-running)
4. [Folder map](#4-folder-map)
5. [How the model works](#5-how-the-model-works)
6. [Base-case results](#6-base-case-results)
7. [Scenarios and sensitivity](#7-scenarios-and-sensitivity)
8. [Dashboard guide](#8-dashboard-guide)
9. [Validation](#9-validation)
10. [Team plan](#10-team-plan)
11. [Where to look things up](#11-where-to-look-things-up)

---

## 1. What we built

| Part | Where | What it does |
|---|---|---|
| Calculation engine | [src/ppp_model/](src/ppp_model/) | Takes the inputs and calculates every number. Contains no dashboard code, so it is tested on its own |
| Inputs | [config/](config/) | One base case per project type plus 11 scenarios, in YAML. Every assumption is here; none is typed into the code |
| Dashboard | [app/dashboard.py](app/dashboard.py) | Streamlit web app with 8 pages: change assumptions and stress levers and watch the results update |
| Command line | `python -m ppp_model` | Runs the model, the scenario table, the Excel export, the report charts and the hand check |
| Excel export | [outputs/](outputs/) | The full model as values: 14 sheets (15 for HAM), one workbook per project type |
| Report charts | [outputs/charts/](outputs/charts/) | The 8 charts the specification asks for (overview.md §14.3), for each project type |
| Tests | [tests/](tests/) | 197 automated tests, including every number in the specification's worked example |
| Hand check | [validation/](validation/) | 37 items recomputed calculator-style for selected years |
| Documentation | [docs/](docs/) | Formulas as implemented, assumptions and limitations, AI usage log |

How the brief's requirements map to the build:

| The brief asks for | Where it is |
|---|---|
| Debt-equity structure | `funding.py`: gearing, grant, sources = uses |
| Interest during construction | `funding.py`: closed-form solution, cross-checked by plain iteration |
| Revenue ramp-up | `revenue.py`: toll and metro (HAM has none, by design) |
| DSCR and LLCR | `metrics.py` |
| Project IRR and Equity IRR | `metrics.py`, with the cash-flow series built in `model.py` |
| Traffic-shortfall and cost-overrun scenarios | `scenarios.py`, `config/scenarios.yaml`, dashboard sidebar |
| Hand verification of the debt schedule and DSCR | `checks.hand_check` → `validation/`; `tests/test_worked_example.py` |

## 2. Status

**Done, and re-checked on 28 October 2026**

- `python -m pytest`: 197 of 197 tests pass.
- Every integrity check passes on the toll, metro and HAM base cases.
- The toll base case reproduces the specification's worked example (overview.md §11) within ±0.01, including every scenario row and the 17.8% break-even. The specification has two half-cent rounding slips, documented in [docs/assumptions_and_limitations.md](docs/assumptions_and_limitations.md) §2.1.
- The hand check agrees on all 37 items.
- The dashboard runs without errors.

**Still to do** (owners in the [remaining-work tracker](#109-remaining-work-tracker))

- The written report (nine chapters, overview.md §17).
- The presentation slides.
- Our own calculator hand check. The "Your verification" row in docs/ai_usage_log.md is empty.
- The open questions for the instructor (overview.md §18): is Python with an Excel export acceptable, is a real case study expected, are annual periods acceptable, what form the hand check should take, and the report length and deadline.
- The metro and HAM base cases use cost and financing inputs that are our own illustrative assumptions, not project data. Confirm them or replace them with a real project.
- Primary sources for the lender thresholds (DSCR 1.20–1.30x and so on).

## 3. Setup and running

You need Python 3.11 or newer. In PowerShell, from the project folder:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

python -m pytest                                   # 197 tests, about 10 seconds
streamlit run app/dashboard.py                     # dashboard at http://localhost:8501
python -m ppp_model run --type toll                # headline results (also metro, ham)
python -m ppp_model run --type toll --scenario traffic_m20
python -m ppp_model scenarios --type ham           # scenario table and break-even
python -m ppp_model export --type metro            # Excel workbook in outputs/
python -m ppp_model charts --type toll             # 8 report charts in outputs/charts/toll/
python -m ppp_model hand-check                     # validation/hand_check.xlsx and .md
```

When you share the folder, leave out `.venv/`. It only works on the computer that created it, so each person makes their own with the first four lines. `export`, `charts` and `hand-check` overwrite their files in `outputs/` and `validation/`; those files are generated, so that is expected.

Scenario keys for `--scenario`: `base`, `traffic_m10`, `traffic_m20`, `traffic_m30`, `slow_rampup`, `cost_p10`, `cost_p20`, `cost_p20_equity`, `delay_1yr`, `rate_p100bp`, `combined_down`.

## 4. Folder map

```
725 PROJECT/
├── README.md                      this guide
├── overview.md                    the specification ("README §N" in code and docs means this file)
├── pyproject.toml, requirements.txt
├── .streamlit/config.toml         dashboard theme
├── config/
│   ├── base_toll.yaml             toll base case = the specification's worked example (§11)
│   ├── base_metro.yaml            metro base case (illustrative cost and financing)
│   ├── base_ham.yaml              HAM base case (illustrative cost and financing)
│   └── scenarios.yaml             11 scenarios, two-way grid, tornado variables, break-even search
├── src/ppp_model/                 calculation engine (module list in Section 5.1)
├── app/dashboard.py               Streamlit dashboard: displays results, does no finance maths
├── tests/                         197 pytest tests in 12 files (Section 9)
├── validation/                    hand_check.md and hand_check.xlsx
├── docs/
│   ├── model_methodology.md       every formula exactly as implemented
│   ├── assumptions_and_limitations.md   where the build departs from the spec, and why
│   └── ai_usage_log.md            what AI produced and how it was checked
└── outputs/                       generated: 3 Excel workbooks and 24 report charts
```

## 5. How the model works

### 5.1 The calculation, step by step

`model.run_model()` runs these steps in order for one set of inputs. Each step uses only the results of the steps before it, apart from the circular loops described in [5.3](#53-six-ideas-to-understand-first).

```
config YAML ─► inputs.py ─► 1 timeline ─► 2 capex ─► 3 revenue ─► 4 opex ─► 5 funding + IDC
                                                                                   │
      ┌────────────────────────────────────────────────────────────────────────────┘
      ▼
  6 debt schedule ⇄ tax ⇄ CFADS ─► 7 waterfall ─► 8 metrics ─► 9 checks ─► ModelResults
                                                                               │
                                     dashboard · Excel · report charts · command line

  scenarios.py repeats steps 1–9 for every scenario
```

| Step | Module | What it calculates | Spec | Owner |
|---|---|---|---|---|
| 0 | `inputs.py`, `errors.py` | Loads the YAML, validates every input, applies scenario overrides | §8 | P1 |
| 1 | `timeline.py` | Model years t, operating years k = t − Tc, flags for construction, operation, moratorium and repayment; delays | §9.1 | P1 |
| 2 | `capex.py` | Cost per year: base cost × phasing × escalation, plus contingency, pre-operative cost and overrun | §9.2 | P1 |
| 3 | `revenue.py` | Toll: traffic × toll rate, with growth and ramp-up. Metro: riders × fare, plus non-fare revenue. HAM: the Authority's payments | §9.5 | P3 |
| 4 | `opex.py` | O&M, major maintenance in its years, concession fee, EBITDA | §9.6 | P3 |
| 5 | `funding.py` | Sources = uses each year; debt = gearing × (cost − grant); IDC added to the loan | §9.3–9.4 | P2 |
| 6 | `debt.py`, `tax.py`, `cashflow.py` | Debt schedule (equal, annuity, structured or sculpted), depreciation and tax, CFADS | §9.7–9.9 | P2, P3 |
| 7 | `cashflow.py` | Waterfall: debt service, then reserves (DSRA, MMRA) and lock-up, then distributions to equity | §9.10–9.11 | P3 |
| 8 | `metrics.py` | DSCR, LLCR, PLCR, ICR, Project and Equity IRR, NPV, payback | §9.12–9.13 | P4 |
| 9 | `checks.py` | 26 automated checks, and the hand check | §12 | P5 |
| — | `model.py` | `run_model()`: runs steps 1–9, solves the circular loops, builds the annual table | §7 | P1, P2 |
| — | `scenarios.py` | Scenario table, two-way table, tornado, break-even, repayment-profile comparison | §10 | P4 |
| — | `export.py`, `report_charts.py`, `__main__.py` | Excel workbook, report PNGs, command line | §14 | P5 |

Revenue and opex run before funding, although the specification lists funding first. HAM construction support is a revenue item that funding needs as its grant, and neither depends on funding, so the results are the same.

### 5.2 Where the inputs come from

Three layers, each overriding the one before:

1. **Base case**: `config/base_toll.yaml`, `base_metro.yaml` or `base_ham.yaml`.
2. **Scenario**: `config/scenarios.yaml`. A scenario's few changes are merged onto a fresh copy of the base, so the base is never modified (a test checks this).
3. **Sidebar levers** on the dashboard: traffic shortfall, cost overrun and who funds it, construction delay, interest-rate shock.

The dashboard's **Project assumptions** page edits the base case for your current browser session only; nothing is written back to the YAML files. To keep a change, edit the YAML file or use Export → Download assumptions (.yaml).

Every input is validated before a run: types, ranges, phasing summing to 100%, the loan fitting inside the concession, and more. A bad input stops the run with a list of every problem. Nothing is silently clipped.

### 5.3 Six ideas to understand first

| Idea | In one or two sentences | Where |
|---|---|---|
| IDC is circular | Interest during construction is added to the loan, but the loan depends on total cost, which includes IDC. The model solves it with a closed formula, `IDC = (r·Open + m·r·g·K) / (1 − m·r·g)`, and check C04 confirms it by plain iteration | `funding.py` |
| CFADS | Cash available to pay lenders: revenue − O&M − major maintenance − concession fee − tax | `cashflow.py` |
| DSCR | CFADS ÷ debt service for one year. Below 1.00x the project cannot pay its lenders that year; toll lenders typically want 1.20–1.30x | `metrics.py` |
| LLCR | Present value of CFADS over the remaining loan life, at the loan rate, ÷ debt outstanding: cover over the whole loan | `metrics.py` |
| Project vs Equity IRR | Project IRR is the return on the whole investment, ignoring how it is financed. Equity IRR is the sponsor's return after lenders are paid; it is higher when debt costs less than the project earns (leverage) | `metrics.py` |
| Sculpting | Debt service is set to CFADS ÷ a target DSCR every year, so cover is flat and repayment follows the cash flow | `debt.py` |

Symbols in the IDC formula: r interest rate, m share of the year a construction draw earns interest (0.5), g gearing, K the year's cost to fund (capex + fees − grant), Open the loan balance at the start of the year.

### 5.4 Conventions

- Money in ₹ crore. Rates and shares as decimals in YAML (0.10 = 10%).
- Annual periods. Cash flows at year end, except construction drawdowns, which earn interest for half the year.
- In operating year k, growth and escalation use (1 + g)^(k−1), so operating year 1 carries the base value.
- Interest is charged on the opening balance.
- No financial number is hard-coded; all of them are in `config/`.

## 6. Base-case results

| | Toll (BOT) | Metro | HAM |
|---|---:|---:|---:|
| Inputs from | Spec §11 worked example | Spec §8.5 revenue; assumed cost and financing | Spec §8.6 contract terms; assumed cost and financing |
| Construction / concession (years) | 3 / 20 | 5 / 35 | 2 / 17 |
| Total project cost | 1,113.08 | 2,835.40 | 958.50 |
| Grant or construction support | — | 1,027.93 (40% VGF) | 412.00 (40% of bid cost) |
| Debt / equity | 779.15 / 333.92 | 1,084.48 / 722.98 | 409.88 / 136.63 |
| IDC | 113.08 | 208.63 | 31.50 |
| Loan | Annuity, 15 yrs, 10% | Structured, 18 yrs after a 2-yr moratorium, 9% | Sculpted, 13 yrs, 8.75%; smaller of 75% gearing and 1.20x DSCR |
| Min DSCR (operating year) | 1.26x (1) | 1.32x (1) | 1.45x (8) |
| Average DSCR | 2.11x | 3.81x | 1.45x |
| LLCR at COD | 1.91x | 3.14x | 1.45x |
| Lender covenant: DSCR / LLCR | 1.20x / 1.30x | 1.25x / 1.35x | 1.15x / 1.20x |
| Project IRR, before / after grant | 13.94% / 13.94% | 11.65% / 15.80% | 2.23% / 10.29% |
| Equity IRR (hurdle) | 20.02% (15%) | 19.85% (15%) | 16.49% (14%) |
| Project NPV at 12%, before grant | 131.15 | −79.33 | −326.45 |
| Equity payback | Model year 9 | Model year 11 | Model year 7 |

Money in ₹ crore. All integrity checks pass and there are no financial warnings in any of the three.

- The toll case is the specification's worked example; the tests pin every number in it.
- The metro and HAM revenue inputs come from the specification. Their cost and financing inputs are our own assumptions ([docs/assumptions_and_limitations.md](docs/assumptions_and_limitations.md) §4), so treat their results as illustrative until they are confirmed.
- Project IRR is shown before and after the grant. The before-grant figure measures the asset itself; the dashboard shows the after-grant figure for metro and HAM. HAM's before-grant IRR is low because it leaves out the 40% construction support the Authority pays.

## 7. Scenarios and sensitivity

### Toll road (the main case)

| Scenario | Min DSCR | Avg DSCR | LLCR | Project IRR | Equity IRR | Verdict |
|---|---:|---:|---:|---:|---:|---|
| Base case | 1.26x | 2.11x | 1.91x | 13.94% | 20.02% | Bankable |
| Traffic −10% | 1.11x | 1.89x | 1.72x | 12.48% | 16.98% | Below covenant |
| Traffic −20% | 0.97x | 1.68x | 1.53x | 10.90% | 13.60% | Not bankable (op years 1, 5) |
| Traffic −30% | 0.75x | 1.46x | 1.33x | 9.17% | 9.83% | Not bankable (op years 1, 5) |
| Slow ramp-up | 1.00x | 2.07x | 1.85x | 13.45% | 18.63% | Below covenant |
| Cost +10% | 1.14x | 1.94x | 1.76x | 12.81% | 17.68% | Below covenant |
| Cost +20% | 1.05x | 1.80x | 1.64x | 11.82% | 15.59% | Below covenant |
| Cost +20%, equity-funded | 1.26x | 2.13x | 1.94x | 11.82% | 14.47% | Lenders fine; equity below hurdle |
| Delay 1 year | 1.21x | 2.05x | 1.86x | 12.66% | 17.53% | Bankable |
| Rate +100 bp | 1.18x | 1.99x | 1.79x | 13.94% | 19.08% | Below covenant |
| Traffic −20% and cost +20% | 0.81x | 1.44x | 1.31x | 9.00% | 9.44% | Not bankable (op years 1, 2, 5) |

Break-even: minimum DSCR reaches 1.00x at a **17.78%** traffic shortfall; Equity IRR reaches the 15% hurdle at 16.01%.

### Metro and HAM

| Scenario | Metro min DSCR | Metro Equity IRR | HAM min DSCR | HAM Equity IRR |
|---|---:|---:|---:|---:|
| Base case | 1.32x | 19.85% | 1.45x | 16.49% |
| Traffic −20% | 0.93x | 16.31% | 1.45x | 16.49% |
| Slow ramp-up | 0.74x | 18.65% | 1.45x | 16.49% |
| Cost +20% | 0.99x | 16.06% | 1.20x | 3.00% |
| Rate +100 bp | 1.17x | 19.27% | 1.39x | 14.67% |
| Break-even traffic shortfall | 16.56% | | not applicable | |

Without its 40% grant the metro's minimum DSCR is 0.79x and its Equity IRR 13.44%.

### What the results say

1. **The toll road is bankable with little headroom.** A 10% traffic shortfall already breaks the 1.20x covenant, and at 17.8% the road stops covering its debt service. In the tornado, traffic and the toll rate move Equity IRR the most, followed by construction cost.
2. **Operating year 1 and the resurfacing years are the pinch points.** Year 1 has the largest loan while revenue is still ramping up. At −30% traffic the binding year moves to op year 5, when resurfacing is paid, so a reserve sized only for the ramp-up would not be enough.
3. **The financing structure matters as much as the project.** On the same toll road, equal-principal repayment fails in year 1 (0.99x), the annuity passes (1.26x) and sculpting gives 1.65x. A 20% overrun funded pro-rata pushes DSCR down to 1.05x; funded by equity it leaves DSCR alone but takes Equity IRR below the hurdle.
4. **Metro needs public money; HAM moves the risk from traffic to cost.** Fare revenue alone cannot carry the metro's cost. HAM revenue does not move with traffic at all, but construction cost is by far the largest risk to HAM equity: a 20% overrun cuts Equity IRR from 16.5% to 3.0%, because the Authority pays on the bid cost, not the actual cost.

## 8. Dashboard guide

Start it with `streamlit run app/dashboard.py` and open http://localhost:8501.

**Sidebar** (applies to every page): project type; scenario; stress levers for traffic or ridership shortfall (0–60%), cost overrun (0–50%) and who funds it, construction delay (0–3 years) and interest-rate shock (−200 to +300 bp); a reset button; and a badge that says whether the integrity checks pass.

| Page | What it shows |
|---|---|
| Overview | Headline figures, coloured against the covenant and the hurdle; concession timeline; CFADS vs debt service with DSCR; debt outstanding; sources and uses; warnings |
| Project assumptions | Every base-case input in five tabs. *Validate and apply* re-runs the model only if the inputs are valid; *Reset to config file* reloads the YAML |
| Financial statements | Every annual line item, grouped by statement; years as rows or as columns |
| Debt analysis | Debt balance, interest and principal, DSCR, LLCR and PLCR by year, repayment-profile comparison |
| Scenario analysis | All 11 scenarios; the selected case against the base; two-way table (shortfall × overrun); tornado; break-even |
| Revenue analysis | Traffic or ridership with ramp-up, the toll or fare path, revenue build-up; for HAM, the Authority's payments and the semi-annual annuity schedule |
| Validation | Integrity and financial checks, IDC cross-check, IRR and NPV checks, hand check, test suite |
| Export | Excel workbook, scenario CSV, assumptions YAML, validation CSV, annual table CSV |

DSCR colours: green at or above the covenant, amber between 1.00x and the covenant, red below 1.00x.

### 8.1 AI assistant ("Ask the model")

A floating button at the bottom right of every page opens a chat powered by the Google Gemini API ([app/chatbot.py](app/chatbot.py)). It **explains** the model's results. It never calculates them and never changes inputs.

- **What it is sent with each question:** the page being viewed, the project type, scenario and lever positions, every headline metric for the current case (and the unstressed base case when stressed), the check results, the annual schedule (CFADS, debt service, DSCR, LLCR and so on), the 11-scenario table, the full input YAML, and [docs/model_methodology.md](docs/model_methodology.md) and [docs/assumptions_and_limitations.md](docs/assumptions_and_limitations.md). Its instructions tell it to use only those numbers, to say when a number isn't available, and to compare against the covenants in the config.
- **API key:** create one at aistudio.google.com, then copy [.streamlit/secrets.toml.example](.streamlit/secrets.toml.example) to `.streamlit/secrets.toml` (git-ignored, never share it) and paste the key in:
  ```toml
  GEMINI_API_KEY = "your-key"
  # GEMINI_MODEL = "gemini-flash-latest"   # optional: pin a model id from ai.google.dev/gemini-api/docs/models
  ```
  or set the `GEMINI_API_KEY` environment variable, or paste it into the chat panel (kept for that browser session only).
- **Privacy:** questions and the current results go to Google. That is fine for these illustrative cases. Do not use it with confidential bid or lender data unless the API terms you are on allow it. The panel says this to every user.
- **Reliability:** answers can be wrong. Treat every number in an answer as a claim to check against the model's own tables. Wrong answers you find are good material for the AI capability section of the reflection report.

## 9. Validation

There are four layers of checking, and each catches a different kind of mistake.

1. **Input validation** (`inputs.py`). Wrong or inconsistent inputs are rejected before anything is calculated.
2. **Automated checks on every run** (`checks.py`, C01–C26). *Integrity* checks test the arithmetic and must pass: sources = uses (C01), IDC closed form = iteration (C04), principal reconciles to the loan (C06), NPV at the IRR is zero (C08), HAM revenue ignores traffic and overruns (C12, C13), the waterfall balances (C15). *Financial* checks only warn: DSCR below 1.00x, a covenant breach, Equity IRR below the hurdle, a loan maturing after the concession.
3. **197 unit tests** (`tests/`):

   | File | Tests | What it covers | Owner |
   |---|---:|---|---|
   | test_inputs.py | 30 | Loading and every validation rule; scenario merging never changes the base | P1 |
   | test_timeline.py | 9 | Flags, the (k − 1) exponent, delays with a fixed concession end | P1 |
   | test_funding_idc.py | 22 | IDC closed form vs iteration, equity-first, overrun funding, fees, grant, DSRA at COD | P2 |
   | test_debt.py | 19 | The four profiles, moratorium, sculpting and its pitfall, DSCR sizing, maturity past the concession | P2 |
   | test_revenue.py | 14 | Toll, metro and HAM formulas; ramp-up not compounded; capacity; HAM ignores traffic and overruns | P3 |
   | test_tax.py | 10 | Loss carry-forward, unlevered tax, depreciation totals | P3 |
   | test_cashflow.py | 7 | Waterfall, DSRA, MMRA, lock-up, sponsor support | P3 |
   | test_metrics.py | 15 | IRR solver (including multiple and missing roots), NPV convention, DSCR, LLCR, PLCR, ICR, payback | P4 |
   | test_scenarios.py | 23 | Spec §11.5 scenario rows, base isolation, 17.8% break-even, tornado, two-way table, HAM, metro grant | P4 |
   | test_worked_example.py | 27 | Every number in spec Tables 11.1–11.3 and §11.4 | P5 |
   | test_checks.py | 16 | Checks pass in every scenario, deliberately corrupted results fail, hand check | P5 |
   | test_export.py | 5 | Excel workbooks and report charts | P5 |

4. **Hand check** ([validation/hand_check.md](validation/hand_check.md)). Construction year 2, the annuity payment, and operating years 1, 5 and 15 of the toll case are recomputed from the inputs with calculator-style formulas, without calling the model's own code. All 37 items agree. Our own calculator check of these years is still to do (see the team plan).

## 10. Team plan

### 10.1 The split

The work is split along the model's calculation order, so in the teach-back ([10.8](#108-order-of-work)) each person builds on the one before. Each area has between 31 and 48 of the 197 tests. Fill in the names:

| | Name | Area | Report chapters (overview.md §17) | Calculator hand check (overview.md §12.3) |
|---|---|---|---|---|
| P1 | | Architecture, inputs, timeline, capital cost | 1 Introduction and PPP background · 2 Architecture and conventions · 9 Conclusion · final edit | HC1: construction year 2 |
| P2 | | Funding, IDC, debt schedule, circular loops | 3 Methodology: funding, IDC, debt · 4 Base-case results | HC2: annuity payment · HC5: op year 15 |
| P3 | | Revenue, operating costs, tax, CFADS, waterfall | 3 Methodology: revenue, costs, tax, CFADS · 8 Limitations and extensions | HC4: op year 5 |
| P4 | | Lender metrics, returns, scenarios, sensitivity | 3 Methodology: DSCR, LLCR, IRR · 5 Scenarios, sensitivity and the lender's view | HC3: op year 1 |
| P5 | | Validation, dashboard, outputs | 6 Validation · 7 Role of AI · slide deck and live demo | Collects all five into the record |

When choosing who takes what: P2 has the hardest finance (the specification calls the debt schedule the core of the project), so give it to whoever is strongest in finance. P5 has the most code, but most of it is dashboard display code, so give it to whoever is most comfortable with Python.

Each person's section below lists what they own, what to read in order, exercises with the answers the model gives, the questions they should be able to answer, and their share of the remaining work.

### 10.2 P1: Architecture, inputs, timeline and capital cost

You explain how the whole model fits together and where every number comes from.

**Owns:** `config/base_toll.yaml`, `base_metro.yaml`, `base_ham.yaml`; `inputs.py`, `errors.py`, `timeline.py`, `capex.py`; the flow of `model.py` (`run_model`, `annual_table`). Tests: `test_inputs.py`, `test_timeline.py` (39).

**Read, in this order**

1. overview.md §1–§8 (brief, PPP basics, glossary, conventions, architecture, inputs) and §9.1–§9.2.
2. docs/model_methodology.md §2–§6.
3. docs/assumptions_and_limitations.md §2.6 (delays), §2.14 and §3.
4. Code: `model.run_model()` first, because it calls every other module in order; then `timeline.py`, `capex.py`, `inputs.py`.

**Try it**

| Do this | You should get |
|---|---|
| `python -m ppp_model run --type toll` | TPC 1,113.08; IDC 113.08; debt 779.15; equity 333.92 |
| Project assumptions: phasing `30, 40, 20`, then Validate and apply | Refused: phasing must sum to 100% (it sums to 90%). The model does not re-run |
| Copy `base_toll.yaml`, set `delay_years` (under `stress`) to 0.5, run `python -m ppp_model run --config <copy>` | Refused: a delay must be a whole number of years, because periods are annual |
| Sidebar: construction delay 1 year | Operations shrink from 17 to 16 years (the concession end is fixed); phasing is re-spread to 22.5/27.5/27.5/22.5; IDC rises from 113.08 to 154.29; Equity IRR 17.53% |
| Project assumptions: capex escalation 5% | Year-2 capex = 1,000 × 0.40 × 1.05 = 420.00; TPC 1,167.17; min DSCR 1.20x, exactly on the covenant |

**Be ready to explain**

- SPV, concession, financial close and COD; how toll, metro and HAM differ in who carries traffic risk; why HAM was introduced.
- Model year t vs operating year k, and why growth uses (k − 1).
- Why a delay shortens operations rather than extending the concession, and what happens to a loan that would mature after the end.
- How a scenario changes the inputs without touching the base case.
- The order in which `run_model()` calls the modules, and why revenue comes before funding.
- Why bad inputs are rejected rather than corrected.

**Hand check:** HC1, construction year 2: capex 400.00 → IDC 37.06 → debt draw 305.94 → closing debt 523.56 (start from the year-1 closing debt of 217.62).

**Also:** take the open questions to the instructor (overview.md §18), and lead the decision on replacing the metro and HAM inputs with a real project. Slides: the problem, the three project types, the architecture.

### 10.3 P2: Funding, IDC, debt schedule and circular loops

You explain how the project is financed, how much it can borrow and how the loan is repaid.

**Owns:** `funding.py`, `debt.py`; in `model.py`, `_size_debt`, `_solve_case` and `_operations` (debt sizing and the sculpting ⇄ tax and DSRA loops). Tests: `test_funding_idc.py`, `test_debt.py` (41).

**Read, in this order**

1. overview.md §7.3 (circular references), §9.3, §9.4, §9.9, §11.1, §11.4.
2. docs/model_methodology.md §7 and the debt part of §10.
3. docs/assumptions_and_limitations.md §2.5 (grant), §2.8 (HAM repayment profile), §2.10 (sculpting) and the funding part of §3.
4. Code: `funding.py` (`_pro_rata`, then `idc_by_iteration`, then `_equity_first`); `debt.py` (`annuity_payment`, `contractual_principal`, `sculpted_schedule`); `model._size_debt`.

**Try it**

| Do this | You should get |
|---|---|
| By hand: construction-year-1 IDC = 0.5 × 0.10 × 0.70 × 300 ÷ (1 − 0.5 × 0.10 × 0.70) | 10.88; debt draw = 0.70 × (300 + 10.88) = 217.62. Compare with Financial statements |
| Project assumptions: repayment profile `equal` | Min DSCR 0.99x in op year 1, a default; Equity IRR 18.77%. The annuity gives 1.26x (overview.md §11.4) |
| Profile `sculpted` | DSCR 1.96x in most years but 1.65x in op year 1 and 1.92x in op year 5; Equity IRR 21.58%. Work out why those two years differ |
| Equity mode `equity_first` | IDC falls from 113.08 to 77.37; debt 754.16 |
| Sizing `gearing_and_dscr`, target DSCR 1.30 | Debt falls from 779.15 to 754.29 (gearing 67.98%); min DSCR exactly 1.30x |
| Gearing 80% | Debt 904.51; min DSCR 1.08x; Equity IRR 22.89% |

**Be ready to explain**

- Sources = uses, and why debt = gearing × (TPC − grant).
- Why IDC is circular, how the closed form solves it, and why check C04 re-solves it by plain iteration; the mid-year drawdown convention.
- The four repayment profiles and when each suits a project; why equal principal fails the toll road in year 1.
- Sculpting, the negative-principal pitfall and the floor rule.
- Debt sizing as the smaller of the gearing limit and the DSCR limit; why the HAM loan is sculpted.
- What happens when the loan would mature after the concession ends.

**Hand check:** HC2, annuity payment: 779.15 × 0.10 ÷ (1 − 1.10⁻¹⁵) = 102.44. HC5, op year 15: opening debt 93.13, principal 93.13, closing debt 0.00.

**Also:** the reference for the VGF scheme (the grant is fixed at award; assumptions §2.5). Slides: sources and uses (chart 1), debt outstanding (chart 4), repayment profiles (chart 8).

### 10.4 P3: Revenue, operating costs, tax, CFADS and waterfall

You explain where the money comes from, what it costs to run the asset, and how cash reaches lenders and then equity.

**Owns:** `revenue.py`, `opex.py`, `tax.py`, `cashflow.py`. Tests: `test_revenue.py`, `test_tax.py`, `test_cashflow.py` (31).

**Read, in this order**

1. overview.md §3.3 (the three project types), §9.5–§9.8, §9.10–§9.11, §11.2.
2. docs/model_methodology.md §8, §9, the tax and CFADS part of §10, and §11.
3. docs/assumptions_and_limitations.md §2.3–§2.4 (MMRA), §2.7 (HAM end date), §2.9 (capacity) and the tax, HAM and waterfall parts of §3.
4. Code: `revenue.py` (`toll_revenue`, `metro_revenue`, `ham_revenue`), `opex.py`, `tax.py` (`tax_with_losses`), `cashflow.py` (`build_waterfall`).

**Try it**

| Do this | You should get |
|---|---|
| By hand: op-year-1 toll revenue = 24,000 × 0.85 × 200 × 365 ÷ 10⁷ | 148.92 (0.85 is the ramp-up factor) |
| Project assumptions: leakage 10% | Op-year-1 revenue 134.03 |
| Financial statements: tax by year | Op year 1: 0 (a loss of 14.47 is carried forward). Op year 2: 0.47 (the loss is used up). Op year 5: 3.42 (resurfacing year). Explain each |
| Switch to HAM, traffic shortfall 30% | Revenue unchanged. Completion cost = 60% × 1,000 × 1.05² = 661.50; construction support 412.00 |
| Toll: DSRA 6 months | DSCR unchanged at 1.26x, but Equity IRR falls from 20.02% to 18.86%. Why? |
| Toll: MMRA on, position `in_cfads` | Op-year-5 DSCR rises from 1.39x to 1.86x, but op-year-1 DSCR falls from 1.26x to 1.14x, below the covenant. Why? |

**Be ready to explain**

- The toll revenue formula, and why ramp-up multiplies rather than compounds.
- Metro fare revisions every three years and non-fare revenue.
- The HAM payment mechanism: 40% construction support, then 60% as 30 semi-annual instalments with interest, plus O&M payments, all indexed and all based on the bid project cost. That is why HAM carries no traffic risk but does carry cost-overrun risk.
- EBITDA vs CFADS.
- Depreciation and loss carry-forward, and why Project IRR uses a separate unlevered tax.
- The waterfall order; what the DSRA, MMRA and lock-up do; what sponsor support means.

**Hand check:** HC4, op year 5: revenue 230.68, O&M 24.31, major maintenance 60.78, tax 3.42, CFADS 142.18, DSCR 1.39x.

**Also:** check the HAM Model Concession Agreement on whether the annuity period runs from the actual COD (assumptions §2.7). For Chapter 8, collect one or two limitations from each person. Slides: revenue and ramp-up (chart 2), the HAM payment mechanism, CFADS vs debt service (chart 3).

### 10.5 P4: Lender metrics, returns, scenarios and sensitivity

You explain whether each project is bankable and worth investing in, and how that changes under stress. You hold the main findings ([Section 7](#7-scenarios-and-sensitivity)).

**Owns:** `metrics.py`, `scenarios.py`, `config/scenarios.yaml`. Tests: `test_metrics.py`, `test_scenarios.py` (38).

**Read, in this order**

1. overview.md §3.4, §9.12–§9.13, §10, §11.3, §11.5.
2. docs/model_methodology.md §12–§13.
3. docs/assumptions_and_limitations.md §2.2, §2.11, §2.12 and §4 (the metro and HAM calibrations).
4. Code: `metrics.py` (`irr`, `cover_ratio_series`, `compute_metrics`); `scenarios.py` (`run_scenarios`, `break_even_shortfall`, `tornado`).

**Try it**

| Do this | You should get |
|---|---|
| By hand: op-year-1 DSCR = 128.92 ÷ 102.44; LLCR at COD = 1,489.13 ÷ 779.15 | 1.2585x; 1.9112x |
| Sidebar: traffic shortfall 20% | Min DSCR 0.97x, in red; below 1.00x in op years 1 and 5 |
| Scenario analysis: break-even | DSCR reaches 1.00x at a 17.78% shortfall; Equity IRR reaches the 15% hurdle at 16.01% |
| Sidebar: rate shock +100 bp | Project IRR stays at 13.94%; Equity IRR 19.08%. Why does Project IRR not move? |
| Metro, Project assumptions: grant 0% | Min DSCR 0.79x; Equity IRR 13.44%. The project fails without VGF |
| HAM: scenario Traffic −20%, then Cost +20% | The first is identical to the base (1.45x, 16.49%); the second cuts Equity IRR to 3.00% |

**Be ready to explain**

- DSCR (minimum vs average, and which years count), LLCR, PLCR and ICR; typical covenants by project type.
- Project IRR vs Equity IRR, before and after grant; why leverage raises Equity IRR.
- The NPV convention (valued at financial close, like Excel's `NPV()`), and why the IRR solver reports nothing rather than guessing when there are several roots.
- How the scenario engine works, and why it can never corrupt the base case.
- How to read the scenario table, the two-way table, the tornado and the break-even, and the lender's view of each project type.

**Hand check:** HC3, op year 1 (the minimum-DSCR year): revenue 148.92 → CFADS 128.92 → interest 77.92 + principal 24.52 → DSCR 1.2585x. Then redo it with a 20% shortfall; you should get 0.97x.

**Also:** primary sources for the lender thresholds (Yescombe, the Model Concession Agreements, term sheets; overview.md §19). Slides: base-case results, scenario comparison (chart 5), tornado (chart 6), heat map (chart 7), break-even.

### 10.6 P5: Validation, dashboard and outputs

You show that the numbers can be trusted, and you run the live demo.

**Owns:** `checks.py`, `export.py`, `report_charts.py`, `__main__.py`, `app/dashboard.py`, `.streamlit/config.toml`, `validation/`, `outputs/`. Tests: `test_checks.py`, `test_worked_example.py`, `test_export.py` (48).

**Read, in this order**

1. overview.md §11 (the worked example the tests pin), §12 (validation plan), §14 (dashboard and charts), §15 (role of AI).
2. docs/model_methodology.md §14; docs/assumptions_and_limitations.md §1, §2.1, §2.13; docs/ai_usage_log.md.
3. Code: `checks.py` (`run_checks`, `hand_check`); `dashboard.py`, starting with the app shell at the end of the file (sidebar and model run), then `effective_raw` and `run_cached` near the top, then the page functions; `export.py`.

**Try it**

| Do this | You should get |
|---|---|
| `python -m pytest` | 197 passed |
| `python -m ppp_model hand-check` | "37 of 37 items agree within 0.01" |
| Dashboard, Validation page, base case | Every integrity check passes |
| Sidebar: traffic shortfall 20% | Financial warnings appear (DSCR below 1.00x) but the integrity checks still pass. Explain the difference |
| `python -m ppp_model export --type ham` | `outputs/ppp_model_ham_base.xlsx` with 15 sheets, including HAM_Annuity |
| `python -m ppp_model charts --type toll` | 8 PNG files in `outputs/charts/toll/` |

**Be ready to explain**

- Integrity vs financial checks, and what C01, C04, C06, C08, C12, C13 and C15 test.
- Why the hand check is independent of the model code.
- How the tests pin the worked example, and what the two rounding slips in the specification are.
- Why `dashboard.py` does no finance maths; how inputs reach the model ([Section 5.2](#52-where-the-inputs-come-from)); why edits on the assumptions page are not saved; why results are cached.
- What each Excel sheet contains.
- What AI produced and how each part was verified.

**Hand check:** collect everyone's calculator results into the hand-check record, compare them with `validation/hand_check.md`, the HandCheck sheet and the Validation page, and fill in the "Your verification" row of `docs/ai_usage_log.md`. If the instructor wants handwritten workings, collect the scans in `validation/hand_check_scans/`.

**Also:** own the AI usage log (everyone adds a row for AI help with their own report sections), the slide template and assembly, and the live demo.

### 10.7 What everyone must know

Anyone may be asked these, whatever their area.

1. What the tool does, in two sentences, and how toll, metro and HAM differ in where revenue comes from and who carries traffic risk.
2. The toll base case: cost ₹1,113 Cr, 70% debt (₹779 Cr), IDC ₹113 Cr, min DSCR 1.26x in op year 1, LLCR 1.91x, Project IRR 13.9%, Equity IRR 20.0%.
3. DSCR, LLCR, Project IRR and Equity IRR in one sentence each, and why Equity IRR is higher than Project IRR.
4. Why op year 1 is the tightest year, and why DSCR dips in op year 5.
5. The toll road stops covering its debt service at a 17.8% traffic shortfall.
6. Repayment shape matters: equal principal fails in year 1 (0.99x) where the annuity passes (1.26x).
7. The metro needs its 40% grant (0.79x without it).
8. HAM removes traffic risk but not cost risk: traffic −20% changes nothing; cost +20% cuts Equity IRR from 16.5% to 3.0%.
9. How we validated: 197 tests, 26 automated checks, the 37-item hand check, the specification's worked example reproduced, and our own calculator check.
10. What AI did and how we checked it, and the main limitations: annual periods, one debt tranche, simplified tax, illustrative metro and HAM inputs.

### 10.8 Order of work

1. **Setup** (everyone): install, run `python -m pytest`, open the dashboard.
2. **Study your area**: the reading list, then the *Try it* table. Write down anything you cannot explain.
3. **Teach-back**: each person explains their area to the others in order, P1 to P5, in about 15 minutes, using the dashboard. The others ask questions from that person's *Be ready to explain* list.
4. **Calculator hand checks**: each person does theirs and sends it to P5.
5. **Report**: each person drafts their chapters; P1 edits the whole report for consistency.
6. **Slides and rehearsal**: one deck, outlined below. P5 assembles it.

| # | Slide | Owner | Material |
|---|---|---|---|
| 1 | Title and team | P1 | |
| 2 | The problem; toll vs metro vs HAM | P1 | overview.md §1, §3 |
| 3 | What we built and how it calculates | P1 | Section 5.1 |
| 4 | Sources and uses; IDC | P2 | chart 1 |
| 5 | Debt schedule and repayment profiles | P2 | charts 4, 8 |
| 6 | Revenue and ramp-up; HAM payments | P3 | chart 2 |
| 7 | CFADS vs debt service | P3 | chart 3 |
| 8 | Base-case results | P4 | Section 6 |
| 9 | Scenarios | P4 | chart 5 |
| 10 | Sensitivity: tornado, heat map, break-even | P4 | charts 6, 7 |
| 11 | Validation | P5 | Section 9 |
| 12 | Live dashboard demo | P5 | |
| 13 | Role of AI and how we checked it | P5 | docs/ai_usage_log.md |
| 14 | Limitations and conclusions | P3, P1 | |

The charts are in `outputs/charts/<type>/`, numbered as in overview.md §14.3.

### 10.9 Remaining-work tracker

- [ ] Open questions answered by the instructor (overview.md §18): P1
- [ ] Metro and HAM inputs confirmed or replaced: P1 changes the YAML, P4 re-reads the results, P5 regenerates the outputs
- [ ] Calculator hand checks HC1–HC5: P1 to P4; record and AI-log row: P5
- [ ] Sources: lender thresholds (P4), VGF scheme (P2), HAM concession agreement (P3)
- [ ] Report chapters 1–9: as in 10.1; final edit: P1
- [ ] AI usage log rows for the report and slides: everyone; P5 collates
- [ ] Slides and live demo: P5 assembles, everyone presents their part
- [ ] Rehearsal: everyone

## 11. Where to look things up

| If you need | Look in |
|---|---|
| A concept, a term or the specification's formula | [overview.md](overview.md): glossary §4, formulas §9 |
| A formula exactly as the code implements it | [docs/model_methodology.md](docs/model_methodology.md) |
| Why the build differs from the specification | [docs/assumptions_and_limitations.md](docs/assumptions_and_limitations.md) |
| Every number for every year | Dashboard → Financial statements, or the Excel workbook |
| What AI did and how it was checked | [docs/ai_usage_log.md](docs/ai_usage_log.md) |
