"""Scenario engine and sensitivities (README §10, §11.5)."""

import copy
from pathlib import Path

import numpy as np
import pytest

from conftest import run_with
from ppp_model import InputValidationError, run_model
from ppp_model.scenarios import (
    Scenario,
    break_even_shortfall,
    ham_traffic_demonstration,
    load_scenarios,
    profile_comparison,
    run_scenario,
    run_scenarios,
    tornado,
    two_way_table,
)

TOL, TOL_PCT = 0.01, 1e-4

# README §11.5: scenario -> (min DSCR, avg DSCR, LLCR at COD, Project IRR, Equity IRR)
README_11_5 = {
    "base": (1.26, 2.11, 1.91, 0.1394, 0.2002),
    "traffic_m10": (1.11, 1.89, 1.72, 0.1248, 0.1698),
    "traffic_m20": (0.97, 1.68, 1.53, 0.1090, 0.1360),
    "cost_p10": (1.14, 1.94, 1.76, 0.1281, 0.1768),
    "cost_p20": (1.05, 1.80, 1.64, 0.1182, 0.1559),
    "combined_down": (0.81, 1.45, 1.31, 0.0900, 0.0944),  # README avg 1.45 is a rounding slip for 1.4445
}


@pytest.fixture(scope="module")
def config():
    return load_scenarios()


@pytest.fixture(scope="module")
def toll_table():
    from ppp_model import base_config_path, load_yaml
    return run_scenarios(load_yaml(base_config_path("toll")), load_scenarios())


@pytest.mark.parametrize("key", sorted(README_11_5))
def test_readme_section_11_5_scenario_results(toll_table, key):
    table, _ = toll_table
    min_dscr, avg, llcr, p_irr, e_irr = README_11_5[key]
    row = table.loc[key]
    assert row["Min DSCR"] == pytest.approx(min_dscr, abs=TOL)
    assert row["Avg DSCR"] == pytest.approx(avg, abs=TOL)
    assert row["LLCR at COD"] == pytest.approx(llcr, abs=TOL)
    assert row["Project IRR"] == pytest.approx(p_irr, abs=TOL_PCT)
    assert row["Equity IRR"] == pytest.approx(e_irr, abs=TOL_PCT)


def test_readme_scenario_verdicts_and_flags(toll_table):
    table, results = toll_table
    assert table.loc["base", "Verdict"] == "Bankable"
    assert table.loc["traffic_m20", "Any DSCR < 1.0?"] == "Yes"
    assert results["traffic_m20"].metrics.dscr_below_one_years == (1, 5)  # README mentions year 1 only
    assert table.loc["combined_down", "Verdict"].startswith("Not bankable")
    assert table.loc["cost_p10", "Debt"] == pytest.approx(857.07, abs=TOL)
    assert (table["Integrity checks"] == "Pass").all()


def test_every_scenario_starts_from_a_fresh_base(toll_raw, config, toll_table):
    before = copy.deepcopy(toll_raw)
    run_scenarios(toll_raw, config)
    assert toll_raw == before
    _, results = toll_table
    alone = run_scenario(toll_raw, config.scenarios["cost_p10"])
    assert alone.metrics.equity_irr.value == results["cost_p10"].metrics.equity_irr.value
    assert results["base"].metrics.min_dscr == pytest.approx(1.2585, abs=1e-4)


def test_traffic_shortfall_30_percent_binds_in_the_maintenance_year(toll_table):
    table, _ = toll_table
    assert table.loc["traffic_m30", "Min DSCR op year"] == 5


def test_equity_funded_overrun_keeps_debt_and_dscr(toll_table):
    table, _ = toll_table
    base, eq = table.loc["base"], table.loc["cost_p20_equity"]
    assert eq["Debt"] == pytest.approx(base["Debt"])
    assert eq["Min DSCR"] == pytest.approx(base["Min DSCR"])
    assert eq["Equity"] == pytest.approx(base["Equity"] + 200.0)
    assert eq["Equity IRR"] < table.loc["cost_p20", "Equity IRR"] < base["Equity IRR"]


def test_delay_scenario_costs_idc_and_operating_years(toll_table):
    table, results = toll_table
    res = results["delay_1yr"]
    assert res.timeline.model_years == 20 and res.timeline.operating_years == 16
    assert table.loc["delay_1yr", "IDC"] > table.loc["base", "IDC"]
    assert res.metrics.tail_years == 1
    assert table.loc["delay_1yr", "Equity IRR"] < table.loc["base", "Equity IRR"]


def test_rate_shock_leaves_project_irr_unchanged(toll_table):
    table, _ = toll_table
    assert table.loc["rate_p100bp", "Project IRR"] == pytest.approx(table.loc["base", "Project IRR"], abs=1e-12)
    assert table.loc["rate_p100bp", "IDC"] > table.loc["base", "IDC"]
    assert table.loc["rate_p100bp", "Equity IRR"] < table.loc["base", "Equity IRR"]


