"""Revenue for toll, metro and HAM (README §9.5)."""

import inspect

import numpy as np
import pytest

from conftest import op, run_with
from ppp_model import build_inputs, deep_merge
from ppp_model.revenue import build_revenue, ham_revenue
from ppp_model.timeline import build_timeline


def revenue(raw, **blocks):
    inp = build_inputs(deep_merge(raw, blocks))
    tl = build_timeline(inp)
    return build_revenue(inp, tl), tl


# --- toll -------------------------------------------------------------------------------------


def test_toll_revenue_matches_hand_check_formulas(toll_raw):
    rv, tl = revenue(toll_raw)
    assert rv.total[tl.index_of_op_year(1)] == pytest.approx(24000 * 0.85 * 200 * 365 / 1e7)  # 148.92
    assert rv.total[tl.index_of_op_year(5)] == pytest.approx(24000 * 1.04 ** 4 * 200 * 1.03 ** 4 * 365 / 1e7)
    assert rv.total[tl.index_of_op_year(5)] == pytest.approx(230.6834, abs=1e-4)
    assert rv.total[: tl.construction_years].sum() == 0.0  # no revenue during construction


def test_ramp_up_multiplies_and_is_not_compounded(toll_raw):
    rv, tl = revenue(toll_raw)
    r1, r2, r3 = (rv.total[tl.index_of_op_year(k)] for k in (1, 2, 3))
    assert r2 / r1 == pytest.approx(1.04 * 1.03 * 0.95 / 0.85)
    assert r3 / r2 == pytest.approx(1.04 * 1.03 * 1.00 / 0.95)
    np.testing.assert_allclose(rv.drivers["Ramp-up factor"][tl.cod_index:tl.cod_index + 4], [0.85, 0.95, 1.0, 1.0])


def test_no_ramp_no_growth_gives_constant_revenue(toll_raw):
    rv, tl = revenue(toll_raw, revenue={"toll": {"ramp_up": [], "growth": 0.0, "rate_escalation": 0.0}})
    ops = rv.total[tl.cod_index:]
    np.testing.assert_allclose(ops, ops[0])
    assert ops[0] == pytest.approx(24000 * 200 * 365 / 1e7)


def test_shortfall_and_leakage_scale_revenue(toll_raw):
    base, tl = revenue(toll_raw)
    short, _ = revenue(toll_raw, stress={"demand_shortfall": 0.2})
    leak, _ = revenue(toll_raw, revenue={"toll": {"leakage": 0.05}})
    np.testing.assert_allclose(short.total, base.total * 0.8)
    np.testing.assert_allclose(leak.total, base.total * 0.95)


def test_capacity_cap_limits_vehicles_on_the_road(toll_raw):
    rv, tl = revenue(toll_raw, revenue={"toll": {"capacity": 40000, "leakage": 0.05}})
    on_road = np.minimum(rv.drivers["Traffic after shortfall (PCU/day)"], 40000)
    assert rv.drivers["Capacity cap binding (1=yes)"][-1] == 1.0
    np.testing.assert_allclose(rv.drivers["Paying traffic (PCU/day)"], on_road * 0.95)
    assert rv.drivers["Paying traffic (PCU/day)"].max() == pytest.approx(38000)
    assert any("capacity cap" in n for n in rv.notes)


# --- metro ------------------------------------------------------------------------------------


def test_metro_fare_revisions_every_three_years(metro_raw):
    rv, tl = revenue(metro_raw)
    fares = [rv.drivers["Average fare (₹/trip)"][tl.index_of_op_year(k)] for k in range(1, 8)]
    np.testing.assert_allclose(fares, [30, 30, 30, 33, 33, 33, 36.3])


