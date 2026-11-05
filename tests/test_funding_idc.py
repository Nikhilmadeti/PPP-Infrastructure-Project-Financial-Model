"""Capex, sources and uses, gearing, grant and IDC (README §9.2-9.4, hand check 1)."""

import numpy as np
import pytest

from conftest import run_with
from ppp_model import FundingError, build_inputs, deep_merge
from ppp_model.capex import build_capex, stretch_phasing
from ppp_model.funding import idc_by_iteration, solve_funding
from ppp_model.timeline import build_timeline


def test_hand_check_1_idc_in_construction_year_2(toll_res):
    fu = toll_res.funding
    assert fu.closing_debt[0] == pytest.approx(217.6166, abs=1e-4)
    expected = (0.10 * 217.6166 + 0.5 * 0.10 * 0.70 * 400) / (1 - 0.5 * 0.10 * 0.70)
    assert expected == pytest.approx(37.0587, abs=1e-4)
    assert fu.idc[1] == pytest.approx(expected, abs=1e-4)
    assert fu.debt_draw[1] == pytest.approx(305.9411, abs=1e-4)
    assert 0.10 * (fu.opening_debt[1] + 0.5 * fu.debt_draw[1]) == pytest.approx(fu.idc[1], abs=1e-12)
    assert fu.closing_debt[1] == pytest.approx(523.5577, abs=1e-4)


@pytest.mark.parametrize("overrides", [
    {},
    {"funding": {"equity_mode": "equity_first"}},
    {"funding": {"upfront_fee": 0.01}},
    {"funding": {"grant_pct": 0.2}},
    {"stress": {"cost_overrun": 0.2, "overrun_funding": "equity"}},
    {"funding": {"equity_mode": "equity_first"}, "stress": {"cost_overrun": 0.2, "overrun_funding": "equity"}},
    {"reserves": {"dsra_months": 6, "dsra_initial_funding": "construction"}},
    {"capex": {"escalation": 0.05, "contingency": 0.04, "preop": 0.02}, "stress": {"delay_years": 1}},
])
def test_closed_form_idc_equals_iteration_and_sources_equal_uses(toll_raw, overrides):
    fu = run_with(toll_raw, **overrides).funding
    np.testing.assert_allclose(fu.idc, fu.idc_iterative, atol=1e-6)
    np.testing.assert_allclose(fu.sources, fu.uses, atol=1e-9)
    assert fu.debt_at_cod == pytest.approx(fu.expected_debt, rel=1e-10)
    assert fu.total_project_cost == pytest.approx(fu.grant_total + fu.debt_at_cod + fu.equity_total, abs=1e-9)


def test_idc_iteration_is_independent_of_closed_form(toll_res):
    fu = toll_res.funding
    base_need = fu.capex[:3]
    idc, iterations = idc_by_iteration(base_need, np.zeros(3), np.zeros(3), 0.7, 0.1, 0.5, "pro_rata", 1e-12, 200)
    assert iterations > 1
    np.testing.assert_allclose(idc, [10.8808, 37.0587, 65.1355], atol=1e-4)


def test_equity_first_lowers_idc_and_keeps_total_gearing(toll_raw, toll_res):
    res = run_with(toll_raw, funding={"equity_mode": "equity_first"})
    fu = res.funding
    assert fu.idc_total < toll_res.funding.idc_total
    assert fu.debt_draw[0] == 0.0  # sponsors carry the first loss
    assert fu.equity[0] == pytest.approx(fu.uses[0])
    assert fu.debt_at_cod / (fu.total_project_cost - fu.grant_total) == pytest.approx(0.70, abs=1e-10)


def test_zero_interest_gives_zero_idc(toll_raw):
    fu = run_with(toll_raw, debt={"interest_rate": 0.0}).funding
    assert fu.idc_total == 0.0
    assert fu.debt_at_cod == pytest.approx(700.0)


def test_no_debt_gives_zero_idc(toll_raw):
    fu = run_with(toll_raw, funding={"gearing": 0.0}).funding
    assert fu.idc_total == 0.0 and fu.debt_at_cod == 0.0
    assert fu.equity_total == pytest.approx(1000.0)


def test_pro_rata_overrun_raises_debt_proportionally(toll_raw, toll_res):
    res = run_with(toll_raw, stress={"cost_overrun": 0.10})
    assert res.funding.debt_at_cod == pytest.approx(toll_res.funding.debt_at_cod * 1.10, rel=1e-12)
    assert res.funding.debt_at_cod == pytest.approx(857.07, abs=0.01)  # README §11.5


