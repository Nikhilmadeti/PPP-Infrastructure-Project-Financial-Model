"""README Section 11: the built model must reproduce the worked example (±0.01, README §12.2).

The README tables are rounded to two decimals, so every comparison uses abs=0.01 (money, ratios)
or 0.01 percentage points (IRRs). Two README figures are half-cent rounding slips that still sit
inside this tolerance; they are pinned precisely in test_readme_rounding_discrepancies.
"""

import numpy as np
import pytest

from conftest import op, run_with

TOL = 0.01
TOL_PCT = 1e-4  # 0.01 percentage points

# Table 11.1: year -> (capex, opening debt, IDC, uses, debt draw, equity, closing debt)
TABLE_11_1 = {
    1: (300.00, 0.00, 10.88, 310.88, 217.62, 93.26, 217.62),
    2: (400.00, 217.62, 37.06, 437.06, 305.94, 131.12, 523.56),
    3: (300.00, 523.56, 65.14, 365.14, 255.59, 109.54, 779.15),
}

# Table 11.2: op year -> (revenue, O&M, MMR, tax, CFADS, opening, interest, principal, closing, DS, DSCR)
TABLE_11_2 = {
    1: (148.92, 20.00, 0.00, 0.00, 128.92, 779.15, 77.92, 24.52, 754.63, 102.44, 1.26),
    2: (178.29, 21.00, 0.00, 0.47, 156.82, 754.63, 75.46, 26.98, 727.65, 102.44, 1.53),
    3: (201.04, 22.05, 0.00, 10.26, 168.73, 727.65, 72.77, 29.67, 697.98, 102.44, 1.65),
    4: (215.35, 23.15, 0.00, 14.33, 177.87, 697.98, 69.80, 32.64, 665.34, 102.44, 1.74),
    5: (230.68, 24.31, 60.78, 3.42, 142.18, 665.34, 66.53, 35.90, 629.44, 102.44, 1.39),
    6: (247.11, 25.53, 0.00, 23.45, 198.13, 629.44, 62.94, 39.49, 589.94, 102.44, 1.93),
    7: (264.70, 26.80, 0.00, 28.55, 209.35, 589.94, 58.99, 43.44, 546.50, 102.44, 2.04),
    8: (283.55, 28.14, 0.00, 34.05, 221.36, 546.50, 54.65, 47.79, 498.71, 102.44, 2.16),
    9: (303.74, 29.55, 0.00, 39.98, 234.21, 498.71, 49.87, 52.57, 446.14, 102.44, 2.29),
    10: (325.36, 31.03, 77.57, 26.85, 189.92, 446.14, 44.61, 57.82, 388.32, 102.44, 1.85),
    11: (348.53, 32.58, 0.00, 53.27, 262.68, 388.32, 38.83, 63.61, 324.72, 102.44, 2.56),
    12: (373.35, 34.21, 0.00, 60.71, 278.43, 324.72, 32.47, 69.97, 254.75, 102.44, 2.72),
    13: (399.93, 35.92, 0.00, 68.73, 295.28, 254.75, 25.47, 76.96, 177.79, 102.44, 2.88),
    14: (428.40, 37.71, 0.00, 77.38, 313.31, 177.79, 17.78, 84.66, 93.13, 102.44, 3.06),
    15: (458.90, 39.60, 99.00, 61.80, 258.51, 93.13, 9.31, 93.13, 0.00, 102.44, 2.52),
}
TAIL_ROWS = {16: (491.58, 41.58, 0.00, 96.78, 353.21), 17: (526.58, 43.66, 0.00, 105.07, 377.85)}

PROJECT_CF = [-300, -400, -300, 111.28, 132.51, 148.74, 158.63, 123.76, 180.62, 192.83, 205.93,
              219.98, 177.02, 251.23, 268.58, 287.19, 307.16, 254.49, 351.54, 376.18]
EQUITY_CF = [-93.26, -131.12, -109.54, 26.48, 54.38, 66.29, 75.43, 39.74, 95.70, 106.91, 118.92,
             131.77, 87.48, 160.24, 175.99, 192.84, 210.87, 156.07, 353.21, 377.85]


@pytest.mark.parametrize("year", sorted(TABLE_11_1))
def test_table_11_1_construction_funding_and_idc(toll_res, year):
    fu = toll_res.funding
    i = year - 1
    capex, opening, idc, uses, draw, equity, closing = TABLE_11_1[year]
    assert fu.capex[i] == pytest.approx(capex, abs=TOL)
    assert fu.opening_debt[i] == pytest.approx(opening, abs=TOL)
    assert fu.idc[i] == pytest.approx(idc, abs=TOL)
    assert fu.uses[i] == pytest.approx(uses, abs=TOL)
    assert fu.debt_draw[i] == pytest.approx(draw, abs=TOL)
    assert fu.equity[i] == pytest.approx(equity, abs=TOL)
    assert fu.closing_debt[i] == pytest.approx(closing, abs=TOL)


def test_table_11_1_totals(toll_res):
    mt = toll_res.metrics
    assert mt.capex == pytest.approx(1000.00, abs=TOL)
    assert mt.idc == pytest.approx(113.08, abs=TOL)
    assert mt.total_project_cost == pytest.approx(1113.08, abs=TOL)
    assert mt.debt == pytest.approx(779.15, abs=TOL)
    assert mt.equity == pytest.approx(333.92, abs=TOL)
    assert mt.debt / mt.total_project_cost == pytest.approx(0.70, abs=1e-12)  # "779.15 / 1,113.08 = 70.0%"
    assert mt.idc / mt.capex == pytest.approx(0.113, abs=5e-4)  # "IDC is 11.3% of hard cost"