def test_metro_non_fare_revenue_and_ramp_up(metro_raw):
    rv, tl = revenue(metro_raw)
    i = tl.index_of_op_year(1)
    fare_rev = 300000 * 0.50 * 30 * 365 / 1e7
    assert rv.lines["Fare revenue"][i] == pytest.approx(fare_rev)
    np.testing.assert_allclose(rv.lines["Non-fare revenue"], 0.15 * rv.lines["Fare revenue"])
    assert rv.total[i] == pytest.approx(fare_rev * 1.15)


def test_metro_capacity_cap(metro_raw):
    rv, tl = revenue(metro_raw)
    riders = rv.drivers["Ridership carried (pax/day)"]
    assert riders.max() == pytest.approx(550000)
    first = tl.op_year[np.argmax(rv.drivers["Capacity cap binding (1=yes)"] > 0)]
    demand = 300000 * 1.03 ** (np.arange(1, 31) - 1)
    assert first == int(np.argmax(demand > 550000)) + 1


# --- HAM --------------------------------------------------------------------------------------


def test_ham_construction_support_and_completion_cost(ham_raw):
    rv, tl = revenue(ham_raw)
    np.testing.assert_allclose(rv.construction_support[:2], [0.4 * 1000 * 0.4, 0.4 * 1000 * 0.6 * 1.05])
    assert rv.construction_support.sum() == pytest.approx(412.0)
    assert rv.details["completion_cost"] == pytest.approx(0.6 * 1000 * 1.05 ** 2)  # 661.50


def test_ham_semiannual_annuity_aggregated_to_annual(ham_raw):
    rv, tl = revenue(ham_raw)
    a0 = 661.5
    sched = rv.semiannual
    assert len(sched) == 30
    np.testing.assert_allclose(sched["Annuity principal"], a0 / 30)
    np.testing.assert_allclose(sched["Annuity interest"], 0.0875 / 2 * (a0 - np.arange(30) * a0 / 30))
    assert rv.lines["Annuity principal"].sum() == pytest.approx(a0)
    i1 = tl.index_of_op_year(1)
    h1_interest = 0.0875 / 2 * a0 + 0.0875 / 2 * (a0 - a0 / 30)
    assert rv.lines["Annuity interest"][i1] == pytest.approx(h1_interest)
    assert rv.lines["Annuity principal"][i1] == pytest.approx(2 * a0 / 30)
    assert rv.lines["O&M payment"][i1] == pytest.approx(12.0)
    assert rv.lines["O&M payment"][tl.index_of_op_year(3)] == pytest.approx(12.0 * 1.05 ** 2)


def test_ham_revenue_ignores_traffic_by_construction(ham_raw):
    assert "shortfall" not in inspect.signature(ham_revenue).parameters
    base, _ = revenue(ham_raw)
    for shortfall in (0.1, 0.2, 0.3, 0.9):
        stressed, _ = revenue(ham_raw, stress={"demand_shortfall": shortfall})
        np.testing.assert_array_equal(stressed.total, base.total)
    assert base.demand_sensitive is False


def test_ham_cost_overrun_does_not_raise_revenue(ham_raw, ham_res):
    res = run_with(ham_raw, stress={"cost_overrun": 0.20})
    np.testing.assert_array_equal(res.revenue.total, ham_res.revenue.total)
    np.testing.assert_array_equal(res.revenue.construction_support, ham_res.revenue.construction_support)
    assert res.metrics.total_project_cost > ham_res.metrics.total_project_cost
    assert res.metrics.equity_irr.value < ham_res.metrics.equity_irr.value


def test_ham_with_fixed_end_and_delay_loses_instalments(ham_raw):
    rv, tl = revenue(ham_raw, timeline={"concession_end_fixed": True}, stress={"delay_years": 1})
    assert tl.operating_years == 14
    assert (~rv.semiannual["Within concession"]).sum() == 2
    assert rv.lines["Annuity principal"].sum() < rv.details["completion_cost"]
    assert any("fall after the concession end" in n for n in rv.notes)


def test_revenue_timing_operating_year_k_is_model_year_tc_plus_k(toll_res):
    i = op(toll_res, 1)
    assert toll_res.timeline.year[i] == 4