def test_equity_funded_overrun_leaves_debt_and_idc_unchanged(toll_raw, toll_res):
    res = run_with(toll_raw, stress={"cost_overrun": 0.20, "overrun_funding": "equity"})
    fu, base = res.funding, toll_res.funding
    assert fu.debt_at_cod == pytest.approx(base.debt_at_cod, abs=1e-9)
    assert fu.idc_total == pytest.approx(base.idc_total, abs=1e-9)
    assert fu.equity_total == pytest.approx(base.equity_total + 200.0, abs=1e-9)
    assert fu.equity_only_total == pytest.approx(200.0)


def test_upfront_fee_fixed_point(toll_raw, toll_res):
    fu = run_with(toll_raw, funding={"upfront_fee": 0.01}).funding
    assert fu.fees[0] == pytest.approx(0.01 * fu.debt_at_cod, abs=1e-8)
    assert fu.fees[1:].sum() == 0.0
    assert fu.debt_at_cod > toll_res.funding.debt_at_cod
    assert fu.total_project_cost == pytest.approx(fu.capex_total + fu.fees_total + fu.idc_total)


def test_grant_reduces_the_funding_need_and_is_fixed_at_award(toll_raw):
    res = run_with(toll_raw, funding={"grant_pct": 0.2})
    fu = res.funding
    assert fu.grant_total == pytest.approx(200.0)
    assert fu.debt_at_cod == pytest.approx(0.7 * (fu.total_project_cost - 200.0), rel=1e-12)
    overrun = run_with(toll_raw, funding={"grant_pct": 0.2}, stress={"cost_overrun": 0.1})
    assert overrun.funding.grant_total == pytest.approx(200.0)  # VGF not increased by the overrun
    literal = run_with(toll_raw, funding={"grant_pct": 0.2, "grant_covers_overrun": True}, stress={"cost_overrun": 0.1})
    assert literal.funding.grant_total == pytest.approx(220.0)  # README formula taken literally


def test_grant_larger_than_uses_is_an_error(toll_raw):
    inp = build_inputs(toll_raw)
    tl = build_timeline(inp)
    capex = build_capex(inp, tl)
    with pytest.raises(FundingError, match="exceeds the debt- and equity-fundable capex"):
        solve_funding(capex=capex.capex, equity_only=np.zeros(20), grant=capex.capex * 1.5, tl=tl, gearing=0.7,
                      rate=0.1, drawdown_timing=0.5, upfront_fee=0.0, equity_mode="pro_rata", dsra_initial=0.0,
                      tol=1e-10, max_iter=200)


def test_dsra_funded_at_cod_is_in_project_cost_without_idc(toll_raw, toll_res):
    res = run_with(toll_raw, reserves={"dsra_months": 6, "dsra_initial_funding": "construction"})
    fu = res.funding
    first_ds = res.debt.debt_service[res.timeline.cod_index]
    assert fu.dsra_initial == pytest.approx(0.5 * first_ds, abs=1e-8)  # DSRA <-> debt fixed point
    assert fu.dsra_funding[2] == pytest.approx(fu.dsra_initial)
    np.testing.assert_allclose(fu.idc, toll_res.funding.idc, atol=1e-9)  # drawn at year end: no IDC
    assert fu.total_project_cost == pytest.approx(toll_res.funding.total_project_cost + fu.dsra_initial)


def test_capex_formula_with_escalation_contingency_preop(toll_raw):
    inp = build_inputs(deep_merge(toll_raw, {"capex": {"escalation": 0.05, "contingency": 0.04, "preop": 0.02},
                                             "stress": {"cost_overrun": 0.1}}))
    cx = build_capex(inp, build_timeline(inp))
    for t, p in enumerate([0.3, 0.4, 0.3]):
        hard = 1000 * p * 1.05 ** t * 1.1
        assert cx.hard_cost[t] == pytest.approx(hard)
        assert cx.capex[t] == pytest.approx(hard * 1.06)
        assert cx.overrun[t] == pytest.approx(hard * 1.06 - hard / 1.1 * 1.06)


def test_stretch_phasing_for_a_one_year_delay():
    np.testing.assert_allclose(stretch_phasing([0.3, 0.4, 0.3], 4), [0.225, 0.275, 0.275, 0.225])
    assert stretch_phasing([0.3, 0.4, 0.3], 5).sum() == pytest.approx(1.0)


def test_delay_adds_idc_and_uses_stretched_phasing(toll_raw, toll_res):
    res = run_with(toll_raw, stress={"delay_years": 1})
    np.testing.assert_allclose(res.capex.phasing[:4], [0.225, 0.275, 0.275, 0.225])
    assert res.capex.phasing_source == "stretched S-curve"
    assert res.funding.idc_total > toll_res.funding.idc_total
    explicit = run_with(toll_raw, stress={"delay_years": 1, "delay_phasing": [0.3, 0.4, 0.3, 0.0]})
    assert explicit.capex.phasing_source == "explicit delay phasing"