@pytest.mark.parametrize("k", sorted(TABLE_11_2))
def test_table_11_2_operations(toll_res, k):
    r, a = toll_res, toll_res.annual
    i = op(r, k)
    rev, om, mmr, tax, cfads, opening, interest, principal, closing, ds, dscr = TABLE_11_2[k]
    assert r.revenue.total[i] == pytest.approx(rev, abs=TOL)
    assert r.opex.om[i] == pytest.approx(om, abs=TOL)
    assert r.opex.mmr[i] == pytest.approx(mmr, abs=TOL)
    assert r.tax.levered.tax[i] == pytest.approx(tax, abs=TOL)
    assert r.cfads[i] == pytest.approx(cfads, abs=TOL)
    assert r.debt.opening[i] == pytest.approx(opening, abs=TOL)
    assert r.debt.interest[i] == pytest.approx(interest, abs=TOL)
    assert r.debt.principal[i] == pytest.approx(principal, abs=TOL)
    assert r.debt.closing[i] == pytest.approx(closing, abs=TOL)
    assert r.debt.debt_service[i] == pytest.approx(ds, abs=TOL)
    assert r.dscr[i] == pytest.approx(dscr, abs=TOL)
    assert a.loc[i + 1, "DSCR"] == pytest.approx(dscr, abs=TOL)  # same number in the annual table


@pytest.mark.parametrize("k", sorted(TAIL_ROWS))
def test_table_11_2_tail_years(toll_res, k):
    r = toll_res
    i = op(r, k)
    rev, om, mmr, tax, cfads = TAIL_ROWS[k]
    assert r.revenue.total[i] == pytest.approx(rev, abs=TOL)
    assert r.opex.om[i] == pytest.approx(om, abs=TOL)
    assert r.tax.levered.tax[i] == pytest.approx(tax, abs=TOL)
    assert r.cfads[i] == pytest.approx(cfads, abs=TOL)
    assert r.debt.opening[i] == 0.0 and r.debt.debt_service[i] == 0.0
    assert np.isnan(r.dscr[i])  # "n/a (tail)"


def test_depreciation_and_year_one_tax_loss(toll_res):
    tx = toll_res.tax.levered
    i1, i2 = op(toll_res, 1), op(toll_res, 2)
    assert tx.depreciation[i1] == pytest.approx(1113.0751 / 17, abs=1e-4)
    assert tx.depreciation[i1] == pytest.approx(65.4750, abs=1e-4)
    assert tx.pbt[i1] == pytest.approx(-14.47, abs=TOL)
    assert tx.loss_cf[i1] == pytest.approx(14.47, abs=TOL)  # carried forward ...
    assert tx.loss_used[i2] == pytest.approx(14.47, abs=TOL)  # ... and used in year 2
    assert tx.loss_cf[i2] == 0.0


def test_section_11_3_headline_results(toll_res):
    mt = toll_res.metrics
    assert mt.min_dscr == pytest.approx(1.26, abs=TOL)
    assert mt.min_dscr_op_year == 1
    assert mt.avg_dscr == pytest.approx(2.11, abs=TOL)
    assert mt.llcr_cod == pytest.approx(1.91, abs=TOL)
    assert mt.llcr_cod * mt.debt == pytest.approx(1489.13, abs=TOL)  # PV of CFADS yrs 1-15 at 10%
    assert mt.project_irr.value == pytest.approx(0.1394, abs=TOL_PCT)
    assert mt.equity_irr.value == pytest.approx(0.2002, abs=TOL_PCT)
    assert mt.tail_years == 2
    assert mt.final_repayment_op_year == 15
    assert toll_res.debt.debt_service[op(toll_res, 1)] == pytest.approx(102.44, abs=TOL)


def test_section_11_3_irr_cash_flows(toll_res):
    np.testing.assert_allclose(toll_res.project_cf, PROJECT_CF, atol=TOL)
    np.testing.assert_allclose(toll_res.equity_cf, EQUITY_CF, atol=TOL)


def test_leverage_effect_section_9_13(toll_res):
    mt = toll_res.metrics
    after_tax_cost_of_debt = 0.10 * (1 - 0.2517)
    assert after_tax_cost_of_debt == pytest.approx(0.0748, abs=5e-5)
    assert mt.project_irr.value > after_tax_cost_of_debt
    assert mt.equity_irr.value > mt.project_irr.value


def test_section_11_4_equal_principal_defaults_in_year_one(toll_raw):
    res = run_with(toll_raw, debt={"profile": "equal"})
    mt = res.metrics
    assert mt.min_dscr == pytest.approx(0.99, abs=TOL)
    assert mt.min_dscr_op_year == 1
    assert mt.equity_irr.value == pytest.approx(0.1877, abs=TOL_PCT)
    assert mt.dscr_below_one_years == (1,)


def test_readme_rounding_discrepancies(toll_res, toll_raw):
    """Pinned precisely: README rounds 373.3450 to 373.35 and 1.4445 to 1.45 (double rounding)."""
    assert toll_res.revenue.total[op(toll_res, 12)] == pytest.approx(373.344971, abs=1e-6)
    combined = run_with(toll_raw, stress={"demand_shortfall": 0.20, "cost_overrun": 0.20})
    assert combined.metrics.avg_dscr == pytest.approx(1.44455, abs=1e-5)
    assert round(combined.metrics.avg_dscr, 2) == 1.44