def test_break_even_traffic_shortfall_is_17_8_percent(toll_raw):
    result = break_even_shortfall(toll_raw)
    assert result.status == "found"
    assert result.value == pytest.approx(1 - 122.4381 / 148.92, abs=1e-5)  # README: 1 - 122.44/148.92
    assert result.value == pytest.approx(0.178, abs=5e-4)
    assert result.binding_op_year == 1
    at = run_with(toll_raw, stress={"demand_shortfall": result.value})
    assert at.metrics.min_dscr == pytest.approx(1.0, abs=1e-5)


def test_break_even_for_equity_hurdle(toll_raw):
    result = break_even_shortfall(toll_raw, metric="equity_irr", threshold=0.15)
    assert result.status == "found" and 0.15 < result.value < 0.178


def test_break_even_infeasible_cases_are_distinguished(toll_raw, ham_raw):
    assert break_even_shortfall(ham_raw).status == "not_applicable"
    already = break_even_shortfall(run_with_raw(toll_raw, debt={"profile": "equal"}))
    assert already.status == "already_breached"
    no_debt = break_even_shortfall(run_with_raw(toll_raw, funding={"gearing": 0.0}))
    assert no_debt.status == "not_reached" and no_debt.value is None


def run_with_raw(raw, **blocks):
    from ppp_model import deep_merge
    return deep_merge(raw, blocks)


def test_two_way_table_is_monotonic_and_anchored_at_base(toll_raw, config):
    table = two_way_table(toll_raw, config.two_way_shortfalls, config.two_way_overruns)
    assert table.shape == (7, 7)
    assert table.iloc[0, 0] == pytest.approx(1.2585, abs=1e-4)
    assert table.loc[0.2, 0.2] == pytest.approx(0.8065, abs=1e-4)  # combined downside
    assert (np.diff(table.values, axis=0) < 0).all() and (np.diff(table.values, axis=1) < 0).all()


def test_tornado_ranks_inputs_by_equity_irr_range(toll_raw, config):
    df = tornado(toll_raw, config.tornado_variables["toll"], config.tornado_shock)
    assert len(df) == len(config.tornado_variables["toll"])
    ranges = df["Equity IRR range"].to_numpy()
    assert (np.diff(ranges) <= 1e-12).all()
    assert df.iloc[0]["Variable"] in {"Traffic (AADT)", "Toll rate", "Hard cost"}
    traffic = df.set_index("Variable").loc["Traffic (AADT)"]
    assert traffic["Δ Equity IRR (low)"] < 0 < traffic["Δ Equity IRR (high)"]
    assert df.attrs["base_equity_irr"] == pytest.approx(0.2002, abs=1e-4)


def test_ham_traffic_shortfall_has_no_effect(ham_raw):
    demo = ham_traffic_demonstration(ham_raw, 0.20)
    assert demo.attrs["max_revenue_difference"] == 0.0
    assert demo.iloc[0].equals(demo.iloc[1])


def test_ham_scenario_table_traffic_rows_equal_base_but_cost_rows_do_not(ham_raw, config):
    table, _ = run_scenarios(ham_raw, config)
    metrics = ["Min DSCR", "LLCR at COD", "Equity IRR", "TPC", "Debt"]
    for key in ("traffic_m10", "traffic_m20", "traffic_m30", "slow_rampup"):
        assert table.loc[key, metrics].tolist() == table.loc["base", metrics].tolist()
    assert table.loc["cost_p20", "Equity IRR"] < table.loc["base", "Equity IRR"]
    assert table.loc["cost_p20", "Min DSCR"] < table.loc["base", "Min DSCR"]


def test_profile_comparison_shows_front_loaded_repayment_risk(toll_raw):
    table, _ = profile_comparison(toll_raw)
    assert table.loc["equal", "Min DSCR"] == pytest.approx(0.99, abs=TOL)
    assert table.loc["annuity", "Min DSCR"] == pytest.approx(1.26, abs=TOL)
    assert table.loc["equal", "Min DSCR"] < table.loc["structured", "Min DSCR"]


def test_unknown_scenario_override_key_names_the_scenario(toll_raw):
    bad = Scenario("typo", "Typo", overrides={"stress": {"demand_shortfal": 0.1}})
    with pytest.raises(InputValidationError, match="scenario 'typo'.*did you mean 'demand_shortfall'"):
        run_scenario(toll_raw, bad)


def test_scenario_file_structure_is_validated(tmp_path: Path):
    path = tmp_path / "scenarios.yaml"
    path.write_text("scenarios:\n  base: {label: Base}\n  x: {lable: X}\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="unknown key"):
        load_scenarios(path)
    path.write_text("scenarios:\n  x: {label: X}\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="'base' scenario"):
        load_scenarios(path)


def test_metro_needs_its_grant(metro_raw, metro_res):
    no_grant = run_with(metro_raw, funding={"grant_pct": 0.0})
    assert metro_res.metrics.min_dscr >= metro_res.inputs.covenants.min_dscr
    assert metro_res.metrics.equity_meets_hurdle
    assert no_grant.metrics.min_dscr < 1.0
    assert no_grant.metrics.equity_meets_hurdle is False
    assert metro_res.metrics.project_irr.value < metro_res.inputs.valuation.discount_rate  # fare box alone
