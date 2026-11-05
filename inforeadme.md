# About this project: the PPP Infrastructure Financial Model

*A plain-language guide for anyone opening this project for the first time: students, the instructor, engineers, bankers or anyone curious. No finance background is assumed. Every technical term is explained the first time it appears.*

---

## Contents

1. [The project in one minute](#1-the-project-in-one-minute)
2. [What is a PPP?](#2-what-is-a-ppp)
3. [The problem we are solving](#3-the-problem-we-are-solving)
4. [Why we built this](#4-why-we-built-this)
5. [What the tool does](#5-what-the-tool-does)
6. [The key terms, in plain words](#6-the-key-terms-in-plain-words)
7. [A worked story: the toll road](#7-a-worked-story-the-toll-road)
8. [What-if testing and what it teaches](#8-what-if-testing-and-what-it-teaches)
9. [Who benefits, and how](#9-who-benefits-and-how)
10. [How to use the tool](#10-how-to-use-the-tool)
11. [The AI assistant inside the tool](#11-the-ai-assistant-inside-the-tool)
12. [How we know the numbers are right](#12-how-we-know-the-numbers-are-right)
13. [How AI was used to build it](#13-how-ai-was-used-to-build-it)
14. [What the tool does not do](#14-what-the-tool-does-not-do)
15. [Frequently asked questions](#15-frequently-asked-questions)
16. [Where to go next](#16-where-to-go-next)

---

## 1. The project in one minute

Big infrastructure such as highways and metro lines costs thousands of crores. In India much of it is built as a **Public-Private Partnership (PPP)**: a private company borrows most of the money, builds the asset, runs it for 15 to 35 years, and repays the loans from the money the asset earns.

Whether such a project survives depends less on the engineering than on **how the money is arranged**: how much is borrowed, how fast it is repaid, and what happens if traffic is lower or construction costs more than planned. Many Indian toll roads ran into financial distress for exactly these reasons.

**This tool is a financial model of a PPP project.** You describe a toll road, a metro line or a Hybrid Annuity Model (HAM) road. The tool then works out, year by year for the whole concession:

- how much the project really costs, including the interest that builds up during construction;
- how it is funded (loan and owner's money);
- how much it earns and spends;
- whether it can repay its lenders every single year;
- what return the investors make.

It then **stress-tests** the project. You can cut traffic by 20%, add 20% to the cost, delay construction or raise interest rates, and see straight away whether the project still holds up. That is the "decision support" part: it helps a lender, a developer or a government officer answer *"Is this project financially sound, and how much can go wrong before it fails?"*

It was built as the course project for **CE725 Construction Economics and Finance, Topic 9: PPP / Infrastructure Project Financial Model**.

---

## 2. What is a PPP?

A **Public-Private Partnership** is a long-term contract in which the government lets a private company **design, build, finance and operate** a public asset for a fixed period, called the **concession period**. At the end, the asset is handed back to the government.

Think of it like this: the government needs a highway but does not want to pay for all of it upfront. A private company agrees to build it with its own money and loans, and in return is allowed to collect tolls for, say, 20 years.

### The parties involved

```
        Government authority (e.g. NHAI, a metro rail corporation)
           │   Concession agreement: rights, duties, period,
           │   and any government support (grant / annuity payments)
           ▼
Sponsors ──equity──►  Project company (SPV)  ◄──loans── Lenders (banks)
                       │                ▲
       builds through  │                │  tolls / fares / government payments
                       ▼                │
           Construction contractor    Road users / metro riders / the authority
           Operations contractor
```

| Party | Who they are | What they want |
|---|---|---|
| **Government authority** | The public body that owns the need (e.g. NHAI) | The asset built on time, at fair cost, with as little public money as possible |
| **Sponsor** (equity investor) | The private company behind the project | A good return on the money it puts in |
| **SPV** (Special Purpose Vehicle) | A separate company created just for this one project | To build, operate and repay its loans |
| **Lenders** | Banks and financial institutions | To be repaid on time, with interest |
| **Users** | Drivers, metro passengers | A good road or metro at a fair price |

**The key point:** lenders lend to the SPV, and they are repaid *only* from the project's own earnings, not from the sponsor's other businesses. This is called **project finance**. Lenders therefore study the project's cash flows very closely, and that is exactly what this tool models.

### The three project types in the tool

| | **BOT toll road** | **Metro (PPP)** | **HAM road** (Hybrid Annuity Model) |
|---|---|---|---|
| Who pays the SPV | Road users, through tolls | Passengers through fares, plus advertising, parking and property | The government, through fixed instalments |
| Who carries the traffic risk | The SPV | The SPV, mostly | The government. The SPV has none |
| Government support | A grant (Viability Gap Funding, VGF) if needed | Usually a large grant | 40% of the project cost paid during construction |
| Main risk for the SPV | Too few vehicles, cost overrun, delay | Too few riders, cost overrun, delay | Cost overrun, delay, interest rates |

*BOT means Build-Operate-Transfer.*

**Why HAM exists:** many Indian toll roads awarded around 2008 to 2013 ran into trouble because actual traffic fell well short of forecasts and land-acquisition delays raised costs. In 2016 the government introduced HAM to share the risk. The government pays 40% of the cost during construction and the rest as instalments over time, so the private company no longer depends on traffic.

---

## 3. The problem we are solving

A PPP can be a good project and still fail **because of how it is financed**:

- **Too much debt:** the yearly loan payments are larger than the cash the project earns. The project defaults.
- **Too little debt:** the sponsor must put in more of its own money, its return falls, and nobody wants to invest.
- **The wrong repayment shape:** traffic on a new road starts low and grows over years ("ramp-up"). If loan repayments are large from day one, the early years are squeezed even when the project is healthy in the long run.
- **Risks nobody tested:** a forecast that is 15% too optimistic, or a one-year construction delay, can turn a "bankable" project into a failed one.

In practice these questions are answered with large, complex spreadsheets that are hard to check and easy to get wrong. A student, a junior engineer or a government officer often cannot see *why* a project passes or fails.

**Our tool makes this visible.** It shows every year's numbers, explains which year is the weakest and why, and lets you move one assumption at a time to see the effect.

---

## 4. Why we built this

**For the course.** The brief asks for a working decision-support tool on a real construction-finance problem, built with AI assistance and **validated against hand calculations**. Topic 9 asks specifically for:

| The brief asks for | Where it is in the tool |
|---|---|
| Debt-equity structure | Funding: share of debt vs equity, grant, sources = uses |
| Interest during construction | Calculated exactly, then cross-checked a second way |
| Revenue ramp-up | Traffic or ridership starts low and grows to its mature level |
| DSCR and LLCR (lender metrics) | Every year, compared with the lender's minimum |
| Project IRR and Equity IRR | For the whole project and for the sponsor |
| Traffic-shortfall and cost-overrun scenarios | 11 ready-made scenarios plus sliders |
| Hand check of the debt schedule and DSCR | 37 items recomputed for selected years |

**For learning.** Building the model forced us to understand *why* lenders insist on certain ratios, *why* HAM was invented, and *why* the repayment pattern matters as much as the project itself (see [Section 8](#8-what-if-testing-and-what-it-teaches)).

**For practice.** The same questions are asked every day by infrastructure lenders, PPP developers and government agencies. A transparent, tested model is a useful teaching and screening tool.

---

## 5. What the tool does

```
   YOUR ASSUMPTIONS                     THE MODEL WORKS OUT, YEAR BY YEAR             RESULTS
 ┌──────────────────────┐          ┌──────────────────────────────────────┐   ┌─────────────────────┐
 │ Construction cost    │          │ 1. Timeline (construction, operation) │   │ Can it repay its    │
 │ Construction period  │          │ 2. Cost per year                      │   │ lenders every year? │
 │ Loan share, rate,    │   ──►    │ 3. Revenue, with ramp-up              │──►│ (DSCR, LLCR)        │
 │   tenor, repayment   │          │ 4. Operating costs and tax            │   │ Investor returns    │
 │ Traffic / ridership, │          │ 5. Funding + interest in construction │   │ (Project IRR,       │
 │   toll / fare        │          │ 6. Loan repayment schedule            │   │  Equity IRR, NPV)   │
 │ Operating costs, tax │          │ 7. Cash left for the owners           │   │ Bankable or not,    │
 │ Grant / support      │          │ 8. Lender and investor ratios         │   │  and why            │
 └──────────────────────┘          │ 9. Automatic error checks             │   └─────────────────────┘
                                   └──────────────────────────────────────┘
                         then repeats it all under stress: less traffic, higher cost, delay, higher rates
```

**What you get:**

- **An interactive dashboard** in the web browser with 8 pages: overview, assumptions, financial statements, debt analysis, scenarios, revenue, validation and export.
- **Stress sliders**: traffic shortfall, cost overrun (and who pays for it), construction delay and interest-rate change.
- **11 ready-made scenarios** and a verdict for each: *Bankable*, *Below lender covenant* or *Not bankable*.
- **Sensitivity tools**: a two-way table (traffic × cost), a tornado chart showing which assumption matters most, and a **break-even** finder ("how much can traffic fall before the project cannot pay its loans?").
- **Comparison of repayment patterns**: the same project under four loan-repayment shapes.
- **An Excel workbook** of the full model, CSV files and report-ready charts.
- **An AI assistant** that explains the results in plain language (see [Section 11](#11-the-ai-assistant-inside-the-tool)).
- **Built-in validation**: 26 automatic checks on every run, plus the hand check.

All amounts are in **₹ crore** (1 crore = 10 million rupees).

---

## 6. The key terms, in plain words

| Term | Plain meaning | Why it matters |
|---|---|---|
| **Concession period** | How long the private company may run the asset (e.g. 20 years) | All earnings must come within this period |
| **COD** (Commercial Operation Date) | The day the road or metro opens and starts earning | Before COD there is cost but no income |
| **Capex** | The cost of building the asset | The biggest number in the project |
| **Debt / Equity** | Borrowed money / the owners' own money | Debt is cheaper but must be repaid on schedule; equity takes the risk |
| **Gearing** | The share of the cost funded by debt (e.g. 70%) | More debt lifts owners' returns but raises the risk of default |
| **IDC** (Interest During Construction) | Interest on the loan while the asset is being built, when there is no income to pay it, so it is added to the loan | It makes the project cost more than the construction cost. A circular calculation the tool solves exactly |
| **Total Project Cost (TPC)** | Construction cost + contingency + fees + IDC | What actually has to be funded |
| **Ramp-up** | Traffic on a new road starts below its full level and grows over a few years | The first years are the hardest to pay loans in |
| **O&M** | Operation and maintenance costs | Paid before lenders get anything |
| **Major maintenance** | Big periodic jobs, e.g. resurfacing a road every 5 years | Creates "dip" years in cash flow |
| **CFADS** (Cash Flow Available for Debt Service) | Money left each year after operating costs and tax, available to pay the lenders | The cash lenders rely on |
| **Debt service** | That year's loan payment: interest + principal | What must be paid every year |
| **DSCR** (Debt Service Coverage Ratio) | CFADS ÷ debt service, for one year. **1.26x** means the project earned ₹1.26 for every ₹1 it owed that year | **Below 1.00x the project cannot pay its loan that year.** Lenders usually demand a minimum, e.g. 1.20x |
| **Covenant** | The minimum DSCR (or LLCR) the lender requires in the loan contract | Breaking it can block dividends or trigger default |
| **LLCR** (Loan Life Coverage Ratio) | Today's value of all future CFADS during the loan's life ÷ loan outstanding | Cover over the whole loan, not just one year |
| **Repayment profile** | The shape of loan repayment: equal principal, annuity (equal instalments), structured, or "sculpted" to match cash flow | The same project can pass or fail depending on this |
| **Project IRR** | The return the whole project earns on its total cost, ignoring how it is financed | Is the asset itself a good investment? |
| **Equity IRR** | The return the sponsor earns on its own money after lenders are paid | Will investors put money in? Compared with a **hurdle** (minimum acceptable return, e.g. 15%) |
| **NPV** (Net Present Value) | All future cash flows converted to today's money at a chosen rate (12% here), minus the investment | Positive means the project beats that rate |
| **VGF** (Viability Gap Funding) | A government grant that makes a socially useful but not fully profitable project viable | Without it, metros usually do not work financially |
| **DSRA** | Debt Service Reserve Account: a cash buffer kept for bad years | Lenders often require it |
| **Tail** | Years left in the concession after the loan is fully repaid | A safety margin for lenders |
| **Bankable** | Lenders would lend on these terms: all coverage ratios meet the covenants | The practical pass/fail test |

---

## 7. A worked story: the toll road

The main example in the tool is a **BOT toll road**: construction cost ₹1,000 crore, built over 3 years, with a 20-year concession. Here is what the model finds.

1. **Building it costs more than ₹1,000 crore.** During the 3 years of construction the loan builds up interest of **₹113.08 crore (IDC)**, so the total project cost is **₹1,113.08 crore**.
2. **Funding:** 70% debt, **₹779.15 crore**, and 30% equity, **₹333.92 crore**.
3. **The loan:** 15 years at 10%, repaid in equal annual instalments (annuity) of about **₹102.44 crore**.
4. **The weakest year is the first year of operation.** Traffic is still ramping up, but the full instalment is due. DSCR that year is **1.26x**, just above the lender's **1.20x** minimum. Later years are far more comfortable, with an average of **2.11x**.
5. **Over the loan's life the cover is healthy:** LLCR **1.91x** against a 1.30x minimum.
6. **Returns:** the project earns **13.94%** (Project IRR). The sponsor earns **20.02%** (Equity IRR), above its 15% hurdle, because borrowing at 10% to earn ~14% boosts the owners' return. NPV at 12% is **+₹131 crore**.
7. **The loan is fully repaid** by year 15 of operation, leaving a **2-year tail**.

**Verdict: bankable, but with little room to spare.** That last point is what the stress tests explore.

### The other two cases

| | Toll (BOT) | Metro | HAM |
|---|---:|---:|---:|
| Total project cost (₹ Cr) | 1,113 | 2,835 | 959 |
| Government support (₹ Cr) | none | 1,028 (40% grant) | 412 (40% of bid cost) |
| Minimum DSCR | 1.26x | 1.32x | 1.45x |
| Equity IRR (hurdle) | 20.0% (15%) | 19.9% (15%) | 16.5% (14%) |

The metro and HAM cost and financing figures are **illustrative assumptions** made by the team, not data from a real project. They show how the tool behaves for those project types.

---

## 8. What-if testing and what it teaches

**Toll road under stress:**

| What goes wrong | Minimum DSCR | Equity IRR | Verdict |
|---|---:|---:|---|
| Nothing (base case) | 1.26x | 20.0% | Bankable |
| Traffic 10% lower | 1.11x | 17.0% | Breaks the lender's minimum |
| Traffic 20% lower | 0.97x | 13.6% | **Cannot pay its loans** in some years |
| Construction cost +20% | 1.05x | 15.6% | Breaks the lender's minimum |
| Cost +20%, but paid by the owners | 1.26x | 14.5% | Lenders fine; owners below their hurdle |
| Construction delayed 1 year | 1.21x | 17.5% | Still bankable, just |
| Interest rates +1% | 1.18x | 19.1% | Breaks the lender's minimum |
| Traffic −20% **and** cost +20% | 0.81x | 9.4% | Not bankable |

**Break-even:** the toll road can survive a traffic shortfall of up to **17.8%**. Beyond that it cannot cover its loan payments.

### Four lessons the tool makes visible

1. **"Profitable" is not the same as "bankable."** The toll road earns a healthy return overall, yet a 10% traffic shortfall already breaks the lender's covenant. Traffic forecasts are the single biggest risk; the tornado chart confirms traffic and toll rate matter most.
2. **The weak years are predictable.** They are the first operating year (low traffic, full loan) and the resurfacing years. At a 30% traffic shortfall the worst year moves to year 5, the resurfacing year. A cash reserve sized only for the first year would not be enough.
3. **How you borrow matters as much as what you build.** On the *same* road, equal-principal repayment fails in year 1 (0.99x), an annuity just passes (1.26x), and a "sculpted" repayment that follows the cash flow gives 1.65x. Who pays for a cost overrun also changes who suffers: lenders or owners.
4. **Different PPP models move risk to different people.** The metro cannot work without a large government grant (its DSCR would be 0.79x without it). HAM is immune to traffic; the traffic slider has no effect at all. But a 20% cost overrun cuts HAM equity returns from 16.5% to 3.0%, because the government pays on the *bid* cost, not the actual cost. HAM moves traffic risk to the government and leaves construction risk with the builder.

---

## 9. Who benefits, and how

| User | Questions the tool helps answer | Benefit |
|---|---|---|
| **Lenders / bank credit teams** | Can the project repay every year? Which year is weakest? How much traffic loss or cost overrun before it fails? | Faster, transparent screening of loan proposals; covenant checks and break-even in one place |
| **Developers / sponsors** | What return will we make? How much debt can the project carry? Which repayment shape works best? What if we have to fund an overrun ourselves? | Structure the deal before bidding; see the downside before committing money |
| **Construction contractors (EPC)** | How sensitive is the project to cost overruns and delays? | Understand why lenders and sponsors care so much about cost and schedule control |
| **Government / PPP authorities** | Does this project need a grant (VGF)? How big? Toll-based or HAM? | Choose the right PPP model and support level; avoid awarding projects likely to fail |
| **Students and teachers** | How do IDC, DSCR, LLCR and IRR actually work, with real numbers? | Every number traceable year by year; change an input and see why the result changes |
| **Analysts and consultants** | Is my spreadsheet right? | An independently tested reference model with a published worked example |

**General benefits:**

- **Transparent:** every annual figure is visible, and every formula is documented in [docs/model_methodology.md](docs/model_methodology.md).
- **Fast:** a full scenario analysis that takes hours in a spreadsheet runs in seconds.
- **Safe to experiment:** changes in the dashboard never overwrite the saved base assumptions.
- **Trustworthy:** 197 automated tests, 26 automatic checks on every run, and an independent hand check (see [Section 12](#12-how-we-know-the-numbers-are-right)).
- **Free and local:** it runs on your own computer. Only the optional AI assistant sends anything outside.

---

## 10. How to use the tool

### Start it (first time)

You need Python 3.11 or newer. In PowerShell, inside the project folder:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
streamlit run app/dashboard.py
```

Your browser opens at **http://localhost:8501**. Next time, only the second and last lines are needed.

### Use it

1. **Choose the project type** in the left sidebar: toll road, metro or HAM.
2. **Read the Overview page.** Headline figures are coloured green (meets the lender's minimum or the investor's hurdle), amber (tight) or red (fails).
3. **Stress it.** Pick a ready-made scenario, or move the sliders: traffic shortfall, cost overrun (and whether debt + equity or equity alone pays for it), construction delay and interest-rate change. Every page updates instantly.
4. **Find out why.** *Debt analysis* shows the loan and DSCR year by year. *Revenue analysis* shows the traffic ramp-up. *Financial statements* shows every line item.
5. **Compare.** *Scenario analysis* runs all 11 scenarios side by side, with the two-way table, tornado chart and break-even.
6. **Change the base assumptions** on the *Project assumptions* page. Invalid inputs are rejected with an explanation.
7. **Check it.** The *Validation* page shows all automatic checks and the hand check.
8. **Take it away.** The *Export* page gives the Excel workbook, CSV files and the assumptions file.
9. **Ask questions.** Click **Ask the model** at the bottom right.

Command-line options (Excel export, report charts, hand check) are listed in [README.md](README.md) §3.

---

## 11. The AI assistant inside the tool

The **Ask the model** button opens a chat assistant powered by Google Gemini. Ask it things like *"Is this project bankable?"*, *"Why is the weakest year op year 1?"* or *"What is the difference between DSCR and LLCR?"*.

- It **explains** the numbers; it never calculates or changes them. With every question it receives the current project, scenario, slider positions, results, yearly table and the methodology documents, and it is instructed to use only those numbers.
- It **can still be wrong.** Check any figure it quotes against the dashboard tables.
- **Privacy:** your question and the current results are sent to Google. That is fine for these illustrative cases, but do not use it with confidential bid or bank data.
- **Setup:** it needs a free Gemini API key. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and paste the key in, or paste it into the chat panel. Never share the secrets file. If Google's servers are busy, the assistant retries and switches to another model automatically.

---

## 12. How we know the numbers are right

The course rule is that **every number must be verified against a manual calculation**. The tool is checked in four layers:

1. **Input validation:** wrong or inconsistent inputs (e.g. phasing that does not add up to 100%, or a loan longer than the concession) are rejected before anything is calculated.
2. **26 automatic checks on every run:** e.g. sources of money always equal uses; IDC calculated two different ways agrees; loan repayments add up to the loan; NPV at the IRR is zero. A failed check is shown on screen.
3. **197 automated tests**, including every number of the published worked example (toll road) to within ±0.01.
4. **Hand check:** 37 items (debt schedule, interest, DSCR for selected years) recomputed calculator-style, all in agreement. See [validation/](validation/).

While checking, we also found two small rounding slips in our own specification and a second weak year (year 5) that the specification had missed. These are documented in [docs/assumptions_and_limitations.md](docs/assumptions_and_limitations.md).

---

## 13. How AI was used to build it

In line with the course principle *"the AI builds with the team, not for the team"*:

- AI (Claude) helped draft the specification, write the calculation code, the dashboard and the tests, and set up the scenarios. The Gemini assistant explains results inside the tool.
- **Every AI-produced formula and number was checked** against the specification, the worked example and the hand check. Where AI got something wrong, it was corrected and recorded. One example: the first HAM draft had owners earning less than the loan cost (Equity IRR 6%), which was revised.
- All of this is logged in [docs/ai_usage_log.md](docs/ai_usage_log.md): what was asked, what AI produced, how it was verified, and what was changed.

---

## 14. What the tool does not do

To use the results responsibly, know the limits:

- **Annual periods only.** Real loans and HAM payments are often semi-annual or monthly.
- **One loan.** There are no multiple lenders or tranches, no refinancing, and no foreign-currency loans.
- **Simplified tax and working capital.** There is no full balance sheet or detailed Income-tax Act depreciation blocks.
- **Illustrative inputs.** The toll road follows our worked example. The metro and HAM costs and financing are our own assumptions, not a real project. Lender thresholds (e.g. 1.20x DSCR) are typical values that still need primary sources.
- **Whole-year delays only.** A half-year delay is rejected rather than approximated.
- **A model is not a decision.** It shows the consequences of the assumptions you give it. If the traffic forecast is wrong, the answer will be wrong too. Real decisions need due diligence, real data and professional judgement.

Planned extensions are listed in [docs/assumptions_and_limitations.md](docs/assumptions_and_limitations.md) §5.

---

## 15. Frequently asked questions

**Why does the traffic slider do nothing for HAM?**
Because under HAM the government pays the company fixed instalments, whatever the traffic. This is deliberate and is one of the key lessons of the tool.

**Why is the first operating year usually the weakest?**
Traffic is still ramping up, but the loan instalment is already at full size and the loan balance is at its highest.

**Why is Equity IRR higher than Project IRR?**
Because of leverage. The project borrows at about 10% and earns about 14% on the whole investment, and the difference goes to the owners. Leverage works in reverse when things go badly, which is why Equity IRR falls fastest in the stress cases.

**What does "Below lender covenant" mean if the DSCR is still above 1.00x?**
The project can pay its loan, but with less margin than the lender demands. In practice this can block dividends to the owners or let the lender step in. Below 1.00x it actually cannot pay.

**Do my changes on the dashboard overwrite the original data?**
No. Changes apply only to your browser session. To keep them, use Export → *Download assumptions (.yaml)*.

**Can I use this for a real project?**
As a learning and first-screening tool, yes, if you enter real, verified data. For an actual investment or lending decision it would need the extensions in Section 14 and a professional review.

---

## 16. Where to go next

| If you want… | Read |
|---|---|
| To run it and see the folder layout | [README.md](README.md) |
| The full specification, every formula and the worked example | [overview.md](overview.md) |
| Formulas exactly as coded | [docs/model_methodology.md](docs/model_methodology.md) |
| Assumptions, limitations, discrepancies found | [docs/assumptions_and_limitations.md](docs/assumptions_and_limitations.md) |
| How AI was used and checked | [docs/ai_usage_log.md](docs/ai_usage_log.md) |
| The hand check | [validation/hand_check.md](validation/hand_check.md) |
| The inputs themselves | [config/](config/) |
