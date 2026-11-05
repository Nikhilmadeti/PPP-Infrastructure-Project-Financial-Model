"""CFADS, reserves and the cash-flow waterfall (README §9.8, §9.10, §9.11)."""

import numpy as np
import pytest

from conftest import op, run_with


def identity_gap(res):
    wf = res.waterfall
    flows = (wf.cfads - wf.debt_service - wf.dsra_topup + wf.dsra_release + wf.dsra_draw - wf.mmra_contribution
             + wf.mmra_release - wf.lockup_trapped + wf.lockup_released - wf.distributions + wf.sponsor_support)
    return np.abs(flows).max()


def test_base_distributions_equal_cfads_minus_debt_service(toll_res):
    wf = toll_res.waterfall
    ops = slice(toll_res.timeline.cod_index, None)
    np.testing.assert_allclose(wf.distributions[ops], (wf.cfads - wf.debt_service)[ops])
    assert identity_gap(toll_res) < 1e-9


def test_dsra_funded_from_cash_flow_builds_then_releases(toll_raw):
    res = run_with(toll_raw, reserves={"dsra_months": 6})
    wf, db = res.waterfall, res.debt
    i1, i2, i15 = op(res, 1), op(res, 2), op(res, 15)
    cash_after_ds = res.cfads[i1] - db.debt_service[i1]  # 26.48: less than the 51.22 target
    target = 0.5 * db.debt_service[i2]
    assert cash_after_ds < target
    assert wf.dsra_topup[i1] == pytest.approx(cash_after_ds)  # a reserve cannot create cash ...
    assert wf.distributions[i1] == 0.0
    assert wf.dsra_closing[i2] == pytest.approx(0.5 * db.debt_service[op(res, 3)])  # ... target reached in year 2
    assert wf.dsra_release[i15] == pytest.approx(wf.dsra_opening[i15])  # released after the last payment
    assert wf.dsra_closing[-1] == 0.0
    assert identity_gap(res) < 1e-9
    pv = np.sum(res.cfads[i2:i15 + 1] / 1.1 ** np.arange(1, 15))  # LLCR adds the DSRA balance
    assert res.llcr[i2] == pytest.approx((pv + wf.dsra_opening[i2]) / db.opening[i2])


def test_dsra_covers_a_debt_service_shortfall_before_sponsor_support(toll_raw):
    res = run_with(toll_raw, stress={"demand_shortfall": 0.20},
                   reserves={"dsra_months": 6, "dsra_initial_funding": "construction"})
    wf = res.waterfall
    i1 = op(res, 1)
    assert wf.ds_shortfall[i1] > 0
    assert wf.dsra_draw[i1] == pytest.approx(wf.ds_shortfall[i1])
    assert wf.sponsor_support[i1] == 0.0
    assert identity_gap(res) < 1e-9


def test_mmra_contributions_fund_major_maintenance(toll_raw):
    res = run_with(toll_raw, reserves={"mmra_enabled": True})
    ox = res.opex
    for k_start, k_mmr in ((1, 5), (6, 10), (11, 15)):
        contributions = sum(ox.mmra_contribution[op(res, k)] for k in range(k_start, k_mmr + 1))
        assert contributions == pytest.approx(ox.mmr[op(res, k_mmr)])
        assert ox.mmra_release[op(res, k_mmr)] == pytest.approx(ox.mmr[op(res, k_mmr)])
        assert ox.mmra_balance[op(res, k_mmr)] == pytest.approx(0.0, abs=1e-9)
    assert identity_gap(res) < 1e-9


def test_mmra_in_cfads_smooths_the_maintenance_year_dscr(toll_raw, toll_res):
    res = run_with(toll_raw, reserves={"mmra_enabled": True, "mmra_position": "in_cfads"})
    i5 = op(res, 5)
    assert res.dscr[i5] > toll_res.dscr[i5]  # the resurfacing dip is pre-funded
    assert res.waterfall.mmra_contribution.sum() == 0.0  # handled inside CFADS, not below debt service
    after = run_with(toll_raw, reserves={"mmra_enabled": True})
    assert after.dscr[i5] == pytest.approx(toll_res.dscr[i5])  # README §9.11 position: DSCR unchanged
    assert identity_gap(res) < 1e-9


def test_lockup_traps_cash_when_dscr_is_below_the_test(toll_raw):
    res = run_with(toll_raw, reserves={"lockup_dscr": 1.30})
    wf = res.waterfall
    i1, i2 = op(res, 1), op(res, 2)
    assert res.dscr[i1] < 1.30
    assert wf.lockup_trapped[i1] == pytest.approx(res.cfads[i1] - res.debt.debt_service[i1])
    assert wf.distributions[i1] == 0.0
    assert wf.lockup_released[i2] == pytest.approx(wf.lockup_trapped[i1])  # released when the test passes
    assert identity_gap(res) < 1e-9


def test_equity_cash_flow_is_contributions_then_distributions_less_support(toll_raw):
    res = run_with(toll_raw, stress={"demand_shortfall": 0.2})
    wf = res.waterfall
    np.testing.assert_allclose(res.equity_cf, -res.funding.equity + wf.distributions - wf.sponsor_support)
    assert wf.sponsor_support.sum() == pytest.approx(wf.ds_shortfall.sum())
