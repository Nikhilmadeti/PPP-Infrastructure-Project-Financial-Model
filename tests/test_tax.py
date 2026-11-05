"""Depreciation, tax and loss carry-forward (README §9.7)."""

import numpy as np
import pytest

from conftest import op, run_with
from ppp_model import build_inputs, deep_merge
from ppp_model.tax import straight_line_depreciation, tax_with_losses
from ppp_model.timeline import build_timeline


def readme_tax(pbt, rate):
    """The README §9.7 recurrence, written out literally."""
    loss_bf, tax = 0.0, []
    for p in pbt:
        taxable = p - loss_bf
        tax.append(rate * max(0.0, taxable))
        loss_bf = max(0.0, -taxable)
    return np.array(tax)


def test_unlimited_carry_forward_equals_the_readme_recurrence():
    rng = np.random.default_rng(725)
    for _ in range(50):
        pbt = rng.normal(5, 40, size=25)
        np.testing.assert_allclose(tax_with_losses(pbt, 0.2517, None)[4], readme_tax(pbt, 0.2517), atol=1e-12)


def test_limited_carry_forward_expires_old_losses():
    pbt = np.array([-100.0] + [0.0] * 8 + [150.0])  # loss in year 1, profit in year 10
    loss_bf, used, expired, taxable, tax, loss_cf = tax_with_losses(pbt, 0.25, 8)
    assert expired[9] == pytest.approx(100.0)  # 9 years later: past the 8-year limit
    assert used[9] == 0.0 and tax[9] == pytest.approx(0.25 * 150.0)
    within = tax_with_losses(np.array([-100.0] + [0.0] * 7 + [150.0]), 0.25, 8)
    assert within[1][8] == pytest.approx(100.0)  # used in year 9, within the limit
    assert within[4][8] == pytest.approx(0.25 * 50.0)


def test_losses_are_used_oldest_first():
    pbt = np.array([-50.0, -30.0, 0.0, 0.0, 60.0, 0.0, 0.0, 0.0, 0.0, 100.0])
    _, used, expired, _, _, loss_cf = tax_with_losses(pbt, 0.25, 8)
    assert used[4] == pytest.approx(60.0)  # all 50 from year 1 + 10 from year 2
    assert expired[9] == 0.0 and used[9] == pytest.approx(20.0)  # year-2 balance still alive in year 10


def test_year_one_loss_used_in_year_two(toll_res):
    tx = toll_res.tax.levered
    i1, i2 = op(toll_res, 1), op(toll_res, 2)
    assert tx.pbt[i1] == pytest.approx(-14.4703, abs=1e-4)
    assert tx.tax[i1] == 0.0
    assert tx.taxable_income[i2] == pytest.approx(tx.pbt[i2] - 14.4703, abs=1e-4)
    assert tx.tax[i2] == pytest.approx(0.47, abs=0.01)


def test_tax_uses_interest_from_the_debt_schedule(toll_res):
    tx, db = toll_res.tax.levered, toll_res.debt
    np.testing.assert_array_equal(tx.interest, db.interest)
    i = op(toll_res, 5)
    expected = toll_res.opex.ebitda[i] - tx.depreciation[i] - db.interest[i]
    assert tx.pbt[i] == pytest.approx(expected)
    assert tx.tax[i] == pytest.approx(0.2517 * 13.5888, abs=1e-4)  # hand check 4: 3.4203


def test_unlevered_tax_has_no_interest_and_excludes_idc(toll_res):
    unlev = toll_res.tax.unlevered
    i1 = op(toll_res, 1)
    assert unlev.depreciation[i1] == pytest.approx(1000 / 17)
    assert unlev.interest.sum() == 0.0
    assert unlev.tax[i1] == pytest.approx(0.2517 * (128.92 - 1000 / 17), abs=1e-4)
    assert toll_res.project_cf[i1] == pytest.approx(111.28, abs=0.01)  # README §11.3 project cash flow
    assert unlev.tax.sum() > toll_res.tax.levered.tax.sum()  # no debt tax shield for Project IRR


def test_depreciation_totals_the_capitalised_cost(toll_res):
    assert toll_res.tax.levered.depreciation.sum() == pytest.approx(toll_res.funding.total_project_cost)
    assert toll_res.tax.depreciable_cost == pytest.approx(1113.0751, abs=1e-4)


def test_depreciation_life_longer_than_operations_is_written_off_at_handback(toll_raw):
    inp = build_inputs(toll_raw)
    tl = build_timeline(inp)
    dep = straight_line_depreciation(1000.0, tl, 20)
    assert dep[tl.index_of_op_year(1)] == pytest.approx(50.0)
    assert dep[-1] == pytest.approx(50.0 + 1000.0 * 3 / 20)
    assert dep.sum() == pytest.approx(1000.0)
    short = straight_line_depreciation(1000.0, tl, 10)
    assert short[tl.index_of_op_year(10)] == pytest.approx(100.0) and short[tl.index_of_op_year(11)] == 0.0


def test_depreciation_net_of_grant(toll_raw):
    net = run_with(toll_raw, funding={"grant_pct": 0.2})
    gross = run_with(toll_raw, funding={"grant_pct": 0.2}, tax={"depreciation_net_of_grant": False})
    assert net.tax.depreciable_cost == pytest.approx(net.funding.total_project_cost - 200.0)
    assert gross.tax.depreciable_cost == pytest.approx(gross.funding.total_project_cost)
    assert net.tax.levered.tax.sum() > gross.tax.levered.tax.sum()


def test_tax_is_never_negative_even_in_deep_stress(toll_raw):
    res = run_with(toll_raw, stress={"demand_shortfall": 0.6})
    assert res.tax.levered.tax.min() >= 0.0
    assert res.tax.levered.loss_cf.max() > 0.0
