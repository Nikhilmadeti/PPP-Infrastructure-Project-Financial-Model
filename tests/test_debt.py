"""Debt schedule: profiles, moratorium, sculpting, sizing and invariants (README §9.9, §12.2)."""

import numpy as np
import pytest

from conftest import op, run_with
from ppp_model import build_inputs, deep_merge
from ppp_model.debt import (
    annuity_payment,
    default_structured_pct,
    schedule_from_principal,
    sculpted_debt_capacity,
    sculpted_schedule,
)
from ppp_model.timeline import build_timeline

D, R = 779.1525369739036, 0.10


def repayment_rows(res):
    rows = np.where(res.timeline.is_repayment > 0)[0]
    return rows, res.debt


def test_hand_check_2_annuity_payment(toll_res):
    assert annuity_payment(D, R, 15) == pytest.approx(102.4381, abs=1e-4)
    assert 1.10 ** 15 == pytest.approx(4.177248, abs=1e-6)
    assert annuity_payment(150.0, 0.0, 15) == 10.0  # zero-rate annuity


def test_annuity_is_flat_and_principal_grows_at_r(toll_res):
    rows, db = repayment_rows(toll_res)
    np.testing.assert_allclose(db.debt_service[rows], db.debt_service[rows[0]], atol=1e-9)
    p1 = db.principal[rows[0]]
    k = np.arange(1, 16)
    np.testing.assert_allclose(db.principal[rows], p1 * 1.1 ** (k - 1), rtol=1e-12)  # P[k] = P[1](1+r)^(k-1)
    assert p1 * 1.1 ** 14 == pytest.approx(93.1256, abs=1e-4)  # hand check 5


def test_equal_principal_identity(toll_raw):
    res = run_with(toll_raw, debt={"profile": "equal"})
    rows, db = repayment_rows(res)
    d = res.funding.debt_at_cod
    k = np.arange(1, 16)
    np.testing.assert_allclose(db.principal[rows], d / 15)
    np.testing.assert_allclose(db.interest[rows], R * d * (1 - (k - 1) / 15))


def test_structured_profile_follows_percentages(toll_raw):
    res = run_with(toll_raw, debt={"profile": "structured"})
    rows, db = repayment_rows(res)
    pct = np.asarray(build_inputs(toll_raw).debt.structured_pct)
    np.testing.assert_allclose(db.principal[rows], res.funding.debt_at_cod * pct)
    assert db.fully_repaid


@pytest.mark.parametrize("profile", ["equal", "annuity", "structured", "sculpted"])
def test_invariants_and_pv_identity_for_every_profile(toll_raw, profile):
    res = run_with(toll_raw, debt={"profile": profile})
    db, tl = res.debt, res.timeline
    assert db.closing.min() >= 0.0
    assert db.principal.sum() == pytest.approx(db.amount, abs=1e-9)
    assert db.fully_repaid and db.closing[op(res, 15)] == pytest.approx(0.0, abs=1e-9)
    k = tl.op_year[tl.cod_index:].astype(float)
    pv = np.sum(db.debt_service[tl.cod_index:] / 1.1 ** k)
    assert pv == pytest.approx(db.amount, rel=1e-10)  # README §12.2 PV identity
    np.testing.assert_allclose(db.interest, R * db.opening)  # interest on the opening balance
    assert res.integrity_ok


def test_moratorium_pays_interest_only(toll_raw):
    res = run_with(toll_raw, debt={"moratorium_years": 2})
    db = res.debt
    for k in (1, 2):
        i = op(res, k)
        assert db.principal[i] == 0.0
        assert db.debt_service[i] == pytest.approx(db.interest[i])
        assert db.opening[i] == pytest.approx(db.amount)
    i3 = op(res, 3)
    assert db.debt_service[i3] == pytest.approx(annuity_payment(db.amount, R, 15))
    assert db.final_repayment_op_year == 17


def test_sculpting_hits_target_dscr_every_year_when_dscr_sizes_the_debt(toll_raw):
    """README §12.2 degenerate case: sculpted with D = D_dscr gives DSCR = target every year."""
    flat = {"revenue": {"toll": {"ramp_up": [], "growth": 0.0, "rate_escalation": 0.0}},
            "opex": {"mmr_base": 0.0, "om_escalation": 0.0},
            "funding": {"gearing": 0.95},
            "debt": {"profile": "sculpted", "sizing": "gearing_and_dscr", "target_dscr": 1.30}}
    res = run_with(toll_raw, **flat)
    rows, db = repayment_rows(res)
    assert res.sizing.binding == "dscr"
    np.testing.assert_allclose(res.dscr[rows], 1.30, atol=1e-7)
    assert not db.floored_years
    assert res.integrity_ok


