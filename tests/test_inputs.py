"""Input loading and validation (README §8, Phase 1 'bad inputs raise clear errors')."""

import copy

import pytest

from ppp_model import InputValidationError, build_inputs, deep_merge, inputs_to_dict, load_inputs
from ppp_model.inputs import base_config_path


def errors_for(raw: dict, **blocks) -> list[str]:
    with pytest.raises(InputValidationError) as info:
        build_inputs(deep_merge(raw, blocks))
    return info.value.errors


@pytest.mark.parametrize("ptype", ["toll", "metro", "ham"])
def test_base_configs_load_and_validate(ptype):
    inputs = load_inputs(base_config_path(ptype))
    assert inputs.project_type == ptype
    assert inputs.revenue_block is getattr(inputs.revenue, ptype)


def test_round_trip_through_plain_dict(toll_raw):
    inputs = build_inputs(toll_raw)
    assert build_inputs(inputs_to_dict(inputs)) == inputs


def test_unknown_key_is_rejected_with_suggestion(toll_raw):
    errs = errors_for(toll_raw, debt={"intrest_rate": 0.1})
    assert any("debt.intrest_rate: unknown input key (did you mean 'interest_rate'?)" in e for e in errs)


def test_unknown_block_is_rejected(toll_raw):
    errs = errors_for(toll_raw, finance={"x": 1})
    assert any(e.startswith("finance: unknown input key") for e in errs)


def test_missing_required_input(toll_raw):
    raw = copy.deepcopy(toll_raw)
    del raw["debt"]["interest_rate"]
    with pytest.raises(InputValidationError, match="debt.interest_rate: required input is missing"):
        build_inputs(raw)


def test_phasing_must_sum_to_100_percent(toll_raw):
    errs = errors_for(toll_raw, capex={"phasing": [0.3, 0.4, 0.2]})
    assert any("capex.phasing: shares must sum to 100%" in e for e in errs)


def test_phasing_length_must_match_construction_period(toll_raw):
    errs = errors_for(toll_raw, capex={"phasing": [0.5, 0.5]})
    assert any("needs exactly 3 values" in e for e in errs)


@pytest.mark.parametrize("block,key,value,fragment", [
    ("funding", "gearing", 1.0, "funding.gearing"),
    ("funding", "gearing", -0.1, "funding.gearing"),
    ("debt", "interest_rate", -0.01, "debt.interest_rate"),
    ("tax", "rate", 1.2, "tax.rate"),
    ("debt", "target_dscr", 0.9, "debt.target_dscr"),
    ("funding", "drawdown_timing", 1.5, "funding.drawdown_timing"),
])
def test_out_of_range_percentages_are_rejected_not_clipped(toll_raw, block, key, value, fragment):
    errs = errors_for(toll_raw, **{block: {key: value}})
    assert any(e.startswith(fragment) and "outside the allowed range" in e for e in errs)


def test_wrong_types_are_rejected(toll_raw):
    errs = errors_for(toll_raw, debt={"interest_rate": "ten percent", "tenor_years": 15.5})
    assert any("debt.interest_rate: expected a number" in e for e in errs)
    assert any("debt.tenor_years: must be a whole number" in e for e in errs)


def test_yaml_style_string_number_is_rejected(toll_raw):
    errs = errors_for(toll_raw, solver={"tolerance": "1e-9"})  # PyYAML reads 1e-9 as text
    assert any("solver.tolerance: expected a number" in e for e in errs)


def test_fractional_delay_is_rejected_because_periods_are_annual(toll_raw):
    errs = errors_for(toll_raw, stress={"delay_years": 0.5})
    assert any("stress.delay_years: must be a whole number" in e for e in errs)


def test_tenor_beyond_concession_is_rejected_in_the_base_case(toll_raw):
    errs = errors_for(toll_raw, debt={"tenor_years": 16, "moratorium_years": 2})
    assert any("exceeds the 17-year operating period" in e for e in errs)


def test_structured_percentages_must_match_tenor_and_sum(toll_raw):
    errs = errors_for(toll_raw, debt={"profile": "structured", "structured_pct": [0.5, 0.5]})
    assert any("debt.structured_pct: needs exactly 15 values" in e for e in errs)


def test_invalid_profile_name(toll_raw):
    errs = errors_for(toll_raw, debt={"profile": "balloon"})
    assert any("debt.profile: must be one of" in e for e in errs)


def test_ramp_up_factor_above_one_is_rejected(toll_raw):
    errs = errors_for(toll_raw, revenue={"toll": {"ramp_up": [0.8, 1.2]}})
    assert any("ramp-up factors must be in (0, 1]" in e for e in errs)


def test_revenue_block_must_match_project_type(toll_raw):
    errs = errors_for(toll_raw, project={"type": "metro"})
    assert any("revenue.metro block is missing" in e for e in errs)


def test_ham_grant_must_be_zero(ham_raw):
    errs = errors_for(ham_raw, funding={"grant_pct": 0.1})
    assert any("HAM construction support is the grant" in e for e in errs)


def test_ham_annuity_must_fit_operating_period(ham_raw):
    errs = errors_for(ham_raw, revenue={"ham": {"annuity_instalments": 40}})
    assert any("40 instalments need 20 operating years" in e for e in errs)


def test_delay_that_leaves_no_operations_is_rejected(toll_raw):
    errs = errors_for(toll_raw, stress={"delay_years": 17})
    assert any("leaves 0 operating years" in e for e in errs)


def test_all_problems_reported_together(toll_raw):
    errs = errors_for(toll_raw, funding={"gearing": 2.0}, tax={"rate": -1.0}, capex={"phasing": [1.0]})
    assert len(errs) >= 3


def test_deep_merge_never_mutates_its_inputs(toll_raw):
    before = copy.deepcopy(toll_raw)
    override = {"stress": {"demand_shortfall": 0.2}, "revenue": {"toll": {"ramp_up": [0.7]}}}
    override_before = copy.deepcopy(override)
    merged = deep_merge(toll_raw, override)
    assert toll_raw == before and override == override_before
    assert merged["stress"]["demand_shortfall"] == 0.2
    assert merged["stress"]["cost_overrun"] == 0.0  # untouched sibling kept
    assert merged["revenue"]["toll"]["ramp_up"] == [0.7]  # lists are replaced, not merged
    merged["revenue"]["toll"]["ramp_up"].append(1.0)
    assert toll_raw["revenue"]["toll"]["ramp_up"] == [0.85, 0.95, 1.0]


def test_inputs_are_immutable(toll_raw):
    inputs = build_inputs(toll_raw)
    with pytest.raises(AttributeError):
        inputs.debt.interest_rate = 0.2  # frozen dataclass


def test_effective_interest_rate_includes_rate_shock(toll_raw):
    inputs = build_inputs(deep_merge(toll_raw, {"stress": {"rate_shock": 0.01}}))
    assert inputs.interest_rate == pytest.approx(0.11)
    assert inputs.debt.interest_rate == 0.10  # base input itself is untouched
