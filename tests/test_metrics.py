"""Lender metrics and returns (README §9.12-9.13, §12.2)."""

import numpy as np
import numpy_financial as npf
import pytest

from conftest import op, run_with
from ppp_model.metrics import irr, npv, payback


def test_known_irr():
    result = irr([-100, 110])
    assert result.ok and result.value == pytest.approx(0.10, abs=1e-12)
    assert result.numpy_financial == pytest.approx(0.10, abs=1e-12)


def test_irr_agrees_with_numpy_financial_on_readme_cash_flows(toll_res):
    for cf in (toll_res.project_cf, toll_res.equity_cf):
        result = irr(cf)
        assert result.ok
        assert result.value == pytest.approx(npf.irr(cf), abs=1e-10)
        assert abs(npv(result.value, cf)) < 1e-6


def test_multiple_irrs_are_not_reported_as_one():
    result = irr([-100, 230, -132])  # roots at 10% and 20%
    assert result.value is None and result.status == "multiple"
    assert result.roots == pytest.approx((0.10, 0.20), abs=1e-10)
    assert "Multiple IRRs" in result.message


def test_no_sign_change_means_no_irr():
    for cf in ([100, 50, 20], [-10, -5, -1], [0, 0, 0]):
        result = irr(cf)
        assert result.value is None and result.status == "no_sign_change"


def test_root_outside_search_range_is_not_invented():
    result = irr([-1, 0, 1e-7])  # IRR about -99.97%
    assert result.value is None and result.status == "no_root"


def test_negative_irr_is_found():
    result = irr([-100, 50, 40])
    assert result.ok and result.value < 0
    assert abs(npv(result.value, [-100, 50, 40])) < 1e-9


def test_npv_convention_values_at_financial_close():
    cf = [-100, 60, 60]
    assert npv(0.1, cf) == pytest.approx(-100 / 1.1 + 60 / 1.1 ** 2 + 60 / 1.1 ** 3)
    assert npv(0.1, cf) == pytest.approx(npf.npv(0.1, cf) / 1.1)  # numpy-financial discounts from t=0


def test_dscr_only_where_debt_service_is_positive(toll_res):
    ds = toll_res.debt.debt_service
    assert np.all(np.isnan(toll_res.dscr[ds <= 0]))
    assert not np.any(np.isnan(toll_res.dscr[ds > 0]))
    rows = ds > 0
    assert toll_res.metrics.avg_dscr == pytest.approx(np.mean(toll_res.cfads[rows] / ds[rows]))


def test_dscr_cushion_interpretation(toll_res):
    assert 1 - 1 / toll_res.metrics.min_dscr == pytest.approx(0.205, abs=1e-3)  # README: CFADS can fall ~20.6%


def test_llcr_and_plcr(toll_res):
    i = op(toll_res, 1)
    pv15 = np.sum(toll_res.cfads[i:i + 15] / 1.1 ** np.arange(1, 16))
    assert pv15 == pytest.approx(1489.13, abs=0.01)
    assert toll_res.llcr[i] == pytest.approx(pv15 / 779.1525, abs=1e-4)
    pv17 = np.sum(toll_res.cfads[i:] / 1.1 ** np.arange(1, 18))
    assert toll_res.plcr[i] == pytest.approx(pv17 / 779.1525, abs=1e-4)
    assert toll_res.metrics.plcr_cod > toll_res.metrics.llcr_cod  # the tail adds cushion
    i5 = op(toll_res, 5)
    pv_from_5 = np.sum(toll_res.cfads[i5:i + 15] / 1.1 ** np.arange(1, 12))
    assert toll_res.llcr[i5] == pytest.approx(pv_from_5 / toll_res.debt.opening[i5])
    assert np.isnan(toll_res.llcr[op(toll_res, 16)])  # no debt in the tail


def test_icr(toll_res):
    i = op(toll_res, 1)
    assert toll_res.icr[i] == pytest.approx(128.92 / 77.9153, abs=1e-4)
    assert toll_res.metrics.min_icr == pytest.approx(toll_res.icr[i])


def test_equity_payback(toll_res):
    pb = toll_res.metrics.payback
    cumulative = np.cumsum(toll_res.equity_cf)
    first = int(np.argmax(cumulative >= 0))
    assert pb.status == "achieved" and pb.model_year == first + 1
    assert cumulative[first - 1] < 0 <= cumulative[first]
    never = np.array([-100.0] + [1.0] * 19)  # cumulative ends at -81
    assert payback(never, toll_res.timeline).status == "not_achieved"
    assert payback(np.zeros(20), toll_res.timeline).status == "no_investment"


def test_no_debt_equity_irr_equals_project_irr(toll_raw):
    """README §12.2 degenerate case: g = 0 gives IDC = 0 and Equity IRR = Project IRR."""
    res = run_with(toll_raw, funding={"gearing": 0.0})
    mt = res.metrics
    assert mt.idc == 0.0 and mt.debt == 0.0
    assert mt.equity_irr.value == pytest.approx(mt.project_irr.value, abs=1e-12)
    np.testing.assert_allclose(res.equity_cf, res.project_cf, atol=1e-9)
    assert mt.min_dscr is None and mt.llcr_cod is None


def test_project_irr_is_independent_of_financing(toll_raw, toll_res):
    for overrides in ({"debt": {"interest_rate": 0.13}}, {"funding": {"gearing": 0.5}},
                      {"debt": {"profile": "equal"}}):
        assert run_with(toll_raw, **overrides).metrics.project_irr.value == pytest.approx(
            toll_res.metrics.project_irr.value, abs=1e-12)


def test_hurdle_status_and_npv(toll_res, toll_raw):
    assert toll_res.metrics.equity_meets_hurdle is True
    assert toll_res.metrics.project_npv == pytest.approx(npv(0.12, toll_res.project_cf))
    stressed = run_with(toll_raw, stress={"demand_shortfall": 0.2})
    assert stressed.metrics.equity_meets_hurdle is False