def test_sculpting_when_gearing_binds_gives_uniform_dscr_above_target(toll_raw):
    flat = {"revenue": {"toll": {"ramp_up": [], "growth": 0.0, "rate_escalation": 0.0}},
            "opex": {"mmr_base": 0.0, "om_escalation": 0.0}, "debt": {"profile": "sculpted"}}
    res = run_with(toll_raw, **flat)
    rows, db = repayment_rows(res)
    pv_cfads = np.sum(res.cfads[rows] / 1.1 ** np.arange(1, 16))
    np.testing.assert_allclose(res.dscr[rows], pv_cfads / db.amount, rtol=1e-9)  # README §9.9
    assert db.sculpt_dscr > 1.30


def test_sculpting_pitfall_negative_principal_is_floored_and_reported(toll_res, toll_raw):
    res = run_with(toll_raw, debt={"profile": "sculpted"})
    db = res.debt
    assert db.floored_years == (1, 5)  # ramp-up year and resurfacing year: sculpted DS below interest
    assert db.principal.min() >= 0.0
    for k in (1, 5):
        assert db.debt_service[op(res, k)] == pytest.approx(db.interest[op(res, k)])
        assert res.dscr[op(res, k)] < db.sculpt_dscr  # the floor lowers DSCR in those years
    assert any("floored at zero" in w for w in res.warnings)


def test_capitalise_rule_lets_the_loan_grow_explicitly(toll_raw):
    res = run_with(toll_raw, debt={"profile": "sculpted", "sculpt_negative_principal": "capitalise"})
    db = res.debt
    assert db.principal[op(res, 1)] < 0 and db.principal[op(res, 5)] < 0  # interest capitalised
    assert db.closing[op(res, 1)] > db.amount
    assert db.capitalised_interest == pytest.approx(-(db.principal[op(res, 1)] + db.principal[op(res, 5)]))
    assert db.fully_repaid
    np.testing.assert_allclose(res.dscr[np.where(res.timeline.is_repayment > 0)[0]], db.sculpt_dscr, rtol=1e-9)


def test_sculpted_debt_capacity_formula(toll_res):
    capacity = sculpted_debt_capacity(toll_res.cfads, R, 1.30, toll_res.timeline)
    rows = np.where(toll_res.timeline.is_repayment > 0)[0]
    assert capacity == pytest.approx(np.sum(toll_res.cfads[rows] / 1.30 / 1.1 ** np.arange(1, 16)))
    assert capacity == pytest.approx(1489.13 / 1.30, abs=0.01)


def test_dscr_sizing_cuts_debt_to_meet_the_target(toll_raw, toll_res):
    res = run_with(toll_raw, debt={"sizing": "gearing_and_dscr", "target_dscr": 1.30})
    assert res.sizing.binding == "dscr"
    assert res.metrics.min_dscr == pytest.approx(1.30, abs=1e-6)
    assert res.metrics.min_dscr >= 1.30 - 1e-9
    assert res.funding.debt_at_cod < toll_res.funding.debt_at_cod
    assert res.funding.gearing < 0.70
    assert res.integrity_ok


def test_dscr_sizing_keeps_gearing_when_it_binds(toll_raw, toll_res):
    res = run_with(toll_raw, debt={"sizing": "gearing_and_dscr", "target_dscr": 1.20})
    assert res.sizing.binding == "gearing"
    assert res.funding.debt_at_cod == pytest.approx(toll_res.funding.debt_at_cod)
    assert res.sizing.debt_dscr_limit > res.funding.debt_at_cod


def test_maturity_beyond_concession_leaves_balance_unpaid(toll_raw):
    inp = build_inputs(deep_merge(toll_raw, {"stress": {"delay_years": 3}}))
    tl = build_timeline(inp)
    db = schedule_from_principal("annuity", D, R, tl)
    assert not db.fully_repaid
    assert db.outstanding_at_end == pytest.approx(D * (1.1 ** 14) - annuity_payment(D, R, 15) * (1.1 ** 14 - 1) / 0.1)
    assert db.principal.sum() + db.outstanding_at_end == pytest.approx(D)
    assert any("not fully repaid" in w for w in db.warnings)


def test_principal_never_exceeds_balance_and_zero_debt_is_handled(toll_raw):
    inp = build_inputs(toll_raw)
    tl = build_timeline(inp)
    zero = schedule_from_principal("annuity", 0.0, R, tl)
    assert zero.debt_service.sum() == 0.0 and zero.fully_repaid and zero.final_repayment_op_year is None
    sculpt_zero = sculpted_schedule(0.0, R, np.ones(tl.model_years), tl, "floor", 1e-10, 200)
    assert sculpt_zero.debt_service.sum() == 0.0


def test_default_structured_profile_rises_and_sums_to_one():
    pct = default_structured_pct(12)
    assert len(pct) == 12 and sum(pct) == pytest.approx(1.0)
    assert all(b > a for a, b in zip(pct, pct[1:]))
