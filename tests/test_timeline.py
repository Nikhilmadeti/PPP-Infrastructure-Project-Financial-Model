"""Timeline and flags (README §9.1), including construction delays with a fixed concession end."""

import numpy as np
import pytest

from ppp_model import InputValidationError, build_inputs, deep_merge
from ppp_model.timeline import build_timeline


def timeline(raw, **blocks):
    return build_timeline(build_inputs(deep_merge(raw, blocks)))


def test_base_timeline_has_3_construction_and_17_operating_years(toll_raw):
    tl = timeline(toll_raw)
    assert (tl.construction_years, tl.operating_years, tl.model_years) == (3, 17, 20)
    np.testing.assert_array_equal(tl.year, np.arange(1, 21))
    np.testing.assert_array_equal(tl.op_year, np.arange(1, 21) - 3)
    assert tl.is_construction.sum() == 3 and tl.is_construction[:3].all()
    assert tl.is_operation.sum() == 17 and not tl.is_operation[:3].any()
    assert tl.labels[0] == "FY2026-27" and tl.labels[-1] == "FY2045-46"


def test_repayment_flags_follow_moratorium_and_tenor(toll_raw):
    tl = timeline(toll_raw)
    np.testing.assert_array_equal(tl.op_year[tl.is_repayment > 0], np.arange(1, 16))
    assert tl.contractual_tail_years == 2
    tl2 = timeline(toll_raw, debt={"moratorium_years": 2})
    np.testing.assert_array_equal(tl2.op_year[tl2.is_moratorium > 0], [1, 2])
    np.testing.assert_array_equal(tl2.op_year[tl2.is_repayment > 0], np.arange(3, 18))
    assert tl2.contractual_tail_years == 0


def test_escalation_exponent_is_k_minus_one(toll_raw):
    tl = timeline(toll_raw)
    ops = tl.is_operation > 0
    np.testing.assert_array_equal(tl.index_exponent[ops], tl.op_year[ops] - 1)
    assert not tl.index_exponent[~ops].any()


def test_delay_keeps_the_concession_end_fixed(toll_raw):
    tl = timeline(toll_raw, stress={"delay_years": 1})
    assert (tl.construction_years, tl.operating_years, tl.model_years) == (4, 16, 20)
    assert tl.contractual_tail_years == 1
    assert any("operations shrink from 17 to 16 years" in n for n in tl.notes)


def test_delay_that_breaks_the_tenor_is_reported_not_extended(toll_raw):
    tl = timeline(toll_raw, stress={"delay_years": 3})
    assert tl.model_years == 20 and tl.operating_years == 14
    assert not tl.maturity_within_concession
    assert tl.last_repayment_op_year == 14
    assert any("after the concession end" in n for n in tl.notes)


def test_delay_with_operations_tied_to_cod_extends_the_end_date(ham_raw):
    tl = timeline(ham_raw, stress={"delay_years": 1})
    assert (tl.construction_years, tl.operating_years, tl.model_years) == (3, 15, 18)
    assert any("concession ends 1 year(s) later" in n for n in tl.notes)


def test_calendar_indexation_counts_years_since_scheduled_cod(toll_raw):
    tl = timeline(toll_raw, stress={"delay_years": 1}, timeline={"indexation_basis": "calendar"})
    first_op = tl.index_of_op_year(1)
    assert tl.index_exponent[first_op] == 1  # one year of growth / escalation during the delay


def test_delay_leaving_no_operations_raises(toll_raw):
    with pytest.raises(InputValidationError):
        timeline(toll_raw, stress={"delay_years": 17})


def test_index_of_op_year_bounds(toll_raw):
    tl = timeline(toll_raw)
    assert tl.index_of_op_year(1) == 3 and tl.index_of_op_year(17) == 19
    with pytest.raises(IndexError):
        tl.index_of_op_year(18)
