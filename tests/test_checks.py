"""Automated checks (README §12.1) and the hand check (README §12.3)."""

import dataclasses

import numpy as np
import pytest

from conftest import run_with
from ppp_model.checks import hand_check, run_checks
from ppp_model.scenarios import load_scenarios, run_scenarios


def status(res, cid):
    return next(c for c in res.checks if c.id == cid).status


@pytest.mark.parametrize("ptype", ["toll", "metro", "ham"])
def test_all_integrity_checks_pass_for_every_scenario(ptype):
    from ppp_model import base_config_path, load_yaml
    _, results = run_scenarios(load_yaml(base_config_path(ptype)), load_scenarios())
    for key, res in results.items():
        failed = [(c.id, c.detail) for c in res.checks if c.status == "fail"]
        assert not failed, f"{ptype}/{key}: {failed}"


def test_base_toll_has_no_financial_warnings(toll_res):
    assert all(c.status in {"pass", "info"} for c in toll_res.checks)
    ids = {c.id for c in toll_res.checks}
    assert {"C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08a", "C08b", "C10", "C11"} <= ids


def test_dscr_below_one_generates_warnings_not_hidden_shortfalls(toll_raw):
    res = run_with(toll_raw, stress={"demand_shortfall": 0.20})
    assert status(res, "C10") == "warn" and status(res, "C24") == "warn"
    i1 = res.timeline.index_of_op_year(1)
    shortfall = res.debt.debt_service[i1] - res.cfads[i1]
    assert res.waterfall.ds_shortfall[i1] == pytest.approx(shortfall)
    assert res.waterfall.sponsor_support[i1] == pytest.approx(shortfall)  # recorded, not zeroed
    assert res.equity_cf[i1] == pytest.approx(-shortfall)
    assert any("Debt-service shortfall" in w for w in res.warnings)


def test_maturity_beyond_concession_is_flagged(toll_raw):
    res = run_with(toll_raw, stress={"delay_years": 3})
    assert status(res, "C11") == "warn" and status(res, "C07") == "warn"
    assert not res.metrics.debt_fully_repaid and res.metrics.outstanding_at_end > 0
    assert res.integrity_ok  # reconciliation still holds: principal + outstanding = debt


def test_ham_invariance_checks(ham_res):
    assert status(ham_res, "C12") == "pass" and status(ham_res, "C13") == "pass"


def test_corrupted_results_fail_the_integrity_checks(toll_res):
    fu = toll_res.funding
    broken = dataclasses.replace(toll_res, funding=dataclasses.replace(fu, sources=fu.sources + 0.5))
    assert status_of(run_checks(broken), "C01") == "fail"
    bad_idc = dataclasses.replace(toll_res, funding=dataclasses.replace(fu, idc_iterative=fu.idc + 1e-3))
    assert status_of(run_checks(bad_idc), "C04") == "fail"
    db = toll_res.debt
    negative = dataclasses.replace(toll_res, debt=dataclasses.replace(db, closing=db.closing - 1.0))
    assert status_of(run_checks(negative), "C05") == "fail"
    lost = dataclasses.replace(toll_res, debt=dataclasses.replace(db, principal=db.principal * 0.99))
    assert status_of(run_checks(lost), "C06") == "fail"


def status_of(checks, cid):
    return next(c for c in checks if c.id == cid).status


def test_hand_check_reproduces_readme_section_12_3(toll_res):
    rows = {(r.section, r.item): r for r in hand_check(toll_res)}
    expected = {
        ("Construction year 2", "IDC"): 37.0587,
        ("Construction year 2", "Closing debt"): 523.5577,
        ("Debt service", "Level annuity DS"): 102.4381,
        ("Op year 1", "Revenue"): 148.9200,
        ("Op year 1", "Interest"): 77.9153,
        ("Op year 1", "Principal"): 24.5229,
        ("Op year 1", "Closing debt"): 754.6297,
        ("Op year 1", "Profit before tax"): -14.4703,
        ("Op year 1", "CFADS"): 128.9200,
        ("Op year 1", "DSCR"): 1.2585,
        ("Op year 5 (major maintenance)", "Revenue"): 230.6834,
        ("Op year 5 (major maintenance)", "Opening debt"): 665.3419,
        ("Op year 5 (major maintenance)", "Principal"): 35.9039,
        ("Op year 5 (major maintenance)", "Tax"): 3.4203,
        ("Op year 5 (major maintenance)", "CFADS"): 142.1777,
        ("Op year 5 (major maintenance)", "DSCR"): 1.3879,
        ("Op year 15 (final repayment)", "Principal"): 93.1256,
        ("Op year 15 (final repayment)", "Closing debt"): 0.0,
        ("Op year 15 (final repayment)", "CFADS"): 258.5112,
        ("Op year 15 (final repayment)", "DSCR"): 2.5236,
    }
    for key, value in expected.items():
        assert rows[key].hand_value == pytest.approx(value, abs=1e-4), key
        assert rows[key].ok, key


@pytest.mark.parametrize("fixture", ["toll_res", "metro_res", "ham_res"])
def test_hand_check_agrees_for_every_project_type(fixture, request):
    rows = hand_check(request.getfixturevalue(fixture))
    assert len(rows) > 10
    assert all(r.ok for r in rows), [(r.section, r.item, r.difference) for r in rows if not r.ok]


@pytest.mark.parametrize("overrides", [
    {"debt": {"profile": "equal"}},
    {"debt": {"profile": "structured", "moratorium_years": 2}},
    {"debt": {"profile": "sculpted"}},
    {"stress": {"cost_overrun": 0.2, "overrun_funding": "equity"}},
])
def test_hand_check_holds_for_other_structures(toll_raw, overrides):
    rows = hand_check(run_with(toll_raw, **overrides))
    assert all(r.ok for r in rows), [(r.section, r.item, r.difference) for r in rows if not r.ok]
